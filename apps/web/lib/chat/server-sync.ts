// Commit-point helpers that push the local chat working copy up to the server.
//
// These are best-effort: localStorage remains the synchronous live cache, and
// these calls mirror it to the durable server store so the data shows up on
// other browsers/devices. Failures are swallowed — the local cache is unchanged
// and the next commit (or a reload-triggered backfill) will retry.

import { useChatStore } from "@/stores/chat-store";
import { useAssetStore } from "@/stores/asset-store";
import type { ChatMessage } from "@/types/chat";
import {
  deleteServerSession,
  fetchServerAssets,
  fetchServerSessions,
  mergeAssets,
  mergeSessions,
  putServerAsset,
  putServerMessages,
  putServerSession,
} from "./persistence-api";

function collectAssetIds(messages: ChatMessage[]): Set<string> {
  const ids = new Set<string>();
  for (const message of messages) {
    if (message.chartAsset?.assetId) ids.add(message.chartAsset.assetId);
    for (const ref of message.chartAssets ?? []) {
      if (ref.assetId) ids.add(ref.assetId);
    }
  }
  return ids;
}

/**
 * Push a session's metadata, full message list, and any chart assets those
 * messages reference to the server. Pushing referenced assets here (rather than
 * a separate user-global sweep) guarantees each asset lands in the same
 * workspace as the session that references it.
 */
export async function syncSessionToServer(workspaceId: string, sessionId: string): Promise<void> {
  if (!workspaceId || !sessionId) return;
  const chat = useChatStore.getState();
  const session = chat.sessions.find((item) => item.id === sessionId);
  if (!session) return;
  const messages = chat.messagesBySession[sessionId] ?? [];

  try {
    await putServerSession(workspaceId, session);
    await putServerMessages(workspaceId, sessionId, messages);
    const assetIds = collectAssetIds(messages);
    if (assetIds.size > 0) {
      const assetStore = useAssetStore.getState();
      await Promise.all(
        Array.from(assetIds).map((assetId) => {
          const asset = assetStore.getAsset(assetId);
          return asset ? putServerAsset(workspaceId, asset).catch(() => undefined) : Promise.resolve();
        })
      );
    }
  } catch {
    // best-effort; localStorage cache is authoritative locally
  }
}

export async function removeSessionFromServer(workspaceId: string, sessionId: string): Promise<void> {
  if (!workspaceId || !sessionId) return;
  try {
    await deleteServerSession(workspaceId, sessionId);
  } catch {
    // best-effort
  }
}

/**
 * Merge the server's durable chat sessions and chart assets for a workspace into
 * the local stores. Call this once per workspace selection, strictly AFTER the
 * localStorage cache has been loaded into the stores (AppShell does this right
 * after initChatForWorkspace / initAssetsForUser), so a fresh device pulls the
 * full set from the server and the active device never loses its live copy.
 *
 * Messages are hydrated lazily per active session by useChatMessages; this only
 * covers the session list and the chart assets needed to render restored chats.
 */
export async function hydrateWorkspaceStateFromServer(workspaceId: string): Promise<void> {
  if (!workspaceId) return;

  const localSessions = useChatStore.getState().sessions;
  try {
    const serverSessions = await fetchServerSessions(workspaceId);
    useChatStore.getState().setSessions(mergeSessions(serverSessions, localSessions));
    // Backfill sessions (and their messages + referenced assets) that exist only
    // on this device — e.g. data created before server persistence existed.
    const serverIds = new Set(serverSessions.map((session) => session.id));
    for (const session of localSessions) {
      if (!serverIds.has(session.id)) {
        void syncSessionToServer(workspaceId, session.id);
      }
    }
  } catch {
    // Offline / server unavailable: the localStorage cache already loaded stands.
  }

  const localAssets = useAssetStore.getState().assets;
  try {
    const serverAssets = await fetchServerAssets(workspaceId);
    useAssetStore.getState().setAssets(mergeAssets(serverAssets, localAssets));
  } catch {
    // Offline / server unavailable: keep the localStorage cache.
  }
}
