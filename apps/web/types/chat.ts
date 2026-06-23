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
