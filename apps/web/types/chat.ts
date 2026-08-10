export type ChatSession = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
  lastMessage?: string;
};

export type MessageRole = "user" | "assistant" | "system";

export type TraceSummary = {
  stepCount: number;
  durationMs: number;
  status: "ok" | "error" | "incomplete";
};

// A web source cited in an assistant answer that used the web-research tools.
// `id` matches an inline `[n]` citation in the message prose.
export type MessageSource = {
  id: number;
  title: string;
  url: string;
};

export type ChatMessage = {
  id: string;
  sessionId: string;
  role: MessageRole;
  content: string;
  chartAsset?: ChartAssetReference;
  chartAssets?: ChartAssetReference[];
  multiChartConfirmation?: MultiChartConfirmation;
  // Agent-canvas-mode: the dashboard outline awaiting (or granted) approval.
  agentRunOutline?: AgentRunOutline;
  // Agent-canvas-mode: terminal run summary for the completed/stopped run,
  // carrying what the undo affordance needs (run page id).
  agentRun?: AgentRunSummary;
  timestamp: string;
  traceSummary?: TraceSummary;
  // Web sources cited by the assistant (only present when the answer used web
  // tools). Persisted with the message so the citation区 survives a reload.
  sources?: MessageSource[];
  // The "+" menu generation options the user selected on the request turn that
  // produced this assistant message (e.g. multi-chart, data labels). Surfaced
  // in the agent-trace summary line; persisted so it survives a reload.
  generationOptions?: import("@/lib/chat/generation-options").GenerationOptionId[];
};

export type ChartAssetReference = {
  assetId: string;
  title: string;
  chartType: string;
  thumbnailPreview?: string;
};

export type AssistantResponse = {
  messageId: string;
  content: string;
  chartSpec?: import("./chart").ChartSpec;
  chartAssets?: import("./chart").ChartAsset[];
  suggestedActions?: SuggestedAction[];
};

export type SuggestedAction = {
  label: string;
  action: "add_to_canvas" | "regenerate" | "duplicate" | "open_workspace";
  payload?: Record<string, unknown>;
};

export type SendMessageRequest = {
  sessionId: string;
  content: string;
  attachment?: File;
  preferredChartType?: import("./chart").KnownChartType;
  generationStrategy?: "multi_chart";
  showDataLabels?: boolean;
  multiChartConfirmation?: MultiChartConfirmationSubmission;
};

export type MultiChartConfirmationItem = {
  key: string;
  label: string;
  selected?: boolean;
};

export type MultiChartConfirmation = {
  confirmationId: string;
  groupingDimension: string;
  proposedCount: number;
  maxChartCount: number;
  reason: string;
  expiresAt?: number;
  truncated?: boolean;
  items: MultiChartConfirmationItem[];
  // Client-only generation options captured on the request turn that opened
  // this confirmation, so they can be replayed when the user confirms (the
  // spec-bearing turn). `showDataLabels` drives the post-processing transform
  // in `toChartAsset`; it is never sent to the backend.
  showDataLabels?: boolean;
};

export type MultiChartConfirmationSubmission = {
  confirmationId: string;
  action: "confirm" | "adjust" | "cancel";
  selectedItems?: Array<{ key: string; label?: string }>;
};

// ---- Agent canvas mode (long-horizon dashboard generation) ----

export type AgentRunOutlineItem = {
  key: string;
  kind: "chart" | "text";
  title?: string;
  description?: string;
  chartType?: string;
  sizePreset?: string;
  style?: string;
  content?: string;
};

export type AgentRunOutlineSection = {
  key: string;
  title: string;
  /** 1 = section heading, 2 = sub-section nested under the preceding section. */
  level: 1 | 2;
  /** Page this section belongs to; sections sharing a key land on one page. */
  pageKey: string;
  pageTitle: string;
  items: AgentRunOutlineItem[];
};

export type AgentRunOutline = {
  confirmationId: string;
  runId: string;
  canvasFormat: import("./workspace").WorkspaceCanvasFormatId;
  pageTitle: string;
  sections: AgentRunOutlineSection[];
  proposedChartCount: number;
  maxChartCount: number;
  /** Number of pages (sidebar entries) the run will create. */
  proposedPageCount: number;
  maxPageCount: number;
  expiresAt?: number;
  reason?: string;
  truncated?: boolean;
  /** True when the planned pages were folded down to the page budget. */
  pagesTruncated?: boolean;
  // True when the outline was auto-approved (informational card, no buttons).
  approved?: boolean;
};

export type AgentRunConfirmationSubmission = {
  confirmationId: string;
  action: "confirm" | "cancel";
  selectedItemKeys?: string[];
};

export type AgentRunSummary = {
  runId: string;
  pageId: string;
  canvasFormat: import("./workspace").WorkspaceCanvasFormatId;
  status: string;
  placedCount: number;
  failedCount: number;
  skippedCount: number;
};

// Ephemeral bridge from a canvas chart into the chat composer. The target is
// intentionally not persisted: it represents the user's current editing
// gesture, while the eventual replacement is saved in the workspace snapshot.
export type CanvasChartEditTarget = {
  sessionId: string;
  workspaceId: string;
  canvasFormat: import("./workspace").WorkspaceCanvasFormatId;
  nodeId: string;
  zoneId?: string;
  pageId?: string;
  assetId: string;
  title: string;
  chartType: string;
  spec: import("./chart").ChartSpec;
  assistantRows?: Record<string, unknown>[];
};

export type SendMessageResponse = {
  message: ChatMessage;
  assistantResponse: AssistantResponse;
};

export type StreamEvent = {
  type: "text" | "chart" | "action" | "done" | "error";
  data: unknown;
};
