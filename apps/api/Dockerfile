FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Build-time package source. claude-agent-sdk ships a bundled CLI binary, so the
# wheel is a few hundred MB: a private mirror is usually required on an internal
# network where the default PyPI is unreachable or rate limited.
ARG PIP_INDEX_URL=
ARG PIP_TRUSTED_HOST=
ARG PIP_TIMEOUT=120
ARG PIP_RETRIES=5

COPY apps/api/requirements.txt /tmp/requirements.txt
RUN set -eu; \
    pip_args="--no-cache-dir --timeout ${PIP_TIMEOUT} --retries ${PIP_RETRIES}"; \
    if [ -n "${PIP_INDEX_URL}" ]; then pip_args="${pip_args} --index-url ${PIP_INDEX_URL}"; fi; \
    if [ -n "${PIP_TRUSTED_HOST}" ]; then pip_args="${pip_args} --trusted-host ${PIP_TRUSTED_HOST}"; fi; \
    pip install ${pip_args} --upgrade pip \
    && pip install ${pip_args} -r /tmp/requirements.txt

RUN mkdir -p /app/apps /app/data/uploads
COPY apps/__init__.py /app/apps/__init__.py
COPY apps/api /app/apps/api
COPY models /app/models

# Runtime layout the image owns, so an orchestrator only has to supply
# AUTH_SECRET. Declared here rather than as code defaults because UPLOAD_DIR
# resolves a relative path against apps/api/: a manifest that mounts a volume at
# /app/data/uploads but omits the variable would otherwise write outside that
# volume and lose everything on restart. Kept after the dependency layers so
# changing them never invalidates the pip cache; `docker inspect` shows the
# values, and any deployment can override them.
ENV APP_ENV=production \
    UPLOAD_DIR=/app/data/uploads \
    DATABASE_URL=sqlite:////app/data/uploads/state/ai_views.sqlite3

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=6 CMD curl -fsS http://127.0.0.1:8000/healthz >/dev/null || exit 1

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
