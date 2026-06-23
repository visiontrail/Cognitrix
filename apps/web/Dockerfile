FROM node:20-alpine AS deps
WORKDIR /app/apps/web
ARG NPM_REGISTRY=https://registry.npmmirror.com
ARG NPM_FETCH_RETRIES=5
ARG NPM_FETCH_RETRY_MINTIMEOUT=20000
ARG NPM_FETCH_RETRY_MAXTIMEOUT=120000
ARG NPM_FETCH_TIMEOUT=600000
ARG NPM_HTTP_PROXY=
ARG NPM_HTTPS_PROXY=
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm config set registry "${NPM_REGISTRY}" \
    && npm config set fetch-retries "${NPM_FETCH_RETRIES}" \
    && npm config set fetch-retry-mintimeout "${NPM_FETCH_RETRY_MINTIMEOUT}" \
    && npm config set fetch-retry-maxtimeout "${NPM_FETCH_RETRY_MAXTIMEOUT}" \
    && npm config set fetch-timeout "${NPM_FETCH_TIMEOUT}" \
    && if [ -n "${NPM_HTTP_PROXY}" ]; then npm config set proxy "${NPM_HTTP_PROXY}"; fi \
    && if [ -n "${NPM_HTTPS_PROXY}" ]; then npm config set https-proxy "${NPM_HTTPS_PROXY}"; fi \
    && npm ci --no-audit --progress=false

FROM deps AS builder
COPY apps/web ./
RUN npm run build \
    && npm prune --omit=dev

FROM node:20-alpine AS runner
WORKDIR /app/apps/web

ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000 \
    API_BASE_URL=http://api:8000

RUN apk add --no-cache curl

COPY --from=builder /app/apps/web ./

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --retries=6 CMD curl -fsS http://127.0.0.1:3000/ >/dev/null || exit 1

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
