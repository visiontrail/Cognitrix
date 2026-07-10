# answer-source-citations 规格(delta)

## ADDED Requirements

### Requirement: 最终回答的输出协议携带结构化来源
Agent 最终回答的结构化输出 SHALL 支持可选的 `sources` 数组,每个元素 MUST 含 `id`(从 1 起的整数序号)、`title`(非空字符串)、`url`(合法 URL)。本轮未使用任何联网工具时,`sources` SHALL 省略或为空数组。

#### Scenario: 联网回答携带来源
- **WHEN** Agent 在某轮中调用过 `web_search` 或 `web_fetch` 并产出最终回答
- **THEN** 最终输出的 `sources` 数组非空,且每个元素含合法的 `id`、`title`、`url`

#### Scenario: 纯本地数据回答不携带来源
- **WHEN** Agent 仅使用 BI 工具(未触发任何联网工具)完成回答
- **THEN** 最终输出不含来源引用区所需的 `sources` 数据

### Requirement: 运行时以实际访问 URL 兜底来源申报
运行时 SHALL 在轮内累积 `web_search` 结果中被 `web_fetch` 实际访问的 URL 及搜索结果 URL 集合;当模型产出的 `sources` 缺失或为空而本轮确有联网工具调用时,运行时 MUST 以该集合(去重)生成兜底 `sources`。展示给用户的来源集合 MUST NOT 少于本轮实际抓取过的页面集合。

#### Scenario: 模型漏报时兜底
- **WHEN** 本轮 Agent 调用了 `web_fetch` 抓取 2 个页面,但最终输出的 `sources` 为空
- **THEN** `final` 事件中的 `sources` 包含这 2 个页面的 URL 与标题

### Requirement: final SSE 事件透传 sources
`ChatStreamService` SHALL 将本轮解析或兜底后的 `sources` 并入 `final` SSE 事件载荷,字段名为 `sources`,结构与输出协议一致。既有 `final` 消费方在 `sources` 缺失时 MUST 不受影响(向后兼容)。

#### Scenario: final 事件包含 sources 字段
- **WHEN** 一次使用了联网工具的对话轮结束
- **THEN** SSE 流的 `final` 事件 JSON 载荷含非空 `sources` 数组

#### Scenario: 旧客户端兼容
- **WHEN** 一个不认识 `sources` 字段的既有前端消费 `final` 事件
- **THEN** 消息正文与图表渲染行为与本变更之前完全一致

### Requirement: 前端渲染来源引用区并随消息持久化
前端助手消息组件 SHALL 在消息正文(及图表)下方渲染来源引用区:按 `id` 升序列出每个来源的序号、标题与域名,点击在新标签页打开原文(`target="_blank"` 且 `rel="noopener noreferrer"`)。`sources` SHALL 作为 `ChatMessage` 的字段随会话持久化,页面刷新后引用区仍可渲染。引用区文案 SHALL 接入 i18n(中英)。

#### Scenario: 引用区渲染
- **WHEN** 前端收到含 3 个来源的 `final` 事件
- **THEN** 助手消息底部出现含 3 行的来源引用区,每行显示序号、标题与域名,链接可点击且带 `noopener noreferrer`

#### Scenario: 刷新后来源仍在
- **WHEN** 用户在收到带来源的回答后刷新页面并回到该会话
- **THEN** 该消息的来源引用区照常渲染

#### Scenario: 无来源时不渲染引用区
- **WHEN** 某助手消息的 `sources` 缺失或为空
- **THEN** 该消息不渲染来源引用区,无空占位

### Requirement: 正文编号引用与来源列表对应
系统提示 SHALL 要求模型在回答正文中以 `[n]` 形式标注依据某来源的论断,`n` 对应 `sources` 中的 `id`。正文出现的每个编号 MUST 在 `sources` 中存在对应项(反向不要求:允许列出未在正文显式编号的来源)。

#### Scenario: 编号可解析到来源
- **WHEN** 回答正文包含 `[2]` 标注
- **THEN** `sources` 中存在 `id=2` 的条目
