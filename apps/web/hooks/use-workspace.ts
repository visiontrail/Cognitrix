"use client";

import { useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useWorkspaceStore } from "@/stores/workspace-store";
import { useUIStore } from "@/stores/ui-store";
import { useI18n } from "@/lib/i18n/context";
import { refreshWorkspaceCatalog, workspaceCatalogQueryKey } from "@/lib/workspace/query-keys";
import {
  chatStorageKeyForWorkspace,
  safeRemoveFromStorage,
  traceStorageKeyForWorkspace,
} from "@/lib/chat/session-storage";
import { useSession } from "@/lib/auth/use-session";
import type { WorkspaceSnapshot } from "@/types/workspace";
import * as api from "@/lib/workspace/api";

const AUTO_SAVE_DELAY_MS = 900;
const AUTO_SAVE_RETRY_DELAY_MS = 5000;

export function useWorkspaceList() {
  const setWorkspaces = useWorkspaceStore((s) => s.setWorkspaces);

  return useQuery({
    queryKey: ["workspaces"],
    queryFn: async () => {
      const workspaces = await api.fetchWorkspaces();
      setWorkspaces(workspaces);
      return workspaces;
    },
  });
}

export function useWorkspaceSnapshot(workspaceId: string | null) {
  const loadSnapshot = useWorkspaceStore((s) => s.loadSnapshot);

  return useQuery({
    queryKey: ["workspace-snapshot", workspaceId],
    queryFn: async () => {
      if (!workspaceId) return null;
      const snapshot = await api.fetchWorkspaceSnapshot(workspaceId);
      if (snapshot) loadSnapshot(snapshot);
      return snapshot;
    },
    enabled: !!workspaceId,
    // staleTime must be 0 so that switching back to a previously-visited workspace always
    // re-runs the queryFn and calls loadSnapshot with the latest localStorage data.
    // The global staleTime of 30s would serve a cached result without calling loadSnapshot,
    // leaving the canvas at the cleared default state after setActiveWorkspace().
    staleTime: 0,
  });
}

export function useWorkspaceCatalog(workspaceId: string | null) {
  return useQuery({
    queryKey: workspaceCatalogQueryKey(workspaceId),
    queryFn: async () => {
      if (!workspaceId) return [];
      return api.fetchWorkspaceCatalog(workspaceId);
    },
    enabled: !!workspaceId,
  });
}

export function useWorkspaceCatalogDataPreview(
  workspaceId: string | null,
  catalogId: string | null,
  options: { limit?: number; offset?: number } = {}
) {
  const limit = options.limit ?? 100;
  const offset = options.offset ?? 0;
  return useQuery({
    queryKey: ["workspace-catalog-data", workspaceId, catalogId, limit, offset],
    queryFn: async () => {
      if (!workspaceId || !catalogId) return null;
      return api.fetchWorkspaceCatalogDataPreview(workspaceId, catalogId, { limit, offset });
    },
    enabled: Boolean(workspaceId && catalogId),
    retry: (failureCount, error) => {
      if (error instanceof api.WorkspaceApiError && error.status === 404) return false;
      return failureCount < 3;
    },
  });
}

export function useDeleteWorkspaceCatalogEntry() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ workspaceId, catalogId }: { workspaceId: string; catalogId: string }) =>
      api.deleteWorkspaceCatalogEntry(workspaceId, catalogId),
    onSuccess: async (_, variables) => {
      await refreshWorkspaceCatalog(queryClient, variables.workspaceId);
    },
  });
}

export function useCreateWorkspace() {
  const queryClient = useQueryClient();
  const addWorkspace = useWorkspaceStore((s) => s.addWorkspace);
  const setActiveWorkspace = useWorkspaceStore((s) => s.setActiveWorkspace);

  return useMutation({
    mutationFn: ({ title, description }: { title?: string; description?: string }) =>
      api.createWorkspace(title, description),
    onSuccess: (workspace) => {
      addWorkspace(workspace);
      setActiveWorkspace(workspace.id);
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
}

export function useDeleteWorkspace() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const removeWorkspace = useWorkspaceStore((s) => s.removeWorkspace);
  const { user } = useSession();

  return useMutation({
    // Accepts either a bare workspace id (legacy callers) or an object that
    // includes the typed confirmation. The server-side guardrail rejects a
    // mismatched name with WORKSPACE_DELETE_CONFIRM_MISMATCH so we surface
    // that as a user-visible toast.
    mutationFn: (input: string | { workspaceId: string; confirmWorkspaceName?: string }) => {
      if (typeof input === "string") {
        return api.deleteWorkspace(input).then(() => input);
      }
      return api
        .deleteWorkspace(input.workspaceId, { confirmWorkspaceName: input.confirmWorkspaceName })
        .then(() => input.workspaceId);
    },
    onSuccess: (workspaceId) => {
      removeWorkspace(workspaceId);
      // Drop the workspace-scoped chat + trace caches from localStorage so the
      // deleted workspace's sessions don't linger on this device. Server-side
      // SQL/FS state is already gone (hard delete cascade).
      const userId = user?.id;
      if (userId) {
        safeRemoveFromStorage(chatStorageKeyForWorkspace(userId, workspaceId));
        safeRemoveFromStorage(traceStorageKeyForWorkspace(userId, workspaceId));
      }
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success(t("workspace.toast.deleted"));
    },
    onError: (error) => {
      if (error instanceof api.WorkspaceApiError) {
        if (error.status === 403) {
          toast.error(t("workspace.toast.deleteForbidden"));
          return;
        }
        if (error.code === "WORKSPACE_DELETE_CONFIRM_MISMATCH") {
          toast.error(t("workspace.toast.deleteConfirmMismatch"));
          return;
        }
      }
      toast.error(t("workspace.toast.deleteFailed"));
    },
  });
}

export function useRenameWorkspace() {
  const queryClient = useQueryClient();
  const updateWorkspaceTitle = useWorkspaceStore((s) => s.updateWorkspaceTitle);

  return useMutation({
    mutationFn: async ({ workspaceId, title }: { workspaceId: string; title: string }) => {
      const trimmedTitle = title.trim();
      if (!trimmedTitle) throw new Error("Workspace name cannot be empty");

      await api.updateWorkspaceTitle(workspaceId, trimmedTitle);
      return { workspaceId, title: trimmedTitle };
    },
    onSuccess: ({ workspaceId, title }) => {
      updateWorkspaceTitle(workspaceId, title);
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
    },
  });
}

export function useSaveWorkspace() {
  const queryClient = useQueryClient();
  const setIsSaving = useUIStore((s) => s.setIsSaving);
  const setHasUnsavedChanges = useWorkspaceStore((s) => s.setHasUnsavedChanges);

  return useMutation({
    mutationFn: async () => {
      const snapshot = useWorkspaceStore.getState().getSnapshot();
      if (!snapshot) throw new Error("No active workspace to save");
      const savedSnapshotKey = serializeWorkspaceSnapshot(snapshot);
      setIsSaving(true);
      await api.saveWorkspaceSnapshot(snapshot);
      return { savedSnapshotKey };
    },
    onSuccess: ({ savedSnapshotKey }) => {
      const currentSnapshot = useWorkspaceStore.getState().getSnapshot();
      if (currentSnapshot && serializeWorkspaceSnapshot(currentSnapshot) === savedSnapshotKey) {
        setHasUnsavedChanges(false);
      }
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
    },
    onSettled: () => {
      setIsSaving(false);
    },
  });
}

export function useAutoSaveWorkspace(options: { enabled?: boolean } = {}) {
  const { t } = useI18n();
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);
  const hasUnsavedChanges = useWorkspaceStore((s) => s.hasUnsavedChanges);
  const nodes = useWorkspaceStore((s) => s.nodes);
  const edges = useWorkspaceStore((s) => s.edges);
  const viewport = useWorkspaceStore((s) => s.viewport);
  const canvasFormat = useWorkspaceStore((s) => s.canvasFormat);
  const webDesign = useWorkspaceStore((s) => s.webDesign);
  const { mutate, isPending } = useSaveWorkspace();
  const retryAfterFailureRef = useRef(false);

  useEffect(() => {
    if (!options.enabled || !activeWorkspaceId || !hasUnsavedChanges || isPending) {
      return;
    }

    const timeout = window.setTimeout(
      () => {
        mutate(undefined, {
          onSuccess: () => {
            retryAfterFailureRef.current = false;
          },
          onError: () => {
            retryAfterFailureRef.current = true;
            toast.error(t("workspace.toast.autosaveFailed"));
          },
        });
      },
      retryAfterFailureRef.current ? AUTO_SAVE_RETRY_DELAY_MS : AUTO_SAVE_DELAY_MS
    );

    return () => window.clearTimeout(timeout);
  }, [
    activeWorkspaceId,
    canvasFormat,
    edges,
    hasUnsavedChanges,
    isPending,
    mutate,
    nodes,
    options.enabled,
    t,
    viewport,
    webDesign,
  ]);
}

function serializeWorkspaceSnapshot(snapshot: WorkspaceSnapshot): string {
  return JSON.stringify(snapshot);
}
