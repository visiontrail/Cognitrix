// Pure helpers for saved-prompt variable parsing, template rendering, and
// caret-aware insertion. Mirrors the backend variable syntax in
// apps/api/saved_prompts.py (single-brace {name}, \{ \} escapes, {{ }} ignored).

import {
  isGenerationOptionId,
  type GenerationOptionId,
} from "@/lib/chat/generation-options";
import type { SavedPromptCapability } from "@/lib/saved-prompts/types";

const VARIABLE_NAME_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;

export type VariableParseResult =
  | { ok: true; variables: string[] }
  | { ok: false; errorCode: "PROMPT_VARIABLE_INVALID" | "PROMPT_VARIABLE_AMBIGUOUS"; token: string };

/**
 * Extract `{variable}` placeholders in first-seen order. Repeated exact names
 * collapse to one entry. Returns an error result for malformed names or
 * case-ambiguous duplicates. Mirrors the server parser so the editor can show
 * validation before submitting.
 */
export function parseVariables(body: string): VariableParseResult {
  const ordered: string[] = [];
  const seenLower = new Map<string, string>();
  const length = body.length;
  let i = 0;
  while (i < length) {
    const char = body[i];

    if (char === "\\" && i + 1 < length && (body[i + 1] === "{" || body[i + 1] === "}")) {
      i += 2;
      continue;
    }

    if (char === "{") {
      if (i + 1 < length && body[i + 1] === "{") {
        i += 2;
        continue;
      }
      const closing = body.indexOf("}", i + 1);
      if (closing === -1) {
        return { ok: false, errorCode: "PROMPT_VARIABLE_INVALID", token: body.slice(i) };
      }
      const inner = body.slice(i + 1, closing);
      if (!VARIABLE_NAME_RE.test(inner)) {
        return { ok: false, errorCode: "PROMPT_VARIABLE_INVALID", token: `{${inner}}` };
      }
      const lower = inner.toLowerCase();
      const existing = seenLower.get(lower);
      if (existing === undefined) {
        seenLower.set(lower, inner);
        ordered.push(inner);
      } else if (existing !== inner) {
        return { ok: false, errorCode: "PROMPT_VARIABLE_AMBIGUOUS", token: `{${inner}}` };
      }
      i = closing + 1;
      continue;
    }

    i += 1;
  }

  return { ok: true, variables: ordered };
}

/**
 * Render a prompt body by substituting every `{variable}` occurrence with its
 * supplied value and collapsing escaped braces to literals. Unknown variables
 * are left untouched so partial values never silently drop placeholders.
 */
export function renderTemplate(body: string, values: Record<string, string>): string {
  const lowerValues = new Map<string, string>();
  for (const [key, value] of Object.entries(values)) {
    lowerValues.set(key.toLowerCase(), value);
  }

  let out = "";
  const length = body.length;
  let i = 0;
  while (i < length) {
    const char = body[i];

    if (char === "\\" && i + 1 < length && (body[i + 1] === "{" || body[i + 1] === "}")) {
      out += body[i + 1];
      i += 2;
      continue;
    }

    if (char === "{") {
      if (i + 1 < length && body[i + 1] === "{") {
        out += "{{";
        i += 2;
        continue;
      }
      const closing = body.indexOf("}", i + 1);
      if (closing !== -1) {
        const inner = body.slice(i + 1, closing);
        if (VARIABLE_NAME_RE.test(inner)) {
          const replacement = lowerValues.get(inner.toLowerCase());
          out += replacement !== undefined ? replacement : `{${inner}}`;
          i = closing + 1;
          continue;
        }
      }
    }

    out += char;
    i += 1;
  }

  return out;
}

export type CaretInsertion = {
  text: string;
  caret: number;
};

/**
 * Insert `insert` into `current` replacing the [selectionStart, selectionEnd)
 * range. Adds a single space on either side only when needed to avoid gluing
 * words together. Returns the new text and the caret position after the
 * inserted content.
 */
export function insertAtSelection(
  current: string,
  selectionStart: number,
  selectionEnd: number,
  insert: string,
): CaretInsertion {
  const start = clamp(selectionStart, 0, current.length);
  const end = clamp(selectionEnd, start, current.length);
  const before = current.slice(0, start);
  const after = current.slice(end);

  const needsLeadingSpace = before.length > 0 && !/\s$/.test(before) && !/^\s/.test(insert);
  const needsTrailingSpace = after.length > 0 && !/^\s/.test(after) && !/\s$/.test(insert);

  const leading = needsLeadingSpace ? " " : "";
  const trailing = needsTrailingSpace ? " " : "";
  const middle = `${leading}${insert}${trailing}`;
  const text = `${before}${middle}${after}`;
  const caret = before.length + leading.length + insert.length;
  return { text, caret };
}

/**
 * Map stored capability hints to composer generation-option ids. `file_upload`
 * has no generation-option counterpart and is dropped here (it surfaces as a
 * separate composer affordance).
 */
export function capabilitiesToGenerationOptions(
  capabilities: readonly SavedPromptCapability[],
): GenerationOptionId[] {
  const result: GenerationOptionId[] = [];
  for (const capability of capabilities) {
    if (isGenerationOptionId(capability) && !result.includes(capability)) {
      result.push(capability);
    }
  }
  return result;
}

function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min;
  return Math.min(Math.max(value, min), max);
}
