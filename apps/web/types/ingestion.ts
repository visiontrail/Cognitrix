export type IngestionBusinessType = "roster" | "project_progress" | "attendance" | "other";
export type IngestionWriteMode = "update_existing" | "time_partitioned_new_table" | "new_table";
export type IngestionProposalAction = IngestionWriteMode | "cancel";
export type IngestionTimeGrain = "none" | "month" | "quarter" | "year";

export type IngestionSetupQuestion = {
  questionId: string;
  title: string;
  options: string[];
};

export type IngestionCatalogSetupSeed = {
  businessType: IngestionBusinessType;
  tableName: string;
  humanLabel: string;
  writeMode: IngestionWriteMode;
  timeGrain: IngestionTimeGrain;
  primaryKeys: string[];
  matchColumns: string[];
  isActiveTarget: boolean;
  description: string;
};

export type IngestionUploadSummary = {
  fileName: string;
  sizeBytes: number;
  fileHash: string;
  storagePath: string;
};

export type IngestionUploadResult = {
  uploadId: string;
  jobId: string;
  workspaceId: string;
  status: "uploaded";
  fileSummary: IngestionUploadSummary;
  sheetSummary: Record<string, unknown>;
  columnSummary: Record<string, unknown>;
  samplePreview: Record<string, unknown>[];
};

export type IngestionAgentRoute = {
  route: string;
  reason: string;
};

export type IngestionAgentGuess = {
  businessType: IngestionBusinessType;
  confidence: number;
};

export type IngestionDiffPreview = {
  predictedInsertCount: number;
  predictedUpdateCount: number;
  predictedConflictCount: number;
};

export type IngestionProposal = {
  businessType: IngestionBusinessType;
  confidence: number;
  recommendedAction: IngestionProposalAction;
  candidateActions: IngestionProposalAction[];
  targetTable: string | null;
  timeGrain: IngestionTimeGrain;
  matchColumns: string[];
  columnMapping: Record<string, string>;
  diffPreview: IngestionDiffPreview;
  risks: string[];
  explanation: string;
  sqlDraft: string;
  requiresCatalogSetup: boolean;
  createdAt: string;
};

export type IngestionHumanApproval = {
  required: boolean;
  mechanism: string;
  stage: "proposal_approval" | "catalog_setup";
  question: string;
  options: string[];
  recommendedOption: string | null;
};

export type IngestionPlanAwaitingSetup = {
  status: "awaiting_catalog_setup";
  workspaceId: string;
  jobId: string;
  agentGuess: IngestionAgentGuess;
  setupQuestions: IngestionSetupQuestion[];
  suggestedCatalogSeed: IngestionCatalogSetupSeed;
  humanApproval: IngestionHumanApproval;
  route: IngestionAgentRoute;
  toolTrace: Record<string, unknown>[];
};

export type IngestionPlanProposalEntry = {
  proposalId: string;
  proposal: IngestionProposal;
};

export type IngestionPlanAwaitingApproval = {
  status: "awaiting_user_approval";
  workspaceId: string;
  jobId: string;
  // Primary (first) proposal — kept for backward compat with single-proposal
  // consumers (chat input, summary message, existing tests).
  proposalId: string;
  proposal: IngestionProposal;
  // Full list. For a single-table plan, length === 1 and entries[0] mirrors
  // `proposalId`/`proposal`. For a multi-table decomposition (e.g. one Excel
  // split into a dimension table + a long-format fact table), length > 1 and
  // the UI must walk through them in order.
  proposals: IngestionPlanProposalEntry[];
  humanApproval: IngestionHumanApproval;
  route: IngestionAgentRoute;
  toolTrace: Record<string, unknown>[];
  existingTables?: Record<string, unknown>;
  setup?: {
    status: string;
    catalogEntry: Record<string, unknown>;
  };
};

export type IngestionPlanResult = IngestionPlanAwaitingSetup | IngestionPlanAwaitingApproval;

export type IngestionDryRunSummary = {
  approvedAction: IngestionProposalAction;
  targetTable: string;
  timeGrain: IngestionTimeGrain;
  predictedInsertCount: number;
  predictedUpdateCount: number;
  predictedConflictCount: number;
  predictedAffectedRows: number;
  schemaWarnings: string[];
  risks: string[];
};

export type IngestionApprovalCancelled = {
  status: "cancelled";
  workspaceId: string;
  jobId: string;
  proposalId: string;
  approvedAction: "cancel";
};

export type IngestionApprovalApproved = {
  status: "approved";
  workspaceId: string;
  jobId: string;
  proposalId: string;
  approvedAction: IngestionWriteMode;
  targetTable: string;
  timeGrain: IngestionTimeGrain;
  dryRunSummary: IngestionDryRunSummary;
};

export type IngestionApprovalResult = IngestionApprovalCancelled | IngestionApprovalApproved;

export type IngestionExecutionReceipt = {
  success: boolean;
  workspaceId: string;
  jobId: string;
  targetTable: string;
  executionMode: IngestionProposalAction;
  insertedRows: number;
  updatedRows: number;
  affectedRows: number;
  rowsAfter: number;
  duckdbPath: string;
  finishedAt: string;
};

export type IngestionExecuteResult = {
  status: "succeeded";
  workspaceId: string;
  jobId: string;
  proposalId: string;
  executionId: string;
  receipt: IngestionExecutionReceipt;
};

export type IngestionLifecyclePhase =
  | "idle"
  | "uploading"
  | "planning"
  | "awaiting_catalog_setup"
  | "awaiting_user_approval"
  | "approving"
  | "approved"
  | "executing"
  | "succeeded"
  | "cancelled"
  | "failed";
