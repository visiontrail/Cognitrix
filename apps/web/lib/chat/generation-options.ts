import { BarChart3, Globe, LayoutDashboard, Tags, type LucideIcon } from "lucide-react";

/**
 * Declarative registry for the multi-selectable chart-generation options that
 * live in the chat composer's "+" menu.
 *
 * Each option is an independent, freely combinable toggle. The composer keeps
 * the active set in a `Set<GenerationOptionId>` and renders menu items + chips
 * by mapping over this registry, so adding a new option is a single entry here
 * (plus its i18n keys) — no new state, reset branch, or send wiring required.
 *
 * `payload` declares how a selected option contributes to the send request;
 * `buildGenerationOptionPayload` merges the contributions of the active set.
 */

export type GenerationOptionId = "multi_chart" | "data_labels" | "web_search" | "agent_canvas";

// Visual tone keys; the composer maps these to concrete Tailwind classes.
export type GenerationOptionTone = "blue" | "terracotta";

// What a selected option adds to the chat send request. Mirrors the relevant
// fields of SendMessageRequest without coupling to it.
export type GenerationOptionPayload = {
  generationStrategy?: "multi_chart";
  showDataLabels?: boolean;
  webSearch?: boolean;
  agentCanvas?: boolean;
};

export type GenerationOption = {
  id: GenerationOptionId;
  icon: LucideIcon;
  tone: GenerationOptionTone;
  /** i18n key for the menu row label. */
  menuLabelKey: string;
  /** i18n key for the selected-state chip label. */
  chipLabelKey: string;
  /** i18n key for the chip's remove button aria-label. */
  removeLabelKey: string;
  /** i18n key for the composer hint shown when this is the only option active. */
  hintKey: string;
  payload: GenerationOptionPayload;
};

export const GENERATION_OPTIONS: readonly GenerationOption[] = [
  {
    id: "multi_chart",
    icon: BarChart3,
    tone: "blue",
    menuLabelKey: "chat.actions.multiChart",
    chipLabelKey: "chat.strategy.multiChart",
    removeLabelKey: "chat.strategy.remove",
    hintKey: "chat.inputHintWithMultiChart",
    payload: { generationStrategy: "multi_chart" },
  },
  {
    id: "data_labels",
    icon: Tags,
    tone: "terracotta",
    menuLabelKey: "chat.actions.dataLabels",
    chipLabelKey: "chat.dataLabels.chip",
    removeLabelKey: "chat.dataLabels.remove",
    hintKey: "chat.inputHintWithDataLabels",
    payload: { showDataLabels: true },
  },
  {
    id: "web_search",
    icon: Globe,
    tone: "blue",
    menuLabelKey: "chat.actions.webSearch",
    chipLabelKey: "chat.webSearch.chip",
    removeLabelKey: "chat.webSearch.remove",
    hintKey: "chat.inputHintWithWebSearch",
    payload: { webSearch: true },
  },
  // Only rendered when the backend reports AGENT_CANVAS_MODE_ENABLED=true
  // (the composer filters by capability before mapping over the registry).
  {
    id: "agent_canvas",
    icon: LayoutDashboard,
    tone: "terracotta",
    menuLabelKey: "chat.actions.agentCanvas",
    chipLabelKey: "chat.agentCanvas.chip",
    removeLabelKey: "chat.agentCanvas.remove",
    hintKey: "chat.inputHintWithAgentCanvas",
    payload: { agentCanvas: true },
  },
];

const GENERATION_OPTION_IDS = new Set<string>(GENERATION_OPTIONS.map((option) => option.id));

export function isGenerationOptionId(value: string): value is GenerationOptionId {
  return GENERATION_OPTION_IDS.has(value);
}

/** Toggle an option id within a selection set, returning a new set. */
export function toggleGenerationOption(
  selected: ReadonlySet<GenerationOptionId>,
  id: GenerationOptionId
): Set<GenerationOptionId> {
  const next = new Set(selected);
  if (next.has(id)) {
    next.delete(id);
  } else {
    next.add(id);
  }
  return next;
}

/** The registry entries that are currently active, in registry order. */
export function selectedGenerationOptions(
  selected: ReadonlySet<GenerationOptionId>
): GenerationOption[] {
  return GENERATION_OPTIONS.filter((option) => selected.has(option.id));
}

/** Merge the payload contributions of every active option. */
export function buildGenerationOptionPayload(
  selected: ReadonlySet<GenerationOptionId>
): GenerationOptionPayload {
  let payload: GenerationOptionPayload = {};
  for (const option of GENERATION_OPTIONS) {
    if (selected.has(option.id)) {
      payload = { ...payload, ...option.payload };
    }
  }
  return payload;
}

/**
 * Reverse of `buildGenerationOptionPayload`: recover which option ids were
 * active from the payload fields sent on a turn. Used to surface the user's
 * "+" menu selections in the assistant message's agent-trace summary line.
 *
 * An option matches only when every field of its declared `payload` is present
 * with the same value in `payload` — so an option whose contribution was
 * overridden or absent is not reported.
 */
export function generationOptionIdsFromPayload(
  payload: GenerationOptionPayload
): GenerationOptionId[] {
  return GENERATION_OPTIONS.filter((option) => {
    const entries = Object.entries(option.payload);
    return (
      entries.length > 0 &&
      entries.every(
        ([key, value]) => payload[key as keyof GenerationOptionPayload] === value
      )
    );
  }).map((option) => option.id);
}
