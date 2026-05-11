export const SESSION_STORAGE_KEY = "cognitrix:chat-workbench:v1";
export const CHAT_STORAGE_KEY = "cognitrix:chat:v1";
export const CHART_ASSETS_STORAGE_KEY = "cognitrix:chart-assets:v1";
export const WORKSPACE_SELECTION_STORAGE_KEY = "cognitrix:workspace-selection:v1";
export const WORKSPACE_SNAPSHOT_STORAGE_KEY = "cognitrix:workspace-snapshots:v1";

export function chatStorageKeyForUser(userId: string): string {
  return `cognitrix:chat:v1:${userId}`;
}

export function chatStorageKeyForWorkspace(userId: string, workspaceId: string): string {
  return `cognitrix:chat:v2:${userId}:${workspaceId}`;
}

export function assetStorageKeyForUser(userId: string): string {
  return `cognitrix:chart-assets:v1:${userId}`;
}

export function traceStorageKeyForUser(userId: string): string {
  return `cognitrix:chat-trace:v1:${userId}`;
}

export function traceStorageKeyForWorkspace(userId: string, workspaceId: string): string {
  return `cognitrix:chat-trace:v2:${userId}:${workspaceId}`;
}

export function legacyChatMigrationStorageKeyForUser(userId: string): string {
  return `cognitrix:chat:v1-migration:${userId}`;
}

export function safeLoadFromStorage<T>(key: string): T | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) {
      return null;
    }
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function safeSaveToStorage<T>(key: string, value: T): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Ignore storage failures, UI should still function in memory.
  }
}
