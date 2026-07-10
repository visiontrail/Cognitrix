# 提案:为 Agent 添加联网搜索能力(add-agent-web-search)

## Why(为什么)

当前 Cognitrix 的 BI Agent 只能查询用户上传的 Excel 数据,无法回答任何依赖外部信息的问题(行业销量、市场数据、竞品动态等),用户必须先人工找数据、做表、再上传。同时,底层 DeepSeek 网关不支持 Anthropic 服务端 WebSearch 工具,SDK 内置联网能力在本架构下不可用——需要一套自建的、可控的联网搜索工具面,让 Agent 能直接获取网络数据、将结构化结果沉淀到 DuckDB,并像主流 Chat Bot 一样在回答中向用户展示信息来源。

## What Changes(变更内容)

- 新增两个 Agent 工具:`web_search`(调用第三方搜索 API,返回标题/URL/摘要)与 `web_fetch`(抓取指定 URL 正文,带 SSRF 防护),按现有 8 个 BI 工具的模式注册进 `ToolCallingService` 与 SDK MCP server。
- 新增一个落库工具 `save_web_research`:将 Agent 从网络提取的结构化数据(含来源 URL、检索时间等溯源元数据列)写入当前会话的 DuckDB,表名限定在 `web_research_` 前缀命名空间内,标识符经严格校验。
- Agent 最终回答的输出协议扩展 `sources` 字段:凡使用了联网工具的回答,SSE `final` 事件携带来源列表(标题、URL、引用序号);前端在助手消息底部渲染可点击的来源引用区,风格对齐主流 Chat Bot。
- `agent_guardrails.py` 工具白名单扩展上述 3 个工具;联网工具的启用受配置开关控制(默认关闭),搜索 API 供应商与密钥通过环境变量配置。
- 系统提示(`agent_prompting.py`)增加联网检索工作流指引:何时触发搜索、交叉验证、必须标注来源与数据口径。
- 联网工具调用自动进入现有 agent trace(`tool_use`/`tool_result` SSE 事件),无需修改 trace 协议。
- 审计日志新增联网相关事件(搜索、抓取、落库),不记录页面正文,只记录元数据。

## Capabilities(能力)

### New Capabilities(新增能力)

- `agent-web-search`:Agent 联网检索工具面——`web_search`/`web_fetch` 工具的行为契约、搜索供应商抽象、SSRF 与出站安全防护、守卫白名单、配置开关与超时/限流约束。
- `web-data-persistence`:联网数据落库——`save_web_research` 工具将检索提取的结构化数据写入会话 DuckDB 的行为契约,包括表命名空间隔离、溯源元数据列、标识符与规模校验、与既有查询工具的互通(落库后可被 `list_tables`/`execute_readonly_sql` 查询)。
- `answer-source-citations`:回答来源引用——Agent 输出协议中 `sources` 的结构、SSE `final` 事件的载荷扩展、前端来源引用区的渲染与交互、来源随消息持久化的行为。

### Modified Capabilities(修改的既有能力)

(无——`chat-agent-trace` 的既有需求不变,联网工具作为普通工具事件自动纳入 trace;`final` 事件此前无规格约束,其 `sources` 扩展由新能力 `answer-source-citations` 覆盖。)

## Impact(影响范围)

- **后端**:`tool_calling.py`(新增 3 个工具)、`agent_runtime.py`(工具注册与 sources 透传)、`agent_guardrails.py`(白名单与联网参数校验)、`agent_prompting.py`(检索工作流提示)、`config.py`(新增 `WEB_SEARCH_ENABLED`、`WEB_SEARCH_PROVIDER`、`WEB_SEARCH_API_KEY` 等)、`chat.py`(`final` 事件载荷)、`audit.py`(新审计事件)、新模块 `web_research.py`(搜索供应商客户端 + 正文抽取 + SSRF 防护)。
- **前端**:`ChatPanel` 及消息渲染组件(来源引用区)、`chat-store.ts`(消息模型增加 sources 字段)、i18n 词条。
- **依赖**:新增 Python 依赖 `trafilatura`(正文抽取);出站依赖第三方搜索 API(博查/智谱/Tavily 之一,可插拔)。
- **数据**:会话 DuckDB 新增 `web_research_*` 表;SQLite 状态库无 schema 变更。
- **安全面**:新增出站 HTTP 能力,引入 SSRF、提示注入(网页内容不可信)、数据溯源三类新风险,均在设计中给出强制约束。
- **不影响**:现有 8 个 BI 工具、ingestion 管道、RLS/脱敏读取路径、公开发布链路。
