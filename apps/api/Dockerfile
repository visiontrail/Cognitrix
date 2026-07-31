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

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=6 CMD curl -fsS http://127.0.0.1:8000/healthz >/dev/null || exit 1

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
