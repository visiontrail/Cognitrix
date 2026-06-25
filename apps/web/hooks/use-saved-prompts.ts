"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  archiveSavedPrompt,
  createSavedPrompt,
  listSavedPrompts,
  markSavedPromptUsed,
  updateSavedPrompt,
} from "@/lib/saved-prompts/api";
import type {
  SavedPrompt,
  SavedPromptCreateInput,
  SavedPromptListParams,
  SavedPromptUpdateInput,
} from "@/lib/saved-prompts/types";

export const savedPromptsQueryKey = (params: SavedPromptListParams = {}) =>
  [
    "saved-prompts",
    params.query?.trim() ?? "",
    params.includeArchived ?? false,
    params.limit ?? null,
  ] as const;

export function useSavedPrompts(params: SavedPromptListParams = {}, enabled = true) {
  return useQuery({
    queryKey: savedPromptsQueryKey(params),
    queryFn: () => listSavedPrompts(params),
    enabled,
    staleTime: 30_000,
  });
}

function useInvalidatePrompts() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["saved-prompts"] });
}

export function useCreateSavedPrompt() {
  const invalidate = useInvalidatePrompts();
  return useMutation<SavedPrompt, Error, SavedPromptCreateInput>({
    mutationFn: createSavedPrompt,
    onSuccess: invalidate,
  });
}

export function useUpdateSavedPrompt() {
  const invalidate = useInvalidatePrompts();
  return useMutation<SavedPrompt, Error, { promptId: string; input: SavedPromptUpdateInput }>({
    mutationFn: ({ promptId, input }) => updateSavedPrompt(promptId, input),
    onSuccess: invalidate,
  });
}

export function useArchiveSavedPrompt() {
  const invalidate = useInvalidatePrompts();
  return useMutation<SavedPrompt, Error, string>({
    mutationFn: archiveSavedPrompt,
    onSuccess: invalidate,
  });
}

export function useMarkSavedPromptUsed() {
  const invalidate = useInvalidatePrompts();
  return useMutation<SavedPrompt, Error, string>({
    mutationFn: markSavedPromptUsed,
    // Refresh ordering (most-recently-used first) after a prompt is applied.
    onSuccess: invalidate,
  });
}
