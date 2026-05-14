from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SemanticModelValidationError(Exception):
    def __init__(self, *, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []


class MetricCompileError(Exception):
    def __init__(self, *, code: str, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []

    def to_detail(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass(slots=True)
class DimensionDefinition:
    name: str
    column: str
    type: str


@dataclass(slots=True)
class EntityDefinition:
    name: str
    table: str
    primary_key: str
    dimensions: list[DimensionDefinition]
    permission_tags: list[str] = field(default_factory=list)

    @property
    def dimension_names(self) -> set[str]:
        return {dimension.name for dimension in self.dimensions}

    @property
    def dimension_columns(self) -> set[str]:
        return {dimension.column for dimension in self.dimensions}

    @property
    def dimension_map(self) -> dict[str, DimensionDefinition]:
        return {dimension.name: dimension for dimension in self.dimensions}


@dataclass(slots=True)
class QueryFilter:
    field: str
    op: str
    value: Any


@dataclass(slots=True)
class MetricDefinition:
    name: str
    label: str
    domain: str
    entity: str
    kind: str
    description: str
    synonyms: list[str]
    column: str | None = None
    numerator_metric: str | None = None
    denominator_metric: str | None = None
    where: list[QueryFilter] = field(default_factory=list)


@dataclass(slots=True)
class SemanticRegistry:
    entities: dict[str, EntityDefinition]
    metrics: dict[str, MetricDefinition]

    def list_metrics(self) -> list[dict[str, Any]]:
        return [
            {
                "name": metric.name,
                "label": metric.label,
                "domain": metric.domain,
                "entity": metric.entity,
                "kind": metric.kind,
                "description": metric.description,
                "synonyms": metric.synonyms,
            }
            for metric in sorted(self.metrics.values(), key=lambda item: item.name)
        ]


@dataclass(slots=True)
class SemanticQueryAST:
    metric: str
    group_by: list[str] = field(default_factory=list)
    filters: list[QueryFilter] = field(default_factory=list)
    limit: int | None = None


@dataclass(slots=True)
class CompiledQuery:
    metric: str
    sql: str
    explain: dict[str, Any]


class IntentParser:
    """Resolve free-form intent strings to a semantic metric AST.

    The parser deliberately performs no keyword extraction or fuzzy scoring:
    upstream callers (the BI agent) are responsible for picking the metric
    name from `get_metric_catalog` and supplying `group_by` / `filters`
    through structured tool arguments. This parser only handles the legacy
    `/semantic/query` endpoint, where it accepts an exact metric name,
    label, or synonym match. Anything ambiguous is rejected so callers must
    disambiguate rather than rely on rule-based guesswork.
    """

    def __init__(self, registry: SemanticRegistry) -> None:
        self.registry = registry

    def parse(self, intent: str) -> SemanticQueryAST:
        normalized = intent.strip()
        if not normalized:
            raise MetricCompileError(
                code="EMPTY_INTENT",
                message="Intent cannot be empty",
            )

        metric = self._exact_metric_match(normalized)
        return SemanticQueryAST(metric=metric.name, group_by=[], filters=[])

    def _exact_metric_match(self, intent: str) -> MetricDefinition:
        lowered = intent.lower()
        matches: list[MetricDefinition] = []

        for metric in self.registry.metrics.values():
            if metric.name.lower() == lowered:
                return metric
            if metric.label and metric.label.lower() == lowered:
                matches.append(metric)
                continue
            for synonym in metric.synonyms:
                if synonym.strip().lower() == lowered:
                    matches.append(metric)
                    break

        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise MetricCompileError(
                code="INTENT_AMBIGUOUS",
                message=(
                    "Intent matches multiple metrics; pass the canonical metric "
                    "name explicitly via tool arguments."
                ),
                details=sorted({metric.name for metric in matches}),
            )
        raise MetricCompileError(
            code="INTENT_NOT_UNDERSTOOD",
            message=(
                "Unable to map intent to a known metric. Use get_metric_catalog "
                "and supply the exact metric name plus explicit group_by/filters."
            ),
        )


class MetricCompiler:
    def __init__(self, registry: SemanticRegistry) -> None:
        self.registry = registry

    def compile(self, query_ast: SemanticQueryAST, *, table_override: str | None = None) -> CompiledQuery:
        metric = self.registry.metrics.get(query_ast.metric)
        if not metric:
            raise MetricCompileError(
                code="METRIC_NOT_FOUND",
                message=f"Unknown metric: {query_ast.metric}",
            )

        entity = self.registry.entities[metric.entity]
        table_name = table_override or entity.table
        safe_table = _safe_identifier(table_name)

        for dimension in query_ast.group_by:
            if dimension not in entity.dimension_names:
                raise MetricCompileError(
                    code="INVALID_GROUP_BY",
                    message=f"Group by dimension not defined: {dimension}",
                )

        for item in query_ast.filters:
            if item.field not in entity.dimension_names:
                raise MetricCompileError(
                    code="INVALID_FILTER_FIELD",
                    message=f"Filter field is not defined in entity: {item.field}",
                )

        metric_expression = self._metric_expression(metric_name=metric.name, stack=[])

        select_parts: list[str] = []
        group_by_parts: list[str] = []
        for dimension in query_ast.group_by:
            column = entity.dimension_map[dimension].column
            quoted = _quote_identifier(column)
            select_parts.append(quoted)
            group_by_parts.append(quoted)

        select_parts.append(f"{metric_expression} AS metric_value")

        sql = f"SELECT {', '.join(select_parts)} FROM {_quote_identifier(safe_table)}"

        where_sql = self._render_where(filters=query_ast.filters, entity=entity)
        if where_sql:
            sql = f"{sql} WHERE {where_sql}"

        if group_by_parts:
            sql = f"{sql} GROUP BY {', '.join(group_by_parts)} ORDER BY metric_value DESC"

        if query_ast.limit is not None:
            if query_ast.limit <= 0:
                raise MetricCompileError(
                    code="INVALID_LIMIT",
                    message="Limit must be a positive integer",
                )
            sql = f"{sql} LIMIT {query_ast.limit}"

        explain = {
            "metric": metric.name,
            "metric_label": metric.label,
            "metric_kind": metric.kind,
            "metric_source": {
                "entity": metric.entity,
                "column": metric.column,
                "numerator_metric": metric.numerator_metric,
                "denominator_metric": metric.denominator_metric,
            },
            "group_by": query_ast.group_by,
            "filters": [
                {
                    "field": item.field,
                    "op": item.op,
                    "value": item.value,
                }
                for item in query_ast.filters
            ],
            "table": safe_table,
        }

        return CompiledQuery(metric=metric.name, sql=sql, explain=explain)

    def _metric_expression(self, *, metric_name: str, stack: list[str]) -> str:
        metric = self.registry.metrics.get(metric_name)
        if not metric:
            raise MetricCompileError(
                code="METRIC_NOT_FOUND",
                message=f"Unknown metric: {metric_name}",
            )

        if metric_name in stack:
            raise MetricCompileError(
                code="CYCLIC_METRIC",
                message=f"Metric dependency loop detected: {' -> '.join(stack + [metric_name])}",
            )

        stack.append(metric_name)
        try:
            condition = self._render_metric_condition(metric=metric)

            if metric.kind == "count":
                if condition:
                    return f"SUM(CASE WHEN {condition} THEN 1 ELSE 0 END)"
                return "COUNT(*)"

            if metric.kind == "count_distinct":
                column = _quote_identifier(_required_metric_column(metric=metric))
                if condition:
                    return f"COUNT(DISTINCT CASE WHEN {condition} THEN {column} ELSE NULL END)"
                return f"COUNT(DISTINCT {column})"

            if metric.kind == "sum":
                column = _quote_identifier(_required_metric_column(metric=metric))
                if condition:
                    return f"SUM(CASE WHEN {condition} THEN COALESCE({column}, 0) ELSE 0 END)"
                return f"SUM(COALESCE({column}, 0))"

            if metric.kind == "avg":
                column = _quote_identifier(_required_metric_column(metric=metric))
                if condition:
                    return f"AVG(CASE WHEN {condition} THEN {column} ELSE NULL END)"
                return f"AVG({column})"

            if metric.kind == "ratio":
                if not metric.numerator_metric or not metric.denominator_metric:
                    raise MetricCompileError(
                        code="INVALID_RATIO_METRIC",
                        message=f"Ratio metric {metric.name} must define numerator and denominator",
                    )
                numerator = self._metric_expression(metric_name=metric.numerator_metric, stack=stack)
                denominator = self._metric_expression(metric_name=metric.denominator_metric, stack=stack)
                return f"({numerator}) / NULLIF(({denominator}), 0)"

            raise MetricCompileError(
                code="UNSUPPORTED_METRIC_KIND",
                message=f"Unsupported metric kind: {metric.kind}",
            )
        finally:
            stack.pop()

    def _render_metric_condition(self, *, metric: MetricDefinition) -> str | None:
        if not metric.where:
            return None

        entity = self.registry.entities[metric.entity]
        fragments = [self._render_filter(item, entity=entity) for item in metric.where]
        return " AND ".join(fragments)

    def _render_where(self, *, filters: list[QueryFilter], entity: EntityDefinition) -> str:
        if not filters:
            return ""
        return " AND ".join(self._render_filter(item, entity=entity) for item in filters)

    def _render_filter(self, item: QueryFilter, *, entity: EntityDefinition) -> str:
        dimension = entity.dimension_map.get(item.field)
        if not dimension:
            raise MetricCompileError(
                code="INVALID_FILTER_FIELD",
                message=f"Filter field is not defined in entity: {item.field}",
            )

        column = _quote_identifier(dimension.column)
        op = item.op.lower()

        if op == "eq":
            return f"{column} = {_sql_literal(item.value)}"
        if op == "neq":
            return f"{column} <> {_sql_literal(item.value)}"
        if op == "gt":
            return f"{column} > {_sql_literal(item.value)}"
        if op == "gte":
            return f"{column} >= {_sql_literal(item.value)}"
        if op == "lt":
            return f"{column} < {_sql_literal(item.value)}"
        if op == "lte":
            return f"{column} <= {_sql_literal(item.value)}"
        if op == "in":
            if not isinstance(item.value, list) or not item.value:
                raise MetricCompileError(
                    code="INVALID_FILTER_VALUE",
                    message=f"Filter op=in requires non-empty list value for field: {item.field}",
                )
            joined = ", ".join(_sql_literal(value) for value in item.value)
            return f"{column} IN ({joined})"

        raise MetricCompileError(
            code="UNSUPPORTED_FILTER_OP",
            message=f"Unsupported filter operator: {item.op}",
        )


def load_semantic_registry(models_dir: Path | None = None) -> SemanticRegistry:
    target_dir = (models_dir or DEFAULT_MODELS_DIR).resolve()
    if not target_dir.exists():
        raise SemanticModelValidationError(message=f"Semantic model directory not found: {target_dir}")

    entities: dict[str, EntityDefinition] = {}
    metrics: dict[str, MetricDefinition] = {}

    yaml_files = sorted(target_dir.glob("*.yaml")) + sorted(target_dir.glob("*.yml"))
    if not yaml_files:
        raise SemanticModelValidationError(message=f"No semantic YAML files found in: {target_dir}")

    for yaml_file in yaml_files:
        payload = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
        _load_model_payload(
            payload=payload,
            source_file=yaml_file,
            entities=entities,
            metrics=metrics,
        )

    _validate_metric_dependencies(entities=entities, metrics=metrics)
    return SemanticRegistry(entities=entities, metrics=metrics)


@lru_cache(maxsize=4)
def _cached_registry(models_dir: str) -> SemanticRegistry:
    return load_semantic_registry(Path(models_dir))


def get_semantic_registry(models_dir: Path | None = None) -> SemanticRegistry:
    target = str((models_dir or DEFAULT_MODELS_DIR).resolve())
    return _cached_registry(target)


@lru_cache(maxsize=4)
def _cached_compiler(models_dir: str) -> MetricCompiler:
    registry = _cached_registry(models_dir)
    return MetricCompiler(registry=registry)


def get_metric_compiler(models_dir: Path | None = None) -> MetricCompiler:
    target = str((models_dir or DEFAULT_MODELS_DIR).resolve())
    return _cached_compiler(target)


def clear_semantic_cache() -> None:
    _cached_registry.cache_clear()
    _cached_compiler.cache_clear()


def build_overlay_registry(overlay: dict[str, Any], *, entity_name: str = "overlay_entity") -> SemanticRegistry | None:
    """Build a SemanticRegistry from a schema overlay JSON (LLM-inferred).

    Returns None when the overlay lacks enough data to form a valid registry.
    Metrics that reference unknown columns are silently skipped.
    """
    columns_info: dict[str, Any] = overlay.get("columns", {})
    raw_metrics: list[dict[str, Any]] = overlay.get("metrics", [])
    if not columns_info:
        return None

    # Build dimensions from all canonical columns
    dimensions: list[DimensionDefinition] = []
    seen_cols: set[str] = set()
    # Identify primary key candidate: prefer something named *_id or first column
    pk_candidate: str | None = None

    for _orig, info in columns_info.items():
        canonical = str(info.get("canonical", "")).strip()
        if not canonical or not SAFE_IDENTIFIER_RE.match(canonical) or canonical in seen_cols:
            continue
        col_type = str(info.get("type", "string")).strip()
        dimensions.append(DimensionDefinition(name=canonical, column=canonical, type=col_type))
        seen_cols.add(canonical)
        if pk_candidate is None or canonical.endswith("_id"):
            pk_candidate = canonical

    if not dimensions or pk_candidate is None:
        return None

    entity = EntityDefinition(
        name=entity_name,
        table=entity_name,  # will be overridden at compile time via table_override
        primary_key=pk_candidate,
        dimensions=dimensions,
    )
    known_cols = seen_cols

    metrics: dict[str, MetricDefinition] = {}
    for raw in raw_metrics:
        name = str(raw.get("name", "")).strip()
        label = str(raw.get("label", name)).strip()
        kind = str(raw.get("kind", "")).strip()
        column = str(raw.get("column", "")).strip() or None
        description = str(raw.get("description", "")).strip()

        if not name or not kind or not SAFE_IDENTIFIER_RE.match(name):
            continue
        if kind in {"count_distinct", "sum", "avg"} and (not column or column not in known_cols):
            continue
        if name in metrics:
            continue

        metrics[name] = MetricDefinition(
            name=name,
            label=label,
            domain="overlay",
            entity=entity_name,
            kind=kind,
            column=column,
            description=description,
            synonyms=[label] if label != name else [],
        )

    if not metrics:
        return None

    return SemanticRegistry(entities={entity_name: entity}, metrics=metrics)


def merge_registries(base: SemanticRegistry, overlay: SemanticRegistry) -> SemanticRegistry:
    """Return a new registry combining base + overlay (overlay wins on name collisions)."""
    merged_entities = {**base.entities, **overlay.entities}
    merged_metrics = {**base.metrics, **overlay.metrics}
    return SemanticRegistry(entities=merged_entities, metrics=merged_metrics)


def _load_model_payload(
    *,
    payload: dict[str, Any],
    source_file: Path,
    entities: dict[str, EntityDefinition],
    metrics: dict[str, MetricDefinition],
) -> None:
    domain = str(payload.get("domain", "")).strip()
    if not domain:
        raise SemanticModelValidationError(
            message=f"Missing domain in semantic model: {source_file.name}",
        )

    entities_payload = payload.get("entities")
    if not isinstance(entities_payload, dict) or not entities_payload:
        raise SemanticModelValidationError(
            message=f"Model file {source_file.name} must define non-empty entities",
        )

    for entity_name, raw_entity in entities_payload.items():
        if entity_name in entities:
            raise SemanticModelValidationError(
                message=f"Duplicate entity name detected: {entity_name}",
            )
        entities[entity_name] = _parse_entity(entity_name=entity_name, payload=raw_entity)

    metrics_payload = payload.get("metrics")
    if not isinstance(metrics_payload, list) or not metrics_payload:
        raise SemanticModelValidationError(
            message=f"Model file {source_file.name} must define non-empty metrics list",
        )

    for raw_metric in metrics_payload:
        metric = _parse_metric(domain=domain, payload=raw_metric)
        if metric.name in metrics:
            raise SemanticModelValidationError(
                message=f"Duplicate metric name detected: {metric.name}",
            )
        metrics[metric.name] = metric


def _parse_entity(*, entity_name: str, payload: dict[str, Any]) -> EntityDefinition:
    table = str(payload.get("table", "")).strip()
    primary_key = str(payload.get("primary_key", "")).strip()
    raw_dimensions = payload.get("dimensions")
    tags = payload.get("permissions", {}).get("tags", [])

    if not table or not primary_key:
        raise SemanticModelValidationError(
            message=f"Entity {entity_name} must include table and primary_key",
        )

    if not isinstance(raw_dimensions, list) or not raw_dimensions:
        raise SemanticModelValidationError(
            message=f"Entity {entity_name} must include non-empty dimensions",
        )

    dimensions: list[DimensionDefinition] = []
    seen_names: set[str] = set()
    seen_columns: set[str] = set()

    for raw_dimension in raw_dimensions:
        name = str(raw_dimension.get("name", "")).strip()
        column = str(raw_dimension.get("column", name)).strip()
        dim_type = str(raw_dimension.get("type", "string")).strip()

        if not name or not column:
            raise SemanticModelValidationError(
                message=f"Entity {entity_name} has invalid dimension declaration",
            )
        if name in seen_names:
            raise SemanticModelValidationError(
                message=f"Entity {entity_name} has duplicate dimension name: {name}",
            )
        if column in seen_columns:
            raise SemanticModelValidationError(
                message=f"Entity {entity_name} has duplicate dimension column: {column}",
            )

        seen_names.add(name)
        seen_columns.add(column)
        dimensions.append(DimensionDefinition(name=name, column=column, type=dim_type))

    return EntityDefinition(
        name=entity_name,
        table=table,
        primary_key=primary_key,
        dimensions=dimensions,
        permission_tags=[str(tag) for tag in tags],
    )


def _parse_metric(*, domain: str, payload: dict[str, Any]) -> MetricDefinition:
    name = str(payload.get("name", "")).strip()
    label = str(payload.get("label", name)).strip()
    entity = str(payload.get("entity", "")).strip()
    kind = str(payload.get("kind", "")).strip()

    if not name or not entity or not kind:
        raise SemanticModelValidationError(message=f"Invalid metric declaration: {payload}")

    where_payload = payload.get("where", [])
    where_filters: list[QueryFilter] = []
    if where_payload:
        if not isinstance(where_payload, list):
            raise SemanticModelValidationError(
                message=f"Metric {name} has invalid where condition; expected list",
            )
        for item in where_payload:
            where_filters.append(
                QueryFilter(
                    field=str(item.get("field", "")).strip(),
                    op=str(item.get("op", "eq")).strip() or "eq",
                    value=item.get("value"),
                )
            )

    synonyms = [str(item).strip() for item in payload.get("synonyms", []) if str(item).strip()]

    return MetricDefinition(
        name=name,
        label=label,
        domain=domain,
        entity=entity,
        kind=kind,
        column=str(payload.get("column")).strip() if payload.get("column") is not None else None,
        numerator_metric=str(payload.get("numerator_metric")).strip()
        if payload.get("numerator_metric") is not None
        else None,
        denominator_metric=str(payload.get("denominator_metric")).strip()
        if payload.get("denominator_metric") is not None
        else None,
        description=str(payload.get("description", "")).strip(),
        synonyms=synonyms,
        where=where_filters,
    )


def _validate_metric_dependencies(
    *,
    entities: dict[str, EntityDefinition],
    metrics: dict[str, MetricDefinition],
) -> None:
    allowed_kinds = {"count", "count_distinct", "sum", "avg", "ratio"}

    for metric in metrics.values():
        if metric.kind not in allowed_kinds:
            raise SemanticModelValidationError(
                message=f"Metric {metric.name} has unsupported kind: {metric.kind}",
            )

        entity = entities.get(metric.entity)
        if not entity:
            raise SemanticModelValidationError(
                message=f"Metric {metric.name} references unknown entity: {metric.entity}",
            )

        if metric.kind in {"count_distinct", "sum", "avg"}:
            if not metric.column:
                raise SemanticModelValidationError(
                    message=f"Metric {metric.name} requires column for kind={metric.kind}",
                )
            if metric.column not in entity.dimension_columns:
                raise SemanticModelValidationError(
                    message=(
                        f"Metric {metric.name} references undefined column {metric.column} "
                        f"for entity {metric.entity}"
                    ),
                )

        if metric.kind == "ratio":
            if not metric.numerator_metric or not metric.denominator_metric:
                raise SemanticModelValidationError(
                    message=f"Metric {metric.name} requires numerator_metric and denominator_metric",
                )

        for where_filter in metric.where:
            if not where_filter.field:
                raise SemanticModelValidationError(
                    message=f"Metric {metric.name} has empty where field",
                )
            if where_filter.field not in entity.dimension_names:
                raise SemanticModelValidationError(
                    message=(
                        f"Metric {metric.name} uses where field {where_filter.field} "
                        f"that is not defined in entity {metric.entity}"
                    ),
                )

    for metric in metrics.values():
        if metric.kind != "ratio":
            continue
        if metric.numerator_metric not in metrics:
            raise SemanticModelValidationError(
                message=(
                    f"Metric {metric.name} references unknown numerator_metric: "
                    f"{metric.numerator_metric}"
                ),
            )
        if metric.denominator_metric not in metrics:
            raise SemanticModelValidationError(
                message=(
                    f"Metric {metric.name} references unknown denominator_metric: "
                    f"{metric.denominator_metric}"
                ),
            )


def _required_metric_column(*, metric: MetricDefinition) -> str:
    if not metric.column:
        raise MetricCompileError(
            code="MISSING_METRIC_COLUMN",
            message=f"Metric {metric.name} requires a source column",
        )
    return metric.column


def _safe_identifier(name: str) -> str:
    if not SAFE_IDENTIFIER_RE.match(name):
        raise MetricCompileError(
            code="INVALID_IDENTIFIER",
            message=f"Unsafe identifier: {name}",
        )
    return name


def _quote_identifier(identifier: str) -> str:
    safe = _safe_identifier(identifier)
    return f'"{safe}"'


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)

    text = str(value).replace("'", "''")
    return f"'{text}'"
