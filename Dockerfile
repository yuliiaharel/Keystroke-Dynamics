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

# alembic_scores.ini/migrations_scores/ (docs/plans/done/PARTY_LAUNCH_PLAN.md section
# 10) are a separate migration run from alembic.ini/migrations/ (the
# account system's) -- .do/app.yaml's pre-deploy job runs them with
# this same image, overriding CMD below with its own run_command.
COPY alembic.ini alembic_scores.ini ./
COPY migrations/ migrations/
COPY migrations_scores/ migrations_scores/
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
# Deliberately NOT --proxy-headers/--forwarded-allow-ips: that would
# make uvicorn trust X-Forwarded-For to rewrite request.client, and
# with --forwarded-allow-ips='*' (the setting that was here before)
# it uses the *first* entry in that header -- which a client fully
# controls -- as the trusted client address. api/security.py's
# client_ip() reads DigitalOcean's own Do-Connecting-Ip header
# directly instead, which the client cannot set (see that function's
# docstring), so none of this app's security decisions need uvicorn's
# own proxy-header handling at all. The Secure session cookie flag
# (main.py's https_only=not settings.debug) was never affected by
# this either way -- it's driven by settings.debug directly, not by
# any detected request scheme.
#
# --timeout-graceful-shutdown 5: a live-update stream
# (GET /api/game/room/events) stays open for as long as its browser
# does, and without a limit uvicorn waits for every connection to
# close before it runs the app's shutdown. One open tab would hold a
# deploy's old container until it was killed, skipping the score
# writer's final flush (main.py's lifespan). Ordinary requests finish
# in well under 5 seconds; browsers reconnect to the new container on
# their own.
CMD ["uvicorn", "keystroke_dynamics.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--timeout-graceful-shutdown", "5"]
