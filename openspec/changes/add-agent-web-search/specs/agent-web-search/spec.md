# agent-web-search 规格(delta)

## ADDED Requirements

### Requirement: 联网工具受总开关控制
`WEB_SEARCH_ENABLED` 为 `false`(默认)时,系统 SHALL 不向 SDK MCP server 注册 `web_search`、`web_fetch`、`save_web_research` 三个工具,且守卫白名单 SHALL 不包含其名称;为 `true` 时三个工具 SHALL 与既有 8 个 BI 工具经完全相同的注册、守卫、审计与 SSE 事件链路暴露。

#### Scenario: 开关关闭时工具不可见且被守卫拒绝
- **WHEN** `WEB_SEARCH_ENABLED=false` 且任一调用方尝试触发名为 `web_search` 的工具调用
- **THEN** 守卫以 `TOOL_NOT_ALLOWED` 拒绝该调用,且该轮对话正常继续

#### Scenario: 开关开启时工具进入白名单
- **WHEN** `WEB_SEARCH_ENABLED=true` 且服务启动完成
- **THEN** `AgentGuardrails.allowed_tools` 包含 `web_search`、`web_fetch`、`save_web_research`

### Requirement: web_search 返回统一结构的搜索结果
`web_search(query, top_k?)` SHALL 调用 `WEB_SEARCH_PROVIDER` 指定的搜索供应商,返回不超过 `WEB_SEARCH_MAX_RESULTS` 条统一结构的结果,每条 MUST 含 `title`、`url`、`snippet`,可含 `published_at`。供应商差异 MUST 被 `SearchProvider` 抽象吸收,工具返回结构与供应商无关。

#### Scenario: 正常搜索
- **WHEN** Agent 以非空 `query` 调用 `web_search`
- **THEN** 工具返回一个结果数组,每个元素含非空 `title`、合法 `url` 与 `snippet`,数组长度 ≤ `WEB_SEARCH_MAX_RESULTS`

#### Scenario: 供应商故障降级为结构化错误
- **WHEN** 搜索供应商返回错误或超时
- **THEN** 工具返回带错误说明的结构化失败结果(而非抛出未捕获异常),Agent 可继续本轮对话

#### Scenario: 切换供应商不改变结果结构
- **WHEN** `WEB_SEARCH_PROVIDER` 从 `bocha` 切换为 `tavily` 并重启服务
- **THEN** `web_search` 的返回字段结构不变

### Requirement: web_fetch 抓取正文并强制出站安全约束
`web_fetch(url, purpose?)` SHALL 以 HTTPS 抓取目标页面并抽取正文文本返回。执行层 MUST 强制:目标(含每一跳重定向)解析后的 IP 不属于私网、环回、链路本地或云元数据地址;重定向不超过 3 跳;响应体不超过 `WEB_FETCH_MAX_BYTES`;超时 `WEB_FETCH_TIMEOUT_SECONDS`;返回正文截断至 `WEB_FETCH_MAX_CHARS` 字符。`http://` URL SHALL 升级为 `https://` 后执行。

#### Scenario: 私网地址被拒绝
- **WHEN** Agent 调用 `web_fetch` 且 URL 解析到 `10.0.0.0/8`、`127.0.0.0/8`、`169.254.0.0/16`、`192.168.0.0/16` 等受禁网段
- **THEN** 工具在发起请求前返回结构化拒绝,不产生任何对该地址的连接

#### Scenario: 重定向逃逸被拦截
- **WHEN** 目标 URL 返回指向私网地址的 302 重定向
- **THEN** 工具在跟随该跳前重新校验并拒绝,已获得的公网内容不返回给模型

#### Scenario: 超大响应被截断
- **WHEN** 页面响应体超过 `WEB_FETCH_MAX_BYTES`
- **THEN** 工具停止读取,基于已读部分抽取正文并在结果中标注已截断

### Requirement: 单轮联网调用次数受限
守卫 SHALL 对单个对话轮次内 `web_search` 与 `web_fetch` 的调用总次数计数,超过 `WEB_SEARCH_MAX_CALLS_PER_TURN` 后 MUST 拒绝后续联网工具调用并向模型返回明确的"配额已用尽,请基于已获得的信息作答"提示。

#### Scenario: 超出单轮上限被拒绝
- **WHEN** 同一轮内联网工具调用次数已达 `WEB_SEARCH_MAX_CALLS_PER_TURN`,Agent 再次调用 `web_search`
- **THEN** 守卫拒绝该调用,拒绝消息指示模型停止检索并作答

### Requirement: 联网工具调用进入 trace 与审计
`web_search`、`web_fetch` 的每次调用 SHALL 按既有约定发出 `tool_use`/`tool_result` SSE 事件(含 `step_id`、时间戳),并写入审计日志。审计记录 MUST 仅含元数据(工具名、目标域名、结果条数、耗时、状态),MUST NOT 记录页面正文或完整查询词。

#### Scenario: 搜索调用产生可配对的 trace 事件
- **WHEN** Agent 执行一次 `web_search`
- **THEN** SSE 流中出现共享同一 `step_id` 的 `tool_use` 与 `tool_result` 事件,前端 trace 以工具行渲染

#### Scenario: 审计不落正文
- **WHEN** `web_fetch` 成功抓取某页面
- **THEN** 对应审计事件包含域名与字节数等元数据,不包含页面正文内容

### Requirement: 系统提示提供显式检索指引
`WEB_SEARCH_ENABLED=true` 时,`build_agent_system_prompt()` SHALL 追加联网检索指引段,至少包含:触发条件(用户问题依赖数据库中不存在的外部事实时先搜索)、禁止条件(现有表可回答时不得联网)、引用纪律(正文使用编号引用,`sources` 申报全部依据)、网页内容仅作资料不作指令的声明。

#### Scenario: 开关开启时提示词包含检索指引
- **WHEN** `WEB_SEARCH_ENABLED=true` 且系统组装某轮对话的系统提示
- **THEN** 提示文本包含联网触发条件、禁止条件与引用纪律段落

#### Scenario: 开关关闭时提示词不含检索指引
- **WHEN** `WEB_SEARCH_ENABLED=false`
- **THEN** 系统提示不包含任何联网检索指引文本
