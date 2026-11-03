# syntax=docker/dockerfile:1

# ---- Stage 1: build the frontend ------------------------------------------
FROM node:22-alpine AS frontend-builder
WORKDIR /repo

COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci

COPY frontend/ frontend/
COPY src/keystroke_dynamics/static/css src/keystroke_dynamics/static/css
RUN cd frontend && npm run build

# ---- Stage 2: the application ----------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Dependencies first, in their own layer -- editing application code
# shouldn't invalidate this and force a full reinstall.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY alembic.ini ./
COPY migrations/ migrations/
COPY src/ src/
COPY --from=frontend-builder /repo/src/keystroke_dynamics/static/js src/keystroke_dynamics/static/js
RUN uv sync --locked --no-dev

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "keystroke_dynamics.main:app", "--host", "0.0.0.0", "--port", "8000"]
