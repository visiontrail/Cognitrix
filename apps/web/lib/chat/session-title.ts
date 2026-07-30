import { getAuthorizationHeader, type AuthContext } from "@/lib/auth/session";
import { isRecord } from "@/lib/utils";
import type { ChatSession } from "@/types/chat";

export const DEFAULT_SESSION_TITLE = "New Conversation";
export const SESSION_TITLE_MAX_LENGTH = 24;

export function normalizeSessionTitle(
  title: string,
  fallback: string = DEFAULT_SESSION_TITLE
): string {
  // Trim before stripping the "Title:" / "标题：" prefix — anchored at ^, the
  // prefix pattern misses whenever the model pads the title with whitespace.
  const cleaned = String(title ?? "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^(title|标题)\s*[:：-]\s*/i, "")
    .replace(/^["'`“”‘’]+|["'`“”‘’]+$/g, "")
    .trim();
  const resolved = cleaned || fallback.trim() || DEFAULT_SESSION_TITLE;
  const characters = Array.from(resolved);
  if (characters.length <= SESSION_TITLE_MAX_LENGTH) {
    return resolved;
  }
  return `${characters.slice(0, SESSION_TITLE_MAX_LENGTH - 1).join("").trimEnd()}…`;
}

export function buildFallbackSessionTitle(content: string): string {
  const normalized = String(content ?? "").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return DEFAULT_SESSION_TITLE;
  }
  const firstSentence = normalized.split(/[。！？!?；;\n]/, 1)[0]?.trim() || normalized;
  return normalizeSessionTitle(firstSentence, DEFAULT_SESSION_TITLE);
}

export function shouldAutoGenerateSessionTitle(
  session: Pick<ChatSession, "messageCount" | "title"> | undefined | null
): boolean {
  if (!session) {
    return false;
  }
  return session.messageCount === 0 && normalizeSessionTitle(session.title) === DEFAULT_SESSION_TITLE;
}

export async function requestGeneratedSessionTitle({
  apiBaseUrl,
  authContext,
  content,
  locale = "en",
}: {
  apiBaseUrl: string;
  authContext: AuthContext;
  content: string;
  locale?: string;
}): Promise<string> {
  const fallback = buildFallbackSessionTitle(content);
  const prompt = String(content ?? "").trim();
  if (!prompt) {
    return fallback;
  }

  const authorizationHeader = await getAuthorizationHeader(apiBaseUrl, authContext);
  const response = await fetch(`${apiBaseUrl}/chat/title`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authorizationHeader,
    },
    body: JSON.stringify({
      user_id: authContext.userId,
      project_id: authContext.projectId,
      prompt,
      locale,
    }),
  });

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(readErrorMessage(payload, `chat_title_failed_${response.status}`));
  }

  const rawTitle = isRecord(payload) ? String(payload.title ?? "") : "";
  return normalizeSessionTitle(rawTitle, fallback);
}

function readErrorMessage(payload: unknown, fallback: string): string {
  if (!isRecord(payload)) {
    return fallback;
  }

  const detail = isRecord(payload.detail) ? payload.detail : null;
  const detailMessage = detail ? String(detail.message ?? "") : "";
  if (detailMessage) {
    return detailMessage;
  }

  const payloadMessage = String(payload.message ?? "");
  return payloadMessage || fallback;
}
