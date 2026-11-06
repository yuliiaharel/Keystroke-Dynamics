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

# --workers 1: explicit, not just uvicorn's own default -- the
# anonymous game's store (game/store.py) lives in this one process's
# memory; a second worker would get its own, independent copy (see
# main.py's docstring).
#
# --proxy-headers --forwarded-allow-ips='*': DigitalOcean App
# Platform (and every platform this image is meant to run behind)
# terminates TLS at its own edge and reaches this container only
# through its own internal proxy -- there is no other inbound path,
# so trusting that proxy's X-Forwarded-Proto/X-Forwarded-For is safe
# here specifically. Without this, uvicorn's own default
# (forwarded-allow-ips=127.0.0.1) ignores both headers unless the
# proxy connects from localhost, which it doesn't in a container:
# request.url.scheme would read "http" even on the live HTTPS site
# (breaking the Secure session cookie -- see main.py's
# https_only=not settings.debug) and client_ip() (api/security.py)
# would rate-limit the platform's own proxy address instead of each
# real visitor's.
CMD ["uvicorn", "keystroke_dynamics.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*"]
