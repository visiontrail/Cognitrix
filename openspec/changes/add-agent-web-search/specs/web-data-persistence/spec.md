# web-data-persistence 规格(delta)

## ADDED Requirements

### Requirement: save_web_research 写入命名空间隔离的会话表
`save_web_research(table_name, columns, rows, sources)` SHALL 在当前用户/项目的会话 DuckDB 中创建表并写入数据。实际表名 MUST 为 `web_research_<table_name>`;`table_name` 与全部列名 MUST 通过 `SAFE_IDENTIFIER_RE` 校验;列类型 MUST 通过既有 DuckDB 类型白名单校验。该工具 SHALL 是联网数据进入 DuckDB 的唯一写路径,且 MUST NOT 能写入任何非 `web_research_` 前缀的表。

#### Scenario: 正常落库
- **WHEN** Agent 以合法表名 `ev_sales_2026h1`、合法列定义与 200 行数据调用 `save_web_research`
- **THEN** 会话 DuckDB 中出现表 `web_research_ev_sales_2026h1` 且行数为 200,工具返回实际表名与行数

#### Scenario: 非法标识符被拒绝
- **WHEN** `table_name` 或任一列名包含 `SAFE_IDENTIFIER_RE` 之外的字符(如引号、分号、中划线)
- **THEN** 工具返回结构化校验错误,不执行任何 DDL

#### Scenario: 命名空间逃逸被拒绝
- **WHEN** `table_name` 试图借助前缀拼接指向既有业务表(如传入伪造的完整表名)
- **THEN** 系统仍以 `web_research_` 前缀 + 校验后的标识符生成表名,不可能覆盖或写入前缀之外的表

### Requirement: 落库数据强制携带溯源元数据
`save_web_research` 写入的每一行 SHALL 由系统自动追加溯源列:`_source_url`(该行数据的来源 URL)、`_source_title`(来源标题)、`_retrieved_at`(检索时间戳)。调用方提供的 `sources` 与行的对应关系缺失时,SHALL 以本轮已访问 URL 的集合填充 `_source_url` 并标注为轮级来源。

#### Scenario: 溯源列自动存在
- **WHEN** 任意一次 `save_web_research` 成功执行
- **THEN** 结果表包含 `_source_url`、`_source_title`、`_retrieved_at` 三列且每行非空

#### Scenario: 用户可按来源筛查数据
- **WHEN** 用户对 `web_research_*` 表执行 `SELECT DISTINCT _source_url FROM ...`
- **THEN** 返回该表全部数据来源 URL 列表

### Requirement: 落库规模受限
单次 `save_web_research` 调用 SHALL 拒绝超过行数上限(默认 1 000 行)或列数上限(默认 30 列,不含系统溯源列)的写入,并返回结构化错误说明限额。

#### Scenario: 超行数上限被拒绝
- **WHEN** Agent 尝试一次写入 5 000 行
- **THEN** 工具返回超限错误且不写入任何数据

### Requirement: 落库结果与既有查询工具互通
`save_web_research` 成功后,结果表 SHALL 立即可被同会话的 `list_tables`、`describe_table`、`sample_rows`、`execute_readonly_sql` 访问,并可与已上传数据集联接查询、生成图表。

#### Scenario: 落库后立即可查
- **WHEN** `save_web_research` 在某轮成功创建 `web_research_ev_sales_2026h1`,同轮或后续轮 Agent 调用 `list_tables`
- **THEN** 返回的表清单包含 `web_research_ev_sales_2026h1`

#### Scenario: 可与上传数据联查
- **WHEN** Agent 对 `web_research_*` 表与用户上传的数据表执行含 JOIN 的 `execute_readonly_sql`
- **THEN** 查询按既有只读 SQL 校验规则正常执行并返回结果

### Requirement: 落库行为进入审计
每次 `save_web_research` SHALL 写入审计事件,记录表名、行数、列数、来源域名列表等元数据,MUST NOT 记录行数据内容。

#### Scenario: 落库产生审计事件
- **WHEN** 一次落库成功写入 200 行
- **THEN** 审计日志出现一条含表名与 `row_count=200` 的事件,事件详情不含任何行数据
