from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Reference business_type vocabulary surfaced to the agent in prompts. The
# ingestion agent is free to propose new values; this tuple is advisory only.
BUSINESS_TYPES = ("roster", "project_progress", "attendance", "other")
PROPOSAL_ACTIONS = ("update_existing", "time_partitioned_new_table", "new_table", "cancel")
TIME_GRAINS = ("none", "month", "quarter", "year")
SETUP_WRITE_MODES = ("update_existing", "time_partitioned_new_table", "new_table")


class IngestionJobStatus(str, Enum):
    uploaded = "uploaded"
    planning = "planning"
    awaiting_catalog_setup = "awaiting_catalog_setup"
    awaiting_user_approval = "awaiting_user_approval"
    approved = "approved"
    executing = "executing"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class IngestionHealth(BaseModel):
    status: str = "ok"
    stage: str = "M6"
    message: str


class IngestionPlanRequest(BaseModel):
    workspace_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    conversation_id: str | None = None
    message: str | None = None

    @field_validator("workspace_id", "job_id")
    @classmethod
    def _trim_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value is required")
        return normalized

    @field_validator("conversation_id")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class IngestionCatalogSetupSeed(BaseModel):
    business_type: str = "other"
    table_name: str = Field(min_length=1, max_length=128)
    human_label: str = Field(min_length=1, max_length=120)
    write_mode: Literal["update_existing", "time_partitioned_new_table", "new_table"] = "new_table"
    time_grain: Literal["none", "month", "quarter", "year"] = "none"
    primary_keys: list[str] = Field(default_factory=list)
    match_columns: list[str] = Field(default_factory=list)
    is_active_target: bool = True
    description: str = Field(default="", max_length=1000)

    @field_validator("table_name")
    @classmethod
    def _trim_table_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("table_name is required")
        return normalized

    @field_validator("human_label")
    @classmethod
    def _trim_human_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("human_label is required")
        return normalized

    @field_validator("description")
    @classmethod
    def _trim_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("primary_keys", "match_columns")
    @classmethod
    def _normalize_columns(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            column = item.strip()
            if not column:
                continue
            lowered = column.lower()
            if lowered not in normalized:
                normalized.append(lowered)
        return normalized


class IngestionSetupConfirmRequest(BaseModel):
    workspace_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    conversation_id: str | None = None
    message: str | None = None
    setup: IngestionCatalogSetupSeed

    @field_validator("workspace_id", "job_id")
    @classmethod
    def _trim_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value is required")
        return normalized

    @field_validator("conversation_id", "message")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DiffPreview(BaseModel):
    predicted_insert_count: int = Field(default=0, ge=0)
    predicted_update_count: int = Field(default=0, ge=0)
    predicted_conflict_count: int = Field(default=0, ge=0)


class IngestionAgentGuess(BaseModel):
    business_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(default="", max_length=1000)


class IngestionSetupQuestion(BaseModel):
    question_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    options: list[str] = Field(default_factory=list)


class IngestionProposalPayload(BaseModel):
    business_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: Literal[
        "update_existing",
        "time_partitioned_new_table",
        "new_table",
        "cancel",
    ]
    candidate_actions: list[
        Literal["update_existing", "time_partitioned_new_table", "new_table", "cancel"]
    ] = Field(default_factory=lambda: ["update_existing", "time_partitioned_new_table", "new_table", "cancel"])
    target_table: str | None = None
    time_grain: Literal["none", "month", "quarter", "year"] = "none"
    match_columns: list[str] = Field(default_factory=list)
    column_mapping: dict[str, str] = Field(default_factory=dict)
    diff_preview: DiffPreview
    risks: list[str] = Field(default_factory=list)
    explanation: str = ""
    sql_draft: str = ""
    requires_catalog_setup: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IngestionHumanApprovalRequest(BaseModel):
    required: bool = True
    mechanism: Literal["frontend_approval_card", "catalog_setup_card"]
    stage: Literal["proposal_approval", "catalog_setup"]
    question: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(default_factory=list)
    recommended_option: str | None = Field(default=None, max_length=80)


class IngestionAgentPlanOutput(BaseModel):
    status: Literal["awaiting_catalog_setup", "awaiting_user_approval"]
    agent_guess: IngestionAgentGuess
    setup_questions: list[IngestionSetupQuestion] = Field(default_factory=list)
    suggested_catalog_seed: IngestionCatalogSetupSeed | None = None
    proposal: IngestionProposalPayload | None = None
    human_approval: IngestionHumanApprovalRequest


class IngestionExecutionAgentOutput(BaseModel):
    status: Literal["executed", "blocked"]
    approved_action: Literal["update_existing", "time_partitioned_new_table", "new_table"]
    target_table: str = Field(min_length=1, max_length=128)
    reasoning: str = Field(default="", max_length=2000)
    executed_sql: str = ""
    receipt: dict[str, Any] = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)

    @field_validator("target_table")
    @classmethod
    def _trim_target_table(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("target_table is required")
        return normalized

    @field_validator("executed_sql", "reasoning")
    @classmethod
    def _trim_text(cls, value: str) -> str:
        return value.strip()


class IngestionApprovalOverrides(BaseModel):
    target_table: str | None = Field(default=None, min_length=1, max_length=128)
    time_grain: Literal["none", "month", "quarter", "year"] | None = None

    @field_validator("target_table")
    @classmethod
    def _trim_optional_table(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None


class IngestionApproveRequest(BaseModel):
    workspace_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    approved_action: Literal["update_existing", "time_partitioned_new_table", "new_table", "cancel"]
    user_overrides: IngestionApprovalOverrides | None = None

    @field_validator("workspace_id", "job_id", "proposal_id")
    @classmethod
    def _trim_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value is required")
        return normalized


class IngestionExecuteRequest(BaseModel):
    workspace_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)

    @field_validator("workspace_id", "job_id", "proposal_id")
    @classmethod
    def _trim_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value is required")
        return normalized
