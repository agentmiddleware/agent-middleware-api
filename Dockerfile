FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code. Release contexts prepared by
# scripts/prepare_railway_release.py carry a .build_commit_sha stamp file, so
# it arrives via this COPY. The guard below refuses an unstamped context
# instead of shipping an image with unknown provenance.
COPY . .

# Fail closed when the stamp is missing. A bare `docker build` on a plain
# checkout stops here with the remediation below instead of a cryptic COPY
# error. For a local build, stamp your checkout first (gitignored):
#   printf '%s\n' "$(git rev-parse HEAD)" > .build_commit_sha && docker build -t api-service .
RUN test -f /app/.build_commit_sha || { echo "docker build: missing .build_commit_sha. For a local build run: printf '%s\n' \"\$(git rev-parse HEAD)\" > .build_commit_sha" >&2; exit 1; }

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
