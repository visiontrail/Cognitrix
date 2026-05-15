"use client";

import { useQueries } from "@tanstack/react-query";
import { useWorkspaceCatalog } from "@/hooks/use-workspace";
import * as api from "@/lib/workspace/api";

export type ColumnMentionItem = {
  id: string;
  tableName: string;
  tableLabel: string;
  columnName: string;
  columnLabel: string;
  columnType: string;
};

export function useWorkspaceColumns(workspaceId: string | null): ColumnMentionItem[] {
  const { data: catalog = [] } = useWorkspaceCatalog(workspaceId);

  const readyEntries = catalog.filter(
    (entry) => entry.primaryKeys.length > 0 || entry.matchColumns.length > 0
  );

  const previews = useQueries({
    queries: readyEntries.map((entry) => ({
      queryKey: ["workspace-catalog-data", workspaceId, entry.id, 1, 0],
      queryFn: async () => {
        if (!workspaceId) return null;
        return api.fetchWorkspaceCatalogDataPreview(workspaceId, entry.id, { limit: 1, offset: 0 });
      },
      enabled: Boolean(workspaceId && entry.id),
      staleTime: 5 * 60 * 1000,
      retry: (failureCount: number, error: unknown) => {
        if (error instanceof api.WorkspaceApiError && error.status === 404) return false;
        return failureCount < 3;
      },
    })),
  });

  return previews.flatMap((result, index) => {
    const entry = readyEntries[index];
    if (!result.data || !entry) return [];
    return result.data.columns.map((col) => ({
      id: `${entry.tableName}.${col.name}`,
      tableName: entry.tableName,
      tableLabel: entry.humanLabel || entry.tableName,
      columnName: col.name,
      columnLabel: col.description || col.originalName || col.label || col.name,
      columnType: col.type,
    }));
  });
}
