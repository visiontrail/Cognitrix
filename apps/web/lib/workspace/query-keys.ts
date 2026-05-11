import type { QueryClient } from "@tanstack/react-query";

export const workspaceCatalogQueryKey = (workspaceId: string | null | undefined) =>
  ["workspace-catalog", workspaceId ?? null] as const;

export const workspaceCatalogDataQueryKey = (workspaceId: string | null | undefined) =>
  ["workspace-catalog-data", workspaceId ?? null] as const;

export async function refreshWorkspaceCatalog(
  queryClient: QueryClient,
  workspaceId: string | null | undefined
) {
  if (!workspaceId) return;

  await Promise.all([
    queryClient.invalidateQueries({ queryKey: workspaceCatalogQueryKey(workspaceId) }),
    queryClient.invalidateQueries({ queryKey: workspaceCatalogDataQueryKey(workspaceId) }),
  ]);
}
