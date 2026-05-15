import { getAuthorizationHeader } from "@/lib/auth/session";
import { API_BASE_URL } from "@/lib/api-base";
import { parseSSEStream } from "@/lib/chat/sse";
import type { SSEEvent } from "@/lib/chat/sse";
import type {
  IngestionApprovalResult,
  IngestionBusinessType,
  IngestionCatalogSetupSeed,
  IngestionDryRunSummary,
  IngestionExecuteResult,
  IngestionHumanApproval,
  IngestionPlanResult,
  IngestionProposal,
  IngestionProposalAction,
  IngestionSetupQuestion,
  IngestionTimeGrain,
  IngestionUploadResult,
} from "@/types/ingestion";

const configuredClearance = Number(process.env.NEXT_PUBLIC_DEFAULT_CLEARANCE ?? 1);
const DEFAULT_CLEARANCE = Number.isFinite(configuredClearance)
  ? Math.max(0, Math.trunc(configuredClearance))
  : 1;
const DEFAULT_AUTH_CONTEXT = {
  userId: process.env.NEXT_PUBLIC_DEFAULT_USER_ID ?? "demo-user",
  projectId: process.env.NEXT_PUBLIC_DEFAULT_PROJECT_ID ?? "demo-project",
  role: process.env.NEXT_PUBLIC_DEFAULT_ROLE ?? "hr",
  department: process.env.NEXT_PUBLIC_DEFAULT_DEPARTMENT ?? "HR",
  clearance: DEFAULT_CLEARANCE,
};

type IngestionApiErrorShape = {
  code?: string;
  message: string;
  status: number;
};

export class IngestionApiError extends Error {
  code?: string;
  status: number;

  constructor(shape: IngestionApiErrorShape) {
    super(shape.message);
    this.name = "IngestionApiError";
    this.code = shape.code;
    this.status = shape.status;
  }
}

export async function createIngestionUpload(input: {
  workspaceId: string;
  file: File;
  signal?: AbortSignal;
}): Promise<IngestionUploadResult> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const body = new FormData();
  body.set("workspace_id", input.workspaceId);
  body.append("files", input.file);

  const response = await fetch(`${API_BASE_URL}/ingestion/uploads`, {
    method: "POST",
    headers,
    body,
    signal: input.signal,
  });

  const payload = await readPayload(response);
  if (!response.ok) {
    throw toApiError(payload, response.status, "ingestion_upload_failed");
  }

  const record = asRecord(payload);
  const fileSummary = asRecord(record.file_summary);
  return {
    uploadId: asString(record.upload_id),
    jobId: asString(record.job_id),
    workspaceId: asString(record.workspace_id),
    status: "uploaded",
    fileSummary: {
      fileName: asString(fileSummary.file_name),
      sizeBytes: asNumber(fileSummary.size_bytes),
      fileHash: asString(fileSummary.file_hash),
      storagePath: asString(fileSummary.storage_path),
    },
    sheetSummary: asRecord(record.sheet_summary),
    columnSummary: asRecord(record.column_summary),
    samplePreview: asRecordList(record.sample_preview),
  };
}

export async function createIngestionPlan(input: {
  workspaceId: string;
  jobId: string;
  conversationId?: string;
  message?: string;
}): Promise<IngestionPlanResult> {
  return mapPlanLikePayload(
    await postJson("/ingestion/plan", {
      workspace_id: input.workspaceId,
      job_id: input.jobId,
      conversation_id: input.conversationId,
      message: input.message,
    }, "ingestion_plan_failed")
  );
}

export async function confirmIngestionSetup(input: {
  workspaceId: string;
  jobId: string;
  conversationId?: string;
  message?: string;
  setup: IngestionCatalogSetupSeed;
}): Promise<IngestionPlanResult> {
  return mapPlanLikePayload(
    await postJson(
      "/ingestion/setup/confirm",
      {
        workspace_id: input.workspaceId,
        job_id: input.jobId,
        conversation_id: input.conversationId,
        message: input.message,
        setup: toApiSetupSeed(input.setup),
      },
      "ingestion_setup_confirm_failed"
    )
  );
}

export async function approveIngestionProposal(input: {
  workspaceId: string;
  jobId: string;
  proposalId: string;
  approvedAction: IngestionProposalAction;
  signal?: AbortSignal;
  userOverrides?: {
    targetTable?: string;
    timeGrain?: IngestionTimeGrain;
  };
}): Promise<IngestionApprovalResult> {
  const payload = asRecord(
    await postJson(
      "/ingestion/approve",
      {
        workspace_id: input.workspaceId,
        job_id: input.jobId,
        proposal_id: input.proposalId,
        approved_action: input.approvedAction,
        user_overrides: input.userOverrides
          ? {
              target_table: input.userOverrides.targetTable,
              time_grain: input.userOverrides.timeGrain,
            }
          : undefined,
      },
      "ingestion_approve_failed",
      input.signal
    )
  );

  const status = asString(payload.status);
  if (status === "cancelled") {
    return {
      status: "cancelled",
      workspaceId: asString(payload.workspace_id),
      jobId: asString(payload.job_id),
      proposalId: asString(payload.proposal_id),
      approvedAction: "cancel",
    };
  }

  return {
    status: "approved",
    workspaceId: asString(payload.workspace_id),
    jobId: asString(payload.job_id),
    proposalId: asString(payload.proposal_id),
    approvedAction: asWriteMode(payload.approved_action),
    targetTable: asString(payload.target_table),
    timeGrain: asTimeGrain(payload.time_grain),
    dryRunSummary: mapDryRunSummary(payload.dry_run_summary),
  };
}

export async function executeIngestionProposal(input: {
  workspaceId: string;
  jobId: string;
  proposalId: string;
}): Promise<IngestionExecuteResult> {
  const payload = asRecord(
    await postJson(
      "/ingestion/execute",
      {
        workspace_id: input.workspaceId,
        job_id: input.jobId,
        proposal_id: input.proposalId,
      },
      "ingestion_execute_failed"
    )
  );

  const receipt = asRecord(payload.receipt);
  return {
    status: "succeeded",
    workspaceId: asString(payload.workspace_id),
    jobId: asString(payload.job_id),
    proposalId: asString(payload.proposal_id),
    executionId: asString(payload.execution_id),
    receipt: {
      success: Boolean(receipt.success),
      workspaceId: asString(receipt.workspace_id),
      jobId: asString(receipt.job_id),
      targetTable: asString(receipt.target_table),
      executionMode: asString(receipt.execution_mode) as IngestionProposalAction,
      insertedRows: asNumber(receipt.inserted_rows),
      updatedRows: asNumber(receipt.updated_rows),
      affectedRows: asNumber(receipt.affected_rows),
      rowsAfter: asNumber(receipt.rows_after),
      duckdbPath: asString(receipt.duckdb_path),
      finishedAt: asString(receipt.finished_at),
    },
  };
}

export type IngestionSSEEvent = SSEEvent & {
  event: "planning" | "tool_use" | "tool_result" | "decision" | "error";
};

export async function* streamIngestionPlan(input: {
  workspaceId: string;
  jobId: string;
  conversationId?: string;
  message?: string;
  signal?: AbortSignal;
}): AsyncGenerator<IngestionSSEEvent> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const response = await fetch(`${API_BASE_URL}/ingestion/plan/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({
      workspace_id: input.workspaceId,
      job_id: input.jobId,
      conversation_id: input.conversationId,
      message: input.message,
    }),
    signal: input.signal,
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => null);
    throw toApiError(payload, response.status, "ingestion_plan_stream_failed");
  }
  for await (const event of parseSSEStream(response.body)) {
    yield event as IngestionSSEEvent;
  }
}

export async function* streamIngestionSetupConfirm(input: {
  workspaceId: string;
  jobId: string;
  conversationId?: string;
  message?: string;
  setup: IngestionCatalogSetupSeed;
  signal?: AbortSignal;
}): AsyncGenerator<IngestionSSEEvent> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const response = await fetch(`${API_BASE_URL}/ingestion/setup/confirm/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({
      workspace_id: input.workspaceId,
      job_id: input.jobId,
      conversation_id: input.conversationId,
      message: input.message,
      setup: toApiSetupSeed(input.setup),
    }),
    signal: input.signal,
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => null);
    throw toApiError(payload, response.status, "ingestion_setup_stream_failed");
  }
  for await (const event of parseSSEStream(response.body)) {
    yield event as IngestionSSEEvent;
  }
}

export async function* streamIngestionExecute(input: {
  workspaceId: string;
  jobId: string;
  proposalId: string;
  signal?: AbortSignal;
}): AsyncGenerator<IngestionSSEEvent> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const response = await fetch(`${API_BASE_URL}/ingestion/execute/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({
      workspace_id: input.workspaceId,
      job_id: input.jobId,
      proposal_id: input.proposalId,
    }),
    signal: input.signal,
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => null);
    throw toApiError(payload, response.status, "ingestion_execute_stream_failed");
  }
  for await (const event of parseSSEStream(response.body)) {
    yield event as IngestionSSEEvent;
  }
}

async function postJson(
  path: string,
  body: Record<string, unknown>,
  fallbackCode: string,
  signal?: AbortSignal
): Promise<unknown> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: JSON.stringify(body),
    signal,
  });

  const payload = await readPayload(response);
  if (!response.ok) {
    throw toApiError(payload, response.status, fallbackCode);
  }
  return payload;
}

async function readPayload(response: Response): Promise<unknown> {
  return response.json().catch(() => null);
}

function toApiError(payload: unknown, status: number, fallbackCode: string): IngestionApiError {
  const record = asRecord(payload);
  const detail = asRecord(record.detail);
  const code = asOptionalString(detail.code) ?? asOptionalString(record.code) ?? fallbackCode;
  const message =
    asOptionalString(detail.message) ??
    asOptionalString(record.message) ??
    `${fallbackCode}_${status}`;

  return new IngestionApiError({
    code,
    message,
    status,
  });
}

export function mapPlanLikePayload(payload: unknown): IngestionPlanResult {
  const record = asRecord(payload);
  const status = asString(record.status);

  if (status === "awaiting_catalog_setup") {
    return {
      status: "awaiting_catalog_setup",
      workspaceId: asString(record.workspace_id),
      jobId: asString(record.job_id),
      agentGuess: {
        businessType: asBusinessType(asRecord(record.agent_guess).business_type),
        confidence: asNumber(asRecord(record.agent_guess).confidence, 0),
      },
      setupQuestions: asSetupQuestions(record.setup_questions),
      suggestedCatalogSeed: fromApiSetupSeed(asRecord(record.suggested_catalog_seed)),
      humanApproval: mapHumanApproval(record.human_approval, "catalog_setup"),
      route: {
        route: asString(asRecord(record.route).route),
        reason: asString(asRecord(record.route).reason),
      },
      toolTrace: asRecordList(record.tool_trace),
    };
  }

  const primaryProposalId = asString(record.proposal_id);
  const primaryProposal = mapProposal(asRecord(record.proposal_json));
  const rawProposals = Array.isArray(record.proposals) ? record.proposals : [];
  let proposalEntries = rawProposals
    .map((entry) => asRecord(entry))
    .map((entry) => {
      const id = asString(entry.proposal_id);
      if (!id) return null;
      return {
        proposalId: id,
        proposal: mapProposal(asRecord(entry.proposal_json)),
      };
    })
    .filter((value): value is { proposalId: string; proposal: IngestionProposal } => value !== null);
  // Backward compat: if the server didn't emit a `proposals` array, build a
  // singleton from the legacy proposal_id / proposal_json pair.
  if (proposalEntries.length === 0 && primaryProposalId) {
    proposalEntries = [{ proposalId: primaryProposalId, proposal: primaryProposal }];
  }

  return {
    status: "awaiting_user_approval",
    workspaceId: asString(record.workspace_id),
    jobId: asString(record.job_id),
    proposalId: primaryProposalId || proposalEntries[0]?.proposalId || "",
    proposal: proposalEntries[0]?.proposal ?? primaryProposal,
    proposals: proposalEntries,
    humanApproval: mapHumanApproval(record.human_approval, "proposal_approval"),
    route: {
      route: asString(asRecord(record.route).route),
      reason: asString(asRecord(record.route).reason),
    },
    toolTrace: asRecordList(record.tool_trace),
    existingTables: asRecord(record.existing_tables),
    setup: record.setup
      ? {
          status: asString(asRecord(record.setup).status),
          catalogEntry: asRecord(asRecord(record.setup).catalog_entry),
        }
      : undefined,
  };
}

function mapHumanApproval(
  payload: unknown,
  fallbackStage: IngestionHumanApproval["stage"]
): IngestionHumanApproval {
  const record = asRecord(payload);
  const stage = normalizeApprovalStage(asOptionalString(record.stage), fallbackStage);
  return {
    required: record.required === undefined ? true : Boolean(record.required),
    mechanism: asOptionalString(record.mechanism) ?? "frontend_approval_card",
    stage,
    question: asOptionalString(record.question) ?? "",
    options: asStringList(record.options),
    recommendedOption: asOptionalString(record.recommended_option) ?? null,
  };
}

function mapProposal(payload: Record<string, unknown>): IngestionProposal {
  return {
    businessType: asBusinessType(payload.business_type),
    confidence: asNumber(payload.confidence, 0),
    recommendedAction: asProposalAction(payload.recommended_action),
    candidateActions: asProposalActionList(payload.candidate_actions),
    targetTable: asOptionalString(payload.target_table) ?? null,
    timeGrain: asTimeGrain(payload.time_grain),
    matchColumns: asStringList(payload.match_columns),
    columnMapping: asStringRecord(payload.column_mapping),
    diffPreview: {
      predictedInsertCount: asNumber(asRecord(payload.diff_preview).predicted_insert_count, 0),
      predictedUpdateCount: asNumber(asRecord(payload.diff_preview).predicted_update_count, 0),
      predictedConflictCount: asNumber(asRecord(payload.diff_preview).predicted_conflict_count, 0),
    },
    risks: asStringList(payload.risks),
    explanation: asString(payload.explanation),
    sqlDraft: asString(payload.sql_draft),
    requiresCatalogSetup: Boolean(payload.requires_catalog_setup),
    createdAt: asString(payload.created_at),
  };
}

function normalizeApprovalStage(
  value: string | undefined,
  fallbackStage: IngestionHumanApproval["stage"]
): IngestionHumanApproval["stage"] {
  if (value === "catalog_setup" || value === "proposal_approval") {
    return value;
  }
  return fallbackStage;
}

function mapDryRunSummary(payload: unknown): IngestionDryRunSummary {
  const record = asRecord(payload);
  return {
    approvedAction: asProposalAction(record.approved_action),
    targetTable: asString(record.target_table),
    timeGrain: asTimeGrain(record.time_grain),
    predictedInsertCount: asNumber(record.predicted_insert_count),
    predictedUpdateCount: asNumber(record.predicted_update_count),
    predictedConflictCount: asNumber(record.predicted_conflict_count),
    predictedAffectedRows: asNumber(record.predicted_affected_rows),
    schemaWarnings: asStringList(record.schema_warnings),
    risks: asStringList(record.risks),
  };
}

function toApiSetupSeed(seed: IngestionCatalogSetupSeed): Record<string, unknown> {
  return {
    business_type: seed.businessType,
    table_name: seed.tableName,
    human_label: seed.humanLabel,
    write_mode: seed.writeMode,
    time_grain: seed.timeGrain,
    primary_keys: seed.primaryKeys,
    match_columns: seed.matchColumns,
    is_active_target: seed.isActiveTarget,
    description: seed.description,
  };
}

function fromApiSetupSeed(seed: Record<string, unknown>): IngestionCatalogSetupSeed {
  return {
    businessType: asBusinessType(seed.business_type),
    tableName: asString(seed.table_name),
    humanLabel: asString(seed.human_label),
    writeMode: asWriteMode(seed.write_mode),
    timeGrain: asTimeGrain(seed.time_grain),
    primaryKeys: asStringList(seed.primary_keys),
    matchColumns: asStringList(seed.match_columns),
    isActiveTarget: Boolean(seed.is_active_target),
    description: asString(seed.description),
  };
}

function asSetupQuestions(value: unknown): IngestionSetupQuestion[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => {
    const record = asRecord(item);
    return {
      questionId: asString(record.question_id),
      title: asString(record.title),
      options: asStringList(record.options),
    };
  });
}

function asProposalActionList(value: unknown): IngestionProposalAction[] {
  return asStringList(value).map((item) => asProposalAction(item));
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asOptionalString(value: unknown): string | undefined {
  const normalized = asString(value).trim();
  return normalized ? normalized : undefined;
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asRecordList(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => asRecord(item));
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => String(item)).filter(Boolean);
}

function asStringRecord(value: unknown): Record<string, string> {
  const record = asRecord(value);
  return Object.fromEntries(Object.entries(record).map(([key, item]) => [key, String(item)]));
}

function asBusinessType(value: unknown): IngestionBusinessType {
  const candidate = asString(value);
  if (candidate === "roster" || candidate === "project_progress" || candidate === "attendance") {
    return candidate;
  }
  return "other";
}

function asWriteMode(value: unknown): "update_existing" | "time_partitioned_new_table" | "new_table" {
  const candidate = asString(value);
  if (candidate === "time_partitioned_new_table" || candidate === "new_table") {
    return candidate;
  }
  return "update_existing";
}

function asTimeGrain(value: unknown): IngestionTimeGrain {
  const candidate = asString(value);
  if (candidate === "month" || candidate === "quarter" || candidate === "year") {
    return candidate;
  }
  return "none";
}

function asProposalAction(value: unknown): IngestionProposalAction {
  const candidate = asString(value);
  if (
    candidate === "update_existing" ||
    candidate === "time_partitioned_new_table" ||
    candidate === "new_table" ||
    candidate === "cancel"
  ) {
    return candidate;
  }
  return "cancel";
}
