#!/usr/bin/env sh
# Container entrypoint: optionally run Alembic, then start uvicorn.
# Set RUN_MIGRATIONS_ON_START=true when DATABASE_URL points at your durable DB
# (use an async URL, e.g. postgresql+asyncpg://... for PostgreSQL).

set -e

if [ "${RUN_MIGRATIONS_ON_START:-}" = "true" ]; then
  if [ -z "${DATABASE_URL:-}" ]; then
    echo "docker_entrypoint: RUN_MIGRATIONS_ON_START=true but DATABASE_URL is empty; skipping migrations" >&2
  else
    echo "docker_entrypoint: alembic upgrade head"
    alembic upgrade head
  fi
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
