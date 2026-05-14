import { getAuthorizationHeader } from "@/lib/auth/session";
import { API_BASE_URL } from "@/lib/api-base";
import { safeLoadFromStorage, safeSaveToStorage, WORKSPACE_SNAPSHOT_STORAGE_KEY } from "@/lib/chat/session-storage";
import type {
  TableCatalogDataColumn,
  TableCatalogDataPreview,
  TableCatalogEntry,
  Workspace,
  WorkspaceSnapshot,
} from "@/types/workspace";

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

type WorkspaceApiErrorShape = {
  code?: string;
  message: string;
  status: number;
};

type PersistedWorkspaceSnapshots = {
  version: 1;
  snapshots: Record<string, WorkspaceSnapshot>;
};

export class WorkspaceApiError extends Error {
  code?: string;
  status: number;

  constructor(shape: WorkspaceApiErrorShape) {
    super(shape.message);
    this.name = "WorkspaceApiError";
    this.code = shape.code;
    this.status = shape.status;
  }
}

export async function fetchWorkspaces(): Promise<Workspace[]> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const response = await fetch(`${API_BASE_URL}/workspaces`, {
    method: "GET",
    headers,
  });
  const payload = await readPayload(response);
  if (!response.ok) {
    throw toApiError(payload, response.status, "workspace_list_failed");
  }

  const snapshots = loadWorkspaceSnapshots();
  const data = asRecord(payload);
  return asRecordList(data.workspaces)
    .map((item) => mapWorkspace(item, snapshots))
    .filter((item): item is Workspace => item !== null);
}

export async function createWorkspace(title?: string, _description?: string): Promise<Workspace> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const response = await fetch(`${API_BASE_URL}/workspaces`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: JSON.stringify({
      name: (title ?? "").trim() || "Untitled Workspace",
    }),
  });
  const payload = await readPayload(response);
  if (!response.ok) {
    throw toApiError(payload, response.status, "workspace_create_failed");
  }
  const workspace = mapWorkspace(asRecord(payload), loadWorkspaceSnapshots());
  if (!workspace) {
    throw new WorkspaceApiError({
      code: "workspace_create_invalid_payload",
      message: "Workspace create response is invalid",
      status: 500,
    });
  }
  return workspace;
}

export async function deleteWorkspace(workspaceId: string): Promise<void> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const response = await fetch(`${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}`, {
    method: "DELETE",
    headers,
  });
  const payload = await readPayload(response);
  if (!response.ok) {
    throw toApiError(payload, response.status, "workspace_delete_failed");
  }
  removeWorkspaceSnapshot(workspaceId);
}

export async function updateWorkspaceTitle(workspaceId: string, title: string): Promise<void> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const response = await fetch(`${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: JSON.stringify({
      name: title.trim(),
    }),
  });
  const payload = await readPayload(response);
  if (!response.ok) {
    throw toApiError(payload, response.status, "workspace_rename_failed");
  }
}

export async function fetchWorkspaceSnapshot(workspaceId: string): Promise<WorkspaceSnapshot | null> {
  if (!workspaceId.trim()) {
    return null;
  }
  const snapshots = loadWorkspaceSnapshots();
  return snapshots[workspaceId] ?? null;
}

export async function saveWorkspaceSnapshot(snapshot: WorkspaceSnapshot): Promise<void> {
  const persisted = loadPersistedWorkspaceSnapshots();
  const next: PersistedWorkspaceSnapshots = {
    version: 1,
    snapshots: {
      ...persisted.snapshots,
      [snapshot.workspaceId]: snapshot,
    },
  };
  savePersistedWorkspaceSnapshots(next);
}

export async function fetchWorkspaceCatalog(workspaceId: string): Promise<TableCatalogEntry[]> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const response = await fetch(
    `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/catalog`,
    {
      method: "GET",
      headers,
    }
  );
  const payload = await readPayload(response);
  if (!response.ok) {
    throw toApiError(payload, response.status, "workspace_catalog_list_failed");
  }
  const data = asRecord(payload);
  return asRecordList(data.entries)
    .map((item) => mapTableCatalogEntry(item))
    .filter((item): item is TableCatalogEntry => item !== null);
}

export async function fetchWorkspaceCatalogDataPreview(
  workspaceId: string,
  catalogId: string,
  options: { limit?: number; offset?: number } = {}
): Promise<TableCatalogDataPreview> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const params = new URLSearchParams({
    limit: String(options.limit ?? 100),
    offset: String(options.offset ?? 0),
  });
  const response = await fetch(
    `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/catalog/${encodeURIComponent(catalogId)}/data?${params.toString()}`,
    {
      method: "GET",
      headers,
    }
  );
  const payload = await readPayload(response);
  if (!response.ok) {
    throw toApiError(payload, response.status, "workspace_catalog_data_preview_failed");
  }

  const preview = mapTableCatalogDataPreview(asRecord(payload));
  if (!preview) {
    throw new WorkspaceApiError({
      code: "workspace_catalog_data_preview_invalid_payload",
      message: "Workspace catalog data preview response is invalid",
      status: 500,
    });
  }
  return preview;
}

export async function deleteWorkspaceCatalogEntry(
  workspaceId: string,
  catalogId: string
): Promise<void> {
  const headers = await getAuthorizationHeader(API_BASE_URL, DEFAULT_AUTH_CONTEXT);
  const response = await fetch(
    `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/catalog/${encodeURIComponent(catalogId)}`,
    {
      method: "DELETE",
      headers,
    }
  );
  const payload = await readPayload(response);
  if (!response.ok) {
    throw toApiError(payload, response.status, "workspace_catalog_delete_failed");
  }
}

function mapWorkspace(
  value: Record<string, unknown>,
  snapshots: Record<string, WorkspaceSnapshot>
): Workspace | null {
  const workspaceId = asString(value.workspace_id);
  if (!workspaceId) {
    return null;
  }
  return {
    id: workspaceId,
    title: asString(value.name) || "Untitled Workspace",
    createdAt: asString(value.created_at) || new Date().toISOString(),
    updatedAt: asString(value.updated_at) || new Date().toISOString(),
    nodeCount: countSnapshotNodes(snapshots[workspaceId]),
    role: asOptionalString(value.role),
  };
}

function countSnapshotNodes(snapshot: WorkspaceSnapshot | undefined): number {
  if (!snapshot) return 0;
  if (snapshot.nodesByFormat) {
    return Object.values(snapshot.nodesByFormat).reduce((sum, arr) => sum + (arr?.length ?? 0), 0);
  }
  return snapshot.nodes?.length ?? 0;
}

function mapTableCatalogEntry(value: Record<string, unknown>): TableCatalogEntry | null {
  const entryId = asString(value.id);
  const workspaceId = asString(value.workspace_id);
  if (!entryId || !workspaceId) {
    return null;
  }
  return {
    id: entryId,
    workspaceId,
    tableName: asString(value.table_name),
    humanLabel: asString(value.human_label),
    businessType: asString(value.business_type) as TableCatalogEntry["businessType"],
    writeMode: asString(value.write_mode) as TableCatalogEntry["writeMode"],
    timeGrain: asString(value.time_grain) as TableCatalogEntry["timeGrain"],
    isActiveTarget: Boolean(value.is_active_target),
    primaryKeys: asStringList(value.primary_keys),
    matchColumns: asStringList(value.match_columns),
    description: asString(value.description),
    createdAt: asString(value.created_at),
    updatedAt: asString(value.updated_at),
  };
}

function mapTableCatalogDataPreview(
  value: Record<string, unknown>
): TableCatalogDataPreview | null {
  const entry = mapTableCatalogEntry(asRecord(value.entry));
  if (!entry) {
    return null;
  }
  return {
    entry,
    table: asString(value.table),
    rowCount: asNumber(value.row_count),
    limit: asNumber(value.limit),
    offset: asNumber(value.offset),
    hasMore: Boolean(value.has_more),
    columns: asRecordList(value.columns).map(mapTableCatalogDataColumn),
    rows: Array.isArray(value.rows)
      ? value.rows.filter((item): item is Record<string, unknown> => isRecord(item))
      : [],
  };
}

function mapTableCatalogDataColumn(value: Record<string, unknown>): TableCatalogDataColumn {
  return {
    name: asString(value.name),
    type: asString(value.type),
    nullable: Boolean(value.nullable),
    primaryKey: Boolean(value.primary_key),
    label: asOptionalString(value.label),
  };
}

function removeWorkspaceSnapshot(workspaceId: string): void {
  const persisted = loadPersistedWorkspaceSnapshots();
  const snapshots = { ...persisted.snapshots };
  delete snapshots[workspaceId];
  savePersistedWorkspaceSnapshots({
    version: 1,
    snapshots,
  });
}

function loadWorkspaceSnapshots(): Record<string, WorkspaceSnapshot> {
  return loadPersistedWorkspaceSnapshots().snapshots;
}

function loadPersistedWorkspaceSnapshots(): PersistedWorkspaceSnapshots {
  const stored = safeLoadFromStorage<Partial<PersistedWorkspaceSnapshots>>(WORKSPACE_SNAPSHOT_STORAGE_KEY);
  if (!stored || typeof stored !== "object") {
    return { version: 1, snapshots: {} };
  }
  const snapshots =
    stored.snapshots && typeof stored.snapshots === "object" && !Array.isArray(stored.snapshots)
      ? (stored.snapshots as Record<string, WorkspaceSnapshot>)
      : {};
  return {
    version: 1,
    snapshots,
  };
}

function savePersistedWorkspaceSnapshots(value: PersistedWorkspaceSnapshots): void {
  safeSaveToStorage<PersistedWorkspaceSnapshots>(WORKSPACE_SNAPSHOT_STORAGE_KEY, value);
}

async function readPayload(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function toApiError(payload: unknown, status: number, fallbackCode: string): WorkspaceApiError {
  const detail = extractErrorDetail(payload);
  return new WorkspaceApiError({
    code: detail.code || fallbackCode,
    message: detail.message || fallbackCode,
    status,
  });
}

function extractErrorDetail(payload: unknown): { code?: string; message?: string } {
  if (!isRecord(payload)) {
    return {};
  }
  const detail = isRecord(payload.detail) ? payload.detail : payload;
  return {
    code: asOptionalString(detail.code),
    message: asOptionalString(detail.message),
  };
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function asOptionalString(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}

function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function asRecordList(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is Record<string, unknown> => isRecord(item));
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
