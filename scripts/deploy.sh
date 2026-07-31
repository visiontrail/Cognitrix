#!/usr/bin/env bash
# ==============================================================================
# Cognitrix 一键部署脚本
#
#   bash scripts/deploy.sh
#
# 首次运行会自动生成 .env（随机密钥 + 随机超管口令），构建并启动 Docker 栈，
# 等待健康检查通过，最后打印访问地址与登录凭据。
# 模型 API Key、联网检索、Agent 开关等一律不在这里配置 —— 登录后在
# 管理后台 /admin 的「模型设置 / 环境配置」里填即可，改完立即生效。
#
# 重复运行 = 升级重启，已有 .env 与数据卷都不会被覆盖或删除。
#
# 可选环境变量:
#   PUBLIC_URL      对外访问地址，例如 http://10.20.30.40:3000 或 https://bi.example.com
#                   不传则按本机主 IP 自动推断。走反向代理时务必显式传入。
#   WEB_PORT        宿主机映射的前端端口，默认 3000
#   API_PORT        宿主机映射的后端端口，默认 8000（建议只在内网暴露）
#   ADMIN_EMAIL     首启超管邮箱，默认 admin@cognitrix.local
#   ADMIN_PASSWORD  首启超管口令，默认随机生成并打印
#   PIP_INDEX_URL   后端镜像构建期的 pip 源，内网环境建议指向私有源
#   NPM_REGISTRY    前端镜像构建期的 npm 源，默认 https://registry.npmmirror.com
#   SKIP_BUILD=1    跳过镜像构建，仅重启现有镜像
#   HEALTH_TIMEOUT  健康检查等待秒数，默认 600（首次构建较慢）
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Reuse compose() (which strips host env that shadows .env) and require_docker().
# ensure_env_file() is deliberately not used: it only asserts that a .env exists
# and points here. Creating one is this script's job.
source "${SCRIPT_DIR}/lib/docker.sh"

WEB_PORT="${WEB_PORT:-3000}"
API_PORT="${API_PORT:-8000}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@cognitrix.local}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-600}"

# Signing keys that were ever shipped in the template or committed to the repo.
# Anyone with repository read access can forge tokens with these, so a .env
# carrying one is rotated automatically. Keep in sync with
# PUBLIC_PLACEHOLDER_SECRETS in apps/api/config.py.
PUBLIC_SECRETS=(
  "replace-with-a-strong-secret"
  "dd904b50ad26343d430462093f66bedc79ec0be5db9c93422fa424ca0781f5d8"
  "584274b0fa054faee78dc5b4ca3d09a3e692c417ab8e0ce1c94bda9022d6e783"
)

is_public_secret() {
  local candidate="$1" known
  [[ -z "${candidate}" ]] && return 0
  for known in "${PUBLIC_SECRETS[@]}"; do
    [[ "${candidate}" == "${known}" ]] && return 0
  done
  return 1
}

GENERATED_ENV=0
GENERATED_PASSWORD=""

log()  { printf '[deploy] %s\n' "$*"; }
warn() { printf '[deploy] 警告: %s\n' "$*" >&2; }
die()  { printf '[deploy] 失败: %s\n' "$*" >&2; exit 1; }

# ------------------------------------------------------------------------------
# 随机值生成。openssl 不可用时回退到 /dev/urandom，避免依赖单一工具。
# ------------------------------------------------------------------------------
gen_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    LC_ALL=C tr -dc 'a-f0-9' </dev/urandom | head -c 64
  fi
}

# Alphanumeric only: compose does not expand .env values, but keeping the
# charset simple avoids quoting surprises when an operator copies the password
# into a shell, a ticket, or a browser form.
gen_password() {
  local raw
  raw="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20)"
  printf 'Cg%s' "${raw}"
}

detect_public_url() {
  local ip=""
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')" || true
  if [[ -z "${ip}" ]] && command -v ip >/dev/null 2>&1; then
    ip="$(ip route get 1.1.1.1 2>/dev/null \
      | awk '{for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit }}')" || true
  fi
  [[ -z "${ip}" ]] && ip="127.0.0.1"
  printf 'http://%s:%s' "${ip}" "${WEB_PORT}"
}

env_has_key() {
  [[ -f "${ENV_FILE}" ]] || return 1
  grep -qE "^[[:space:]]*$1=" "${ENV_FILE}"
}

env_read_key() {
  [[ -f "${ENV_FILE}" ]] || return 0
  awk -F= -v key="$1" '
    $0 !~ /^[[:space:]]*#/ && $1 == key { sub(/^[^=]*=/, ""); print; exit }
  ' "${ENV_FILE}"
}

# Append a key only when absent, so re-running after an upgrade backfills new
# settings without touching anything the operator has already tuned.
env_backfill() {
  local key="$1" value="$2"
  if ! env_has_key "${key}"; then
    printf '%s=%s\n' "${key}" "${value}" >>"${ENV_FILE}"
    log "补齐缺失配置项 ${key}"
  fi
}

env_replace_key() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp "${PROJECT_ROOT}/.env.tmp.XXXXXX")"
  awk -F= -v key="${key}" -v value="${value}" '
    $0 !~ /^[[:space:]]*#/ && $1 == key { print key "=" value; next }
    { print }
  ' "${ENV_FILE}" >"${tmp}"
  cat "${tmp}" >"${ENV_FILE}"
  rm -f "${tmp}"
}

write_new_env() {
  local public_url="$1" admin_password="$2"
  local auth_secret nextauth_secret previous_umask
  auth_secret="$(gen_hex)"
  nextauth_secret="$(gen_hex)"

  # Restrict the file from the moment it is created: it holds the signing keys
  # and the bootstrap password, and chmod alone would leave a readable window.
  previous_umask="$(umask)"
  umask 077
  cat >"${ENV_FILE}" <<EOF
# ==============================================================================
# 由 scripts/deploy.sh 于 $(date '+%Y-%m-%d %H:%M:%S') 自动生成。
# 密钥为本机随机值，请勿提交到代码仓库。
#
# 模型 API Key、联网检索、Agent 画布等运行时开关不在此文件维护，
# 登录后在管理后台 /admin 修改即可，绝大多数配置改完立即生效、无需重启。
# ==============================================================================

APP_NAME=Cognitrix
APP_ENV=production
LOG_LEVEL=INFO

# ---- 对外访问地址 -------------------------------------------------------------
# 换域名 / 上反向代理后，改这四项再重新执行 scripts/deploy.sh 即可。
WEB_PORT=${WEB_PORT}
API_PORT=${API_PORT}
APP_URL=${public_url}
NEXTAUTH_URL=${public_url}
PUBLIC_BASE_URL=${public_url}
CORS_ALLOW_ORIGINS=${public_url},http://127.0.0.1:${WEB_PORT},http://localhost:${WEB_PORT}
API_BASE_URL=http://api:8000

# ---- 存储（容器内绝对路径，compose 亦有硬编码兜底）-----------------------------
DATABASE_URL=sqlite:////app/data/uploads/state/ai_views.sqlite3
UPLOAD_DIR=/app/data/uploads
SQLITE_BUSY_TIMEOUT_MS=15000

# ---- 鉴权密钥（随机生成，泄露后重新执行部署脚本无法轮换，需手工改这两行）-------
AUTH_SECRET=${auth_secret}
NEXTAUTH_SECRET=${nextauth_secret}
USER_ACCOUNTS_ENABLED=true
# 开放自助注册意味着任何能访问该地址的人都能建号；内网之外请在后台关闭。
AUTH_REGISTRATION_ENABLED=true
PASSWORD_MIN_LENGTH=8
ACCESS_TOKEN_TTL_MIN=43200
INVITE_LINK_TTL_DAYS=14
LEGACY_SERVICE_LOGIN_ENABLED=false

# ---- 首启超管账号 -------------------------------------------------------------
# 仅在数据库里还没有任何密码账号时创建；首次登录后请立即改密。
AUTH_BOOTSTRAP_ADMIN_EMAIL=${ADMIN_EMAIL}
AUTH_BOOTSTRAP_ADMIN_PASSWORD=${admin_password}
AUTH_BOOTSTRAP_SUPERADMIN_EMAIL=${ADMIN_EMAIL}

# ---- 模型供应商：留空，登录后在 /admin →「模型设置」里填 ----------------------
MODEL_PROVIDER_URL=https://api.deepseek.com
AI_API_KEY=
AI_MODEL=deepseek-chat
AI_TIMEOUT_SECONDS=120
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_AUTH_TOKEN=
ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-chat
API_TIMEOUT_MS=600000

# ---- Agent 运行时 -------------------------------------------------------------
CLAUDE_AGENT_SDK_ENABLED=true
AGENTIC_INGESTION_ENABLED=true
LEGACY_DATASET_UPLOAD_ENABLED=true
AGENT_MAX_TOOL_STEPS=20
AGENT_MAX_SQL_ROWS=2000
AGENT_MAX_SQL_SCAN_ROWS=10000
AGENT_TIMEOUT_SECONDS=240
INGESTION_PLAN_TIMEOUT_SECONDS=600
AGENT_CANVAS_MODE_ENABLED=true
AGENT_MODE_MAX_STEPS=40
AGENT_MODE_OUTLINE_MAX_STEPS=16
AGENT_MODE_TIMEOUT_SECONDS=600
AGENT_MODE_MAX_CHARTS=12
MULTI_CHART_GENERATION_ENABLED=true
AGENT_MAX_MULTI_CHARTS=8
MULTI_CHART_CONFIRMATION_TTL_SECONDS=900

# ---- 联网检索：需要搜索服务 Key，默认关闭，可在后台开启 -----------------------
WEB_SEARCH_ENABLED=false
WEB_SEARCH_PROVIDER=bocha
WEB_SEARCH_API_KEY=
WEB_SEARCH_MAX_RESULTS=8
WEB_SEARCH_MAX_CALLS_PER_TURN=5
WEB_FETCH_TIMEOUT_SECONDS=15
WEB_FETCH_MAX_BYTES=2097152
WEB_FETCH_MAX_CHARS=20000

# ---- Agent Skills（需随包提供 xlsx skill zip，默认关闭）-----------------------
AGENT_SKILLS_ENABLED=false
AGENT_SKILLS_DIR=
AGENT_SKILLS_MAX_UPLOAD_MB=25
LEGACY_XLSX_PARSER_ENABLED=true

# ---- 其他 --------------------------------------------------------------------
PUBLIC_ASSISTANT_CACHE_TTL_SECONDS=1800
PUBLIC_ASSISTANT_CACHE_MAX_ENTRIES=10
PUBLIC_ASSISTANT_MAX_QUERY_ROWS=200
ADMIN_USAGE_RETENTION_DAYS=180

# ---- 镜像构建期的软件源（内网可改为私有源）------------------------------------
PIP_INDEX_URL=${PIP_INDEX_URL:-}
PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST:-}
NPM_REGISTRY=${NPM_REGISTRY:-https://registry.npmmirror.com}
NPM_FETCH_RETRIES=5
NPM_FETCH_RETRY_MINTIMEOUT=20000
NPM_FETCH_RETRY_MAXTIMEOUT=120000
NPM_FETCH_TIMEOUT=600000
NPM_HTTP_PROXY=${NPM_HTTP_PROXY:-}
NPM_HTTPS_PROXY=${NPM_HTTPS_PROXY:-}
EOF
  umask "${previous_umask}"
  chmod 600 "${ENV_FILE}"
}

prepare_env() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    local public_url admin_password
    public_url="${PUBLIC_URL:-$(detect_public_url)}"
    admin_password="${ADMIN_PASSWORD:-$(gen_password)}"
    write_new_env "${public_url}" "${admin_password}"
    GENERATED_ENV=1
    GENERATED_PASSWORD="${admin_password}"
    log "已生成 ${ENV_FILE}（权限 600）"
    log "对外访问地址取为 ${public_url}"
    if [[ -z "${PUBLIC_URL:-}" ]]; then
      warn "PUBLIC_URL 未显式指定，已按本机 IP 推断。若通过域名或反向代理访问，"
      warn "请改 .env 里的 APP_URL / NEXTAUTH_URL / PUBLIC_BASE_URL 后重跑本脚本，"
      warn "否则「发布公开链接」生成的地址对外打不开。"
    fi
    return
  fi

  log "检测到已有 ${ENV_FILE}，沿用其中的密钥与账号配置"

  # A .env built by copying the template (or by an older ensure_env_file) can
  # carry a signing key that lives in the repository. Rotate rather than boot
  # with it; APP_ENV=production now refuses such a key outright.
  if is_public_secret "$(env_read_key AUTH_SECRET)"; then
    env_replace_key AUTH_SECRET "$(gen_hex)"
    warn "AUTH_SECRET 为空或是已进入代码仓库的公开值，已替换为随机密钥。"
    warn "现有登录态全部失效，所有人需要重新登录。"
  fi
  if is_public_secret "$(env_read_key NEXTAUTH_SECRET)"; then
    env_replace_key NEXTAUTH_SECRET "$(gen_hex)"
    warn "NEXTAUTH_SECRET 为空或是已进入代码仓库的公开值，已替换为随机密钥。"
  fi

  # A hand-written or template-derived .env can carry an empty bootstrap
  # password. _bootstrap_admin() then returns without creating anything, and
  # since it only ever fires while the users table holds no password account,
  # that first boot burns the single chance to get an account into the system.
  env_backfill AUTH_BOOTSTRAP_ADMIN_EMAIL "${ADMIN_EMAIL}"
  env_backfill AUTH_BOOTSTRAP_SUPERADMIN_EMAIL "${ADMIN_EMAIL}"
  if [[ -z "$(env_read_key AUTH_BOOTSTRAP_ADMIN_PASSWORD)" ]]; then
    local new_password
    new_password="${ADMIN_PASSWORD:-$(gen_password)}"
    if env_has_key AUTH_BOOTSTRAP_ADMIN_PASSWORD; then
      env_replace_key AUTH_BOOTSTRAP_ADMIN_PASSWORD "${new_password}"
    else
      printf 'AUTH_BOOTSTRAP_ADMIN_PASSWORD=%s\n' "${new_password}" >>"${ENV_FILE}"
    fi
    GENERATED_PASSWORD="${new_password}"
    warn "AUTH_BOOTSTRAP_ADMIN_PASSWORD 为空，已生成随机口令（见文末输出）。"
  fi

  # Upgrade path: backfill keys introduced after this deployment was created.
  env_backfill APP_ENV production
  env_backfill WEB_PORT "${WEB_PORT}"
  env_backfill API_PORT "${API_PORT}"
  env_backfill API_BASE_URL "http://api:8000"
  env_backfill AGENT_CANVAS_MODE_ENABLED true
  env_backfill AGENT_MODE_MAX_STEPS 40
  env_backfill AGENT_MODE_OUTLINE_MAX_STEPS 16
  env_backfill AGENT_MODE_TIMEOUT_SECONDS 600
  env_backfill AGENT_MODE_MAX_CHARTS 12
  env_backfill MULTI_CHART_GENERATION_ENABLED true
  env_backfill AGENT_MAX_MULTI_CHARTS 8
  env_backfill WEB_SEARCH_ENABLED false
  env_backfill WEB_SEARCH_PROVIDER bocha
  env_backfill AGENT_SKILLS_ENABLED false
  env_backfill ADMIN_USAGE_RETENTION_DAYS 180
  env_backfill PIP_INDEX_URL ""
  env_backfill PIP_TRUSTED_HOST ""
  env_backfill NPM_REGISTRY "https://registry.npmmirror.com"
}

wait_healthy() {
  local container="$1" deadline status
  deadline=$(( $(date +%s) + HEALTH_TIMEOUT ))
  log "等待 ${container} 健康检查通过（最长 ${HEALTH_TIMEOUT}s）..."
  while :; do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
      "${container}" 2>/dev/null || true)"
    case "${status}" in
      healthy|running)
        log "${container}: ${status}"
        return 0
        ;;
      exited|dead)
        docker logs --tail 80 "${container}" >&2 || true
        die "${container} 已退出（状态 ${status}），日志见上方"
        ;;
    esac
    if (( $(date +%s) >= deadline )); then
      docker logs --tail 80 "${container}" >&2 || true
      die "${container} 在 ${HEALTH_TIMEOUT}s 内未就绪（当前状态 ${status:-unknown}），日志见上方"
    fi
    sleep 5
  done
}

print_summary() {
  local public_url admin_email
  public_url="$(env_read_key APP_URL)"
  admin_email="$(env_read_key AUTH_BOOTSTRAP_ADMIN_EMAIL)"

  cat <<EOF

================================================================================
部署完成
================================================================================
  访问地址      ${public_url}
  管理后台      ${public_url}/admin
  健康检查      http://127.0.0.1:$(env_read_key API_PORT)/healthz
EOF

  if [[ -n "${GENERATED_PASSWORD}" ]]; then
    cat <<EOF

  登录账号      ${admin_email}
  登录口令      ${GENERATED_PASSWORD}

  ！该口令只在本次输出中出现一次，也保存在服务器的 .env 里（权限 600）。
  ！登录后请立即修改口令。
EOF
    if (( GENERATED_ENV == 0 )); then
      cat <<'EOF'
  ！该口令仅在数据库里还没有任何账号时才会生效。若本次部署之前已经有人建过号，
  ！请用原有账号登录；忘记口令需要开发协助在库中重置。
EOF
    fi
  else
    cat <<EOF

  登录账号      ${admin_email}（口令沿用上次部署，未改动）
EOF
  fi

  cat <<'EOF'

下一步（全部在管理后台完成，无需再登服务器）
--------------------------------------------------------------------------------
  1. 用上面的账号登录 → 右上角进入 /admin
  2. 「模型设置」填入模型服务地址与 API Key，点连通性测试 —— 保存后立即生效，
     不用重启。在此之前所有对话都会失败，这是预期行为。
  3. 「环境配置」按需开启联网检索（需搜索服务 Key）、调整 Agent 步数与超时。
  4. 「用户管理」邀请成员、分配角色。

需要登服务器的只有三类改动（改完重跑 bash scripts/deploy.sh）
  - 换访问域名/端口：APP_URL / NEXTAUTH_URL / PUBLIC_BASE_URL / WEB_PORT
  - 轮换 AUTH_SECRET / NEXTAUTH_SECRET
  - 代码升级后重新构建镜像

常用运维命令
  查看状态    docker compose -f docker-compose.yml ps
  查看日志    docker logs -f cognitrix-api
  重启        bash scripts/deploy.sh
  停止        bash scripts/docker_down.sh
  数据位置    Docker 具名卷 cognitrix_cognitrix_upload_data（上传文件 + 全部数据库）
================================================================================
EOF
}

main() {
  require_docker
  cd "${PROJECT_ROOT}"
  prepare_env

  if [[ "${SKIP_BUILD:-0}" == "1" ]]; then
    log "SKIP_BUILD=1，跳过镜像构建"
    compose up -d --remove-orphans
  else
    log "开始构建并启动（首次构建需要拉取依赖，可能耗时 5-15 分钟）..."
    compose up -d --build --remove-orphans
  fi

  wait_healthy cognitrix-api
  wait_healthy cognitrix-web
  echo
  compose ps
  print_summary
}

main "$@"
