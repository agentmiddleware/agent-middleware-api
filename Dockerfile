FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016 AS base

FROM base AS builder

WORKDIR /build

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Compilers are needed only while building Python dependencies.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# The shared manifest keeps development tools after this required marker.
# Fail the build if that boundary is missing or duplicated.
COPY requirements.txt .
RUN test "$(grep -c -x '# --- Development ---' requirements.txt)" -eq 1 \
    && sed '/^# --- Development ---$/,$d' requirements.txt > requirements-runtime.txt \
    && python -m venv --without-pip /opt/venv \
    && python -m pip --python /opt/venv install --no-cache-dir -r requirements-runtime.txt \
    && python -m pip --python /opt/venv check

FROM base AS runtime

# DSA-6530-1 fixes CVE-2026-103111; keep the required shared library patched.
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade libpcre2-8-0 \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' libpcre2-8-0)" ge '10.46-1~deb13u3' \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes pip

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY . .

# Release contexts must carry a commit stamp generated from the exact Git tree.
COPY .build_commit_sha /app/.build_commit_sha

RUN chmod +x scripts/docker_entrypoint.sh \
    && groupadd --system app \
    && useradd --system --gid app --no-create-home --home-dir /app app \
    && chown -R app:app /app

USER app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://localhost:{os.getenv('PORT', '8000')}/health\")"

# Optional: RUN_MIGRATIONS_ON_START=true + DATABASE_URL runs Alembic before uvicorn
# (fail-closed if the flag is set without DATABASE_URL). See docs/deploy-railway.md.
ENTRYPOINT ["scripts/docker_entrypoint.sh"]
