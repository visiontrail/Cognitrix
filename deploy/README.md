# Cognitrix 部署说明（运维）

## TL;DR

```bash
git clone -b feat/agent-canvas-generation http://gitlab.yhroot.com/nr/cognitrix.git
cd cognitrix
PUBLIC_URL=http://<对外地址>:3000 bash scripts/deploy.sh
```

> **注意分支**：当前交付分支是 `feat/agent-canvas-generation`，不是 `master`。
> GitLab 上的 `master` 只有一个初始化 README，克隆时必须显式带 `-b`，
> 否则拿到的是空壳。管理后台 `/admin` 也只在该分支上。

一条命令完成：生成随机密钥与超管账号 → 构建镜像 → 启动 → 等健康检查 →
打印访问地址和登录口令。**不需要事先准备任何配置文件，也不需要模型 API Key。**

模型 Key、联网检索、Agent 参数等一律登录后在管理后台 `/admin` 配置，
保存即生效、不用重启、不用再登服务器。

---

## 环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | Linux x86_64（amd64）|
| Docker | 20.10+ |
| Docker Compose | v2（`docker compose`）或 v1（`docker-compose`）|
| 内存 | ≥ 4 GB，构建期建议 ≥ 6 GB |
| 磁盘 | ≥ 20 GB（后端镜像含约 250 MB 的 Agent CLI 二进制）|
| 出网 | 构建期需要能访问 pip 与 npm 源；运行期需要能访问模型服务地址 |

**架构必须匹配**：后端依赖的 wheel 自带原生二进制。若在 arm64 机器上构建、
部署到 amd64（或反之），容器会起不来。跨架构构建请加 `--platform linux/amd64`。

**只能单实例**：数据层是 DuckDB + SQLite 本地文件，靠文件锁保证一致性。
不要多副本、不要放进 k8s Deployment 扩副本，否则会静默损坏数据。
需要高可用请先联系开发。

---

## 部署

### 首次部署

```bash
PUBLIC_URL=http://10.20.30.40:3000 bash scripts/deploy.sh
```

`PUBLIC_URL` 是**浏览器实际访问的地址**。不传则按本机主 IP 推断；
走域名或反向代理时必须显式传入，否则「发布公开链接」功能生成的
分享地址对外打不开。

脚本结束时会打印：

```
  访问地址      http://10.20.30.40:3000
  管理后台      http://10.20.30.40:3000/admin
  首次登录账号  admin@cognitrix.local
  首次登录口令  Cg7xK2mQ...        <- 只出现这一次
```

口令同时写在服务器的 `.env` 里（权限 600）。**首次登录后请立即改密。**

### 升级 / 重启

```bash
git pull
bash scripts/deploy.sh
```

重复执行是安全的：已有 `.env` 不会被覆盖，密钥和口令不会重新生成，
数据卷不会被删除。脚本只会补齐新版本新增的配置项。

### 可选参数

| 变量 | 说明 |
|---|---|
| `PUBLIC_URL` | 对外访问地址，强烈建议显式指定 |
| `WEB_PORT` / `API_PORT` | 宿主机映射端口，默认 3000 / 8000 |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | 首启超管账号，默认 `admin@cognitrix.local` + 随机口令 |
| `PIP_INDEX_URL` / `PIP_TRUSTED_HOST` | 内网私有 pip 源 |
| `NPM_REGISTRY` | 内网私有 npm 源，默认 `https://registry.npmmirror.com` |
| `NPM_HTTP_PROXY` / `NPM_HTTPS_PROXY` | 构建期代理 |
| `SKIP_BUILD=1` | 跳过构建，仅重启现有镜像 |
| `HEALTH_TIMEOUT` | 健康检查等待秒数，默认 600 |

内网无外网出口的典型用法：

```bash
PUBLIC_URL=http://10.20.30.40:3000 \
PIP_INDEX_URL=https://mirrors.example.com/pypi/simple \
PIP_TRUSTED_HOST=mirrors.example.com \
NPM_REGISTRY=https://mirrors.example.com/npm/ \
bash scripts/deploy.sh
```

---

## 部署后：在管理后台完成配置

登录 → 右上角进入 `/admin`（仅超级管理员可见）：

1. **模型设置** — 填模型服务地址、API Key、模型名，点连通性测试。
   保存后立即生效。**配置之前所有对话都会失败，这是预期行为。**
2. **环境配置** — 后端全部配置项都在这里，含联网检索开关（需搜索服务 Key）、
   Agent 步数与超时、画布模式等。标了「需重启」的项改完要执行
   `bash scripts/deploy.sh`，其余立即生效。
3. **用户管理** — 邀请成员、分配角色、停用账号。
4. **使用指标** — 调用量、延迟、Token 消耗。

---

## 需要登服务器的三类改动

其余一律在后台完成。改完 `.env` 后重跑 `bash scripts/deploy.sh` 生效。

1. 换访问域名或端口：`APP_URL` / `NEXTAUTH_URL` / `PUBLIC_BASE_URL` / `WEB_PORT`
2. 轮换 `AUTH_SECRET` / `NEXTAUTH_SECRET`（会让所有人退出登录）
3. 代码升级后重新构建镜像

---

## 运维命令

```bash
docker compose ps                      # 状态
docker logs -f cognitrix-api           # 后端日志
docker logs -f cognitrix-web           # 前端日志
bash scripts/deploy.sh                 # 重启（含重新构建）
SKIP_BUILD=1 bash scripts/deploy.sh    # 重启（不重新构建）
bash scripts/docker_down.sh            # 停止（保留数据）
```

### 数据与备份

全部业务数据在一个 Docker 具名卷里：`cognitrix_cognitrix_upload_data`
（上传的文件、DuckDB、SQLite 状态库、审计日志）。

备份：

```bash
docker run --rm \
  -v cognitrix_cognitrix_upload_data:/data:ro \
  -v "$(pwd)":/backup \
  alpine:3.20 tar czf /backup/cognitrix-$(date +%F).tar.gz -C /data .
```

SQLite 启用了 WAL：`.sqlite3-wal` / `.sqlite3-shm` 是数据库的一部分，
必须与 `.sqlite3` 一起备份或一起删除。上面的整卷打包已经覆盖。

**不要**手工删除该卷，`docker compose down -v` 也会删掉它。

---

## 安全须知

- `.env` 含签名密钥与超管口令，权限 600，**不要提交进 Git**。
- 对外只需暴露前端端口（默认 3000）。浏览器全程走同源代理 `/api/backend`，
  后端 8000 不需要对公网开放，建议用防火墙限制在内网。
- `AUTH_REGISTRATION_ENABLED` 默认开启自助注册：任何能访问该地址的人都能建号。
  非内网部署请在后台「环境配置」里关掉。
- Token 默认有效期 30 天且系统没有吊销机制。凭据泄露时唯一的全量失效手段是
  更换 `AUTH_SECRET` 并重跑部署脚本。
- 从 `APP_ENV=production` 起，空的或已进入代码仓库的 `AUTH_SECRET` 会被拒绝启动 —
  这是刻意的，避免用一把公开的钥匙签发 JWT。

---

## GitLab CI 参考

仓库里**没有**预置 `.gitlab-ci.yml`，避免与贵方现有流水线规范冲突。
以下骨架供参考，需在 Runner 所在机器上直接部署（Runner 需能访问 Docker）：

```yaml
stages: [deploy]

variables:
  # 子模块指向 GitHub 且用 SSH 协议，Runner 上没有对应密钥。
  # 构建不需要子模块，保持 none。
  GIT_SUBMODULE_STRATEGY: none

deploy:
  stage: deploy
  tags: [<你的-runner-tag>]
  when: manual                 # 首次建议手动触发，稳定后再改自动
  only: [feat/agent-canvas-generation]   # 当前交付分支，不是 master
  script:
    - PUBLIC_URL="$DEPLOY_PUBLIC_URL" bash scripts/deploy.sh
```

要点：

- **`only` 必须写当前交付分支**。`master` 上没有代码，也没有管理后台。
  等主干合并后再改回 `master`。

- **`GIT_SUBMODULE_STRATEGY` 必须是 `none`**（默认值即是）。设成 `recursive`
  会因为 `.gitmodules` 里的 GitHub SSH 地址而拉取失败，而构建根本不需要子模块。
- 首次部署产生的超管口令会出现在 Job 日志里。若流水线日志对全员可见，
  建议改为在 CI 变量里预设 `ADMIN_PASSWORD`，并把该变量设为 masked。
- 服务器上的 `.env` 是有状态的：Runner 每次都在同一台机器同一目录部署时才成立。
  如果 Runner 用的是全新工作目录，每次都会生成新密钥、且**超管账号只在第一次
  创建**（数据库里已有账号后 `AUTH_BOOTSTRAP_*` 不再建号）。这种情况请把
  `.env` 固化到服务器上的固定路径，或在 CI 变量里锁定
  `ADMIN_PASSWORD` / `AUTH_SECRET` / `NEXTAUTH_SECRET`。

---

## 排障

| 现象 | 原因与处理 |
|---|---|
| 对话一直失败 / 报模型错误 | 模型 API Key 没配。`/admin` →「模型设置」填写并测试连通性 |
| 后端启动即退出，日志提示 `AUTH_SECRET` | `.env` 里密钥为空或是仓库里的公开值。重跑 `bash scripts/deploy.sh` 自动轮换 |
| 构建卡在 pip / npm | 内网无法访问默认源。用 `PIP_INDEX_URL` / `NPM_REGISTRY` 指向私有源 |
| 分享链接打不开 | `PUBLIC_URL` 没传对。改 `.env` 的 `APP_URL` / `PUBLIC_BASE_URL` 后重跑脚本 |
| 忘记超管口令 | 服务器上 `grep AUTH_BOOTSTRAP_ADMIN_PASSWORD .env`；若已改过密则需在库中重置 |
| 健康检查超时 | 看 `docker logs cognitrix-api`。首次构建慢可调大 `HEALTH_TIMEOUT` |
