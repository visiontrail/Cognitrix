# 实施任务:add-agent-web-search

## 1. 配置与依赖

- [x] 1.1 `config.py` 的 `Settings` 新增 D6 全部配置项(`WEB_SEARCH_ENABLED`、`WEB_SEARCH_PROVIDER`、`WEB_SEARCH_API_KEY`、`WEB_SEARCH_MAX_RESULTS`、`WEB_SEARCH_MAX_CALLS_PER_TURN`、`WEB_FETCH_TIMEOUT_SECONDS`、`WEB_FETCH_MAX_BYTES`、`WEB_FETCH_MAX_CHARS`),含类型校验与默认值
- [x] 1.2 `apps/api/.env.example` 增补新变量与中文注释;`scripts/checks` 的 env-check 兼容新变量(缺省不报错)
- [x] 1.3 后端依赖清单加入 `trafilatura`,验证 `make bootstrap` 可安装

## 2. web_research 核心模块

- [x] 2.1 新建 `apps/api/web_research.py`:定义 `SearchResult` 数据类与 `SearchProvider` 协议(`search(query, top_k) -> list[SearchResult]`)
- [x] 2.2 实现 `BochaSearchProvider` 与 `TavilySearchProvider`(httpx 调用、错误归一为结构化失败),按 `WEB_SEARCH_PROVIDER` 工厂选择
- [x] 2.3 实现 SSRF 防护函数:URL 规范化、http→https 升级、DNS 解析后校验 IP(私网/环回/链路本地/云元数据网段拒绝)、每跳重定向重校验、上限 3 跳
- [x] 2.4 实现 `fetch_page(url)`:httpx GET(超时、大小上限、并发信号量)+ trafilatura 正文抽取 + `WEB_FETCH_MAX_CHARS` 截断,超限标注
- [x] 2.5 单元测试 `tests/unit/test_web_research.py`:供应商结果归一化、SSRF 各网段拒绝、重定向逃逸拦截、大小/字符截断(HTTP 层用 httpx.MockTransport,不真实出网)

## 3. 工具注册与守卫

- [x] 3.1 `tool_calling.py` 新增 `web_search`、`web_fetch` 工具实现与 schema 定义(描述中写明触发条件),接入 `web_research.py`
- [x] 3.2 `tool_calling.py` 新增 `save_web_research`:`SAFE_IDENTIFIER_RE` 校验、`web_research_` 前缀强制、类型白名单复用、行/列上限、自动追加 `_source_url`/`_source_title`/`_retrieved_at` 溯源列、经 `datasets.py` 写入会话 DuckDB
- [x] 3.3 `agent_runtime.py` 的工具定义 / `_build_sdk_tools` 按 `WEB_SEARCH_ENABLED` 条件注册 3 个新工具(`save_web_research` 标记非只读)
- [x] 3.4 `agent_guardrails.py`:白名单按开关动态包含新工具;新增单轮联网调用计数器,超 `WEB_SEARCH_MAX_CALLS_PER_TURN` 拒绝并返回"停止检索请作答"提示
- [x] 3.5 `audit.py` 接入三类新事件(`web_search`、`web_fetch`、`save_web_research`),仅记录元数据(域名、条数、行数、耗时),不落正文与完整查询词
- [x] 3.6 单元测试:守卫开关行为、单轮限额、`save_web_research` 标识符/命名空间/规模校验(`tests/unit/`、`tests/security/`)

## 4. 提示工程与来源协议

- [x] 4.1 `agent_prompting.py`:`WEB_SEARCH_ENABLED` 时追加检索指引段(触发/禁止条件、`[n]` 编号引用纪律、`sources` 申报、网页内容仅作资料声明)
- [x] 4.2 Agent 最终输出 JSON schema 增加可选 `sources: [{id, title, url}]`,解析容错(缺失/格式错不致整轮失败)
- [x] 4.3 `agent_runtime.py`:`SDKRunContext` 累积本轮联网访问 URL 集合;`final` 组装时实现 D5 兜底逻辑(模型漏报则以实际访问集合去重生成 `sources`)
- [x] 4.4 `chat.py` / `ChatStreamService`:`final` SSE 载荷并入 `sources`,验证旧消费方向后兼容
- [x] 4.5 后端集成测试:mock 供应商跑通"搜索→抓取→落库→final 带 sources"全链(`tests/integration/`)

## 5. 前端来源引用区

- [x] 5.1 `chat-store.ts` 的 `ChatMessage` 增加 `sources` 字段并随会话持久化;SSE 消费侧解析 `final.sources`
- [x] 5.2 新建来源引用区组件:序号 + 标题 + 域名,外链 `target="_blank" rel="noopener noreferrer"`,空来源不渲染;接入助手消息底部
- [x] 5.3 i18n 词条(中英):"来源 / Sources" 等文案
- [x] 5.4 Vitest 单测:有/无 sources 的渲染分支、刷新后持久化渲染、链接安全属性

## 6. 验证与收尾

- [x] 6.1 `tests/evals/` 增加检索行为评估用例:该搜时搜、不该搜时不搜、正文编号与 sources 对应
- [ ] 6.2 手动 smoke(开发环境配真实密钥):提问外部市场数据 → 观察 trace 搜索/抓取行为 → 确认落库 `web_research_*` 表可被 SQL 联查 → 确认回答带可点击来源  _(需真实供应商密钥 + 联网,当前环境无法执行;待开发环境人工验证)_
- [x] 6.3 更新 `CLAUDE.md`(新工具、新配置、新模块说明)与 `.env.example` 核对
- [ ] 6.4 全量门禁 `make test-all` 通过;`WEB_SEARCH_ENABLED=false` 下回归确认存量行为零变化  _(已核实:后端 `pytest`/前端 `vitest`+`next lint` 通过,新增 49 测试全绿;存量 10 处失败与 master 完全一致,均为本地 `apps/api/.env` 泄漏所致的既有失败,与本变更无关。`WEB_SEARCH_ENABLED=false` 回归已由 `test_web_disabled_emits_no_sources` 及 master 对比确认零变化。完整 `make test-all` 的 build+docker-smoke 环节需完整环境,待 CI 执行)_
