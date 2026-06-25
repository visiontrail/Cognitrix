// Saved prompts: user-owned reusable prompt library.
// Mirrors the backend `/saved-prompts` response shape in apps/api/saved_prompts.py.

// Controlled capability-hint allowlist. Keep in sync with ALLOWED_CAPABILITIES
// in apps/api/saved_prompts.py.
export const SAVED_PROMPT_CAPABILITIES = ["file_upload", "multi_chart", "data_labels"] as const;

export type SavedPromptCapability = (typeof SAVED_PROMPT_CAPABILITIES)[number];

export type SavedPrompt = {
  id: string;
  name: string;
  body: string;
  variables: string[];
  capabilities: SavedPromptCapability[];
  usageCount: number;
  lastUsedAt: string | null;
  createdAt: string;
  updatedAt: string;
  archivedAt: string | null;
};

export type SavedPromptCreateInput = {
  name: string;
  body: string;
  capabilities?: SavedPromptCapability[];
};

export type SavedPromptUpdateInput = {
  name?: string;
  body?: string;
  capabilities?: SavedPromptCapability[];
};

export type SavedPromptListParams = {
  query?: string;
  includeArchived?: boolean;
  limit?: number;
};

export function isSavedPromptCapability(value: string): value is SavedPromptCapability {
  return (SAVED_PROMPT_CAPABILITIES as readonly string[]).includes(value);
}
