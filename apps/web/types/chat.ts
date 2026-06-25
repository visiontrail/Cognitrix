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

export type ChatMessage = {
  id: string;
  sessionId: string;
  role: MessageRole;
  content: string;
  chartAsset?: ChartAssetReference;
  chartAssets?: ChartAssetReference[];
  multiChartConfirmation?: MultiChartConfirmation;
  timestamp: string;
  traceSummary?: TraceSummary;
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

export type SendMessageResponse = {
  message: ChatMessage;
  assistantResponse: AssistantResponse;
};

export type StreamEvent = {
  type: "text" | "chart" | "action" | "done" | "error";
  data: unknown;
};
