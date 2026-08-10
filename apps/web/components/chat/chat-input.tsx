"use client";

import { useRef, useCallback, useEffect, useMemo, useState } from "react";
import { BookMarked, ChevronRight, FileSpreadsheet, Plus, Send, Square, WandSparkles, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useChatStore } from "@/stores/chat-store";
import { useUIStore } from "@/stores/ui-store";
import { useWorkspaceStore } from "@/stores/workspace-store";
import { stopChatResponse, useConfirmIngestionSetup, useSendMessage } from "@/hooks/use-chat";
import { useBackendCapabilities } from "@/hooks/use-backend-capabilities";
import { useI18n } from "@/lib/i18n/context";
import { useWorkspaceColumns, type ColumnMentionItem } from "@/hooks/use-workspace-columns";
import { cn } from "@/lib/utils";
import {
  findQueryChartType,
  getQueryChartTypeOptions,
  type ChartTypeOption,
  type QueryChartType,
} from "@/lib/charts/chart-type-options";
import {
  MENU_GENERATION_OPTIONS,
  buildGenerationOptionPayload,
  findGenerationOption,
  selectedGenerationOptions,
  toggleGenerationOption,
  type GenerationOptionId,
  type GenerationOptionTone,
} from "@/lib/chat/generation-options";
import type { IngestionCatalogSetupSeed, IngestionProposalAction, IngestionTimeGrain } from "@/types/ingestion";
import { IngestionSetupCard } from "@/components/workspace/ingestion-setup-card";
import { SavedPromptEditorDialog } from "@/components/chat/saved-prompts/saved-prompt-editor-dialog";
import { SavedPromptVariableDialog } from "@/components/chat/saved-prompts/saved-prompt-variable-dialog";
import { SavedPromptsManager } from "@/components/chat/saved-prompts/saved-prompts-manager";
import { useMarkSavedPromptUsed, useSavedPrompts } from "@/hooks/use-saved-prompts";
import { capabilitiesToGenerationOptions, insertAtSelection } from "@/lib/saved-prompts/template";
import type { SavedPrompt } from "@/lib/saved-prompts/types";
import { ALLOWED_ATTACHMENT_EXTENSIONS, selectChatAttachment } from "@/lib/chat/attachment";
import { ChartPreview } from "@/components/charts/chart-preview";

// Concrete Tailwind classes per generation-option tone. Kept as full literal
// strings (not interpolated) so the JIT compiler always emits them.
const OPTION_TONE_CHIP: Record<GenerationOptionTone, { container: string; remove: string }> = {
  blue: {
    container: "border-focus-blue/30 bg-focus-blue/10 text-focus-blue",
    remove: "text-focus-blue/75 hover:text-focus-blue",
  },
  terracotta: {
    container: "border-terracotta/30 bg-terracotta/10 text-terracotta",
    remove: "text-terracotta/75 hover:text-terracotta",
  },
};

const OPTION_TONE_MENU_ACTIVE: Record<GenerationOptionTone, string> = {
  blue: "bg-focus-blue/10 text-focus-blue",
  terracotta: "bg-terracotta/10 text-terracotta",
};

export function ChatInput({ sessionId }: { sessionId: string }) {
  const { locale, t } = useI18n();
  const composerText = useChatStore((s) => s.composerText);
  const setComposerText = useChatStore((s) => s.setComposerText);
  const pendingApproval = useChatStore((s) => s.pendingIngestionBySession[sessionId]);
  const pendingSetup = useChatStore((s) => s.pendingIngestionSetupBySession[sessionId]);
  const clearPendingSetup = useChatStore((s) => s.clearPendingIngestionSetup);
  const isSending = useUIStore((s) => Boolean(s.sendingBySession[sessionId]));
  const activeWorkspaceId = useWorkspaceStore((s) => s.activeWorkspaceId);
  const chartEditTarget = useUIStore((s) =>
    s.chartEditTarget?.sessionId === sessionId &&
    s.chartEditTarget.workspaceId === activeWorkspaceId
      ? s.chartEditTarget
      : null
  );
  const clearChartEditTarget = useUIStore((s) => s.clearChartEditTarget);
  const sendMessage = useSendMessage();
  const confirmSetup = useConfirmIngestionSetup();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const actionMenuRef = useRef<HTMLDivElement>(null);
  // Attachment lives in the store so the panel-wide drop zone and this chip
  // describe the same single pending workbook.
  const selectedFile = useChatStore((s) => s.composerAttachment);
  const setSelectedFile = useChatStore((s) => s.setComposerAttachment);
  const [customApprovalInput, setCustomApprovalInput] = useState(false);
  const [selectedChartType, setSelectedChartType] = useState<QueryChartType | null>(null);
  const [selectedOptions, setSelectedOptions] = useState<Set<GenerationOptionId>>(() => new Set());
  const [actionMenuOpen, setActionMenuOpen] = useState(false);
  const [chartTrigger, setChartTrigger] = useState<ChartTriggerState | null>(null);
  const [activeChartIndex, setActiveChartIndex] = useState(0);
  const [columnTrigger, setColumnTrigger] = useState<ColumnTriggerState | null>(null);
  const [activeColumnIndex, setActiveColumnIndex] = useState(0);
  // Saved prompts: submenu + dialog state. Insertion captures the live
  // textarea selection so opening the menu never loses the user's caret.
  const [savedPromptsSubmenuOpen, setSavedPromptsSubmenuOpen] = useState(false);
  const [editorState, setEditorState] = useState<{ open: boolean; prompt: SavedPrompt | null }>({
    open: false,
    prompt: null,
  });
  const [managerOpen, setManagerOpen] = useState(false);
  const [variablePrompt, setVariablePrompt] = useState<SavedPrompt | null>(null);
  const composerSelectionRef = useRef<{ start: number; end: number } | null>(null);
  const markPromptUsed = useMarkSavedPromptUsed();
  const recentPromptsQuery = useSavedPrompts({ limit: 5 }, actionMenuOpen && savedPromptsSubmenuOpen);
  const recentPrompts = recentPromptsQuery.data ?? [];
  const chartOptions = useMemo(() => getQueryChartTypeOptions(locale), [locale]);
  const capabilities = useBackendCapabilities();
  const activeOptions = useMemo(() => selectedGenerationOptions(selectedOptions), [selectedOptions]);
  // Agent mode is a sticky per-conversation mode, not a per-message option: it
  // lives in the chat store keyed by session, survives sends and reloads, and
  // is flipped only by its own switch. Offered only when the backend reports
  // the feature flag; a disabled deployment renders no switch at all.
  const agentModeAvailable = capabilities.agentCanvasModeEnabled;
  const agentMode = useChatStore((s) => s.agentModeBySession[sessionId] === true) && agentModeAvailable;
  const setAgentMode = useChatStore((s) => s.setAgentMode);
  const agentOption = findGenerationOption("agent_canvas");
  const columns = useWorkspaceColumns(activeWorkspaceId);
  const approvalOptions = useMemo(
    () => collectPendingApprovalOptions(pendingApproval?.plan.humanApproval.options),
    [pendingApproval]
  );
  const inputLockedByApproval = (Boolean(pendingApproval) || Boolean(pendingSetup)) && !customApprovalInput;
  const filteredChartOptions = useMemo(
    () => filterChartOptions(chartOptions, chartTrigger?.query ?? ""),
    [chartOptions, chartTrigger?.query]
  );
  const filteredColumns = useMemo(
    () => filterColumnOptions(columns, columnTrigger?.query ?? ""),
    [columns, columnTrigger?.query]
  );
  const activeChartOption = filteredChartOptions[Math.min(activeChartIndex, filteredChartOptions.length - 1)] ?? null;

  useEffect(() => {
    if (pendingApproval || pendingSetup) {
      setSelectedFile(null);
      setSelectedOptions(new Set());
      setActionMenuOpen(false);
      setChartTrigger(null);
      setColumnTrigger(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      return;
    }
    setCustomApprovalInput(false);
  }, [pendingApproval, pendingSetup, setSelectedFile]);

  // The attachment is store-level (shared with the panel drop zone), so drop it
  // when the user switches conversations instead of silently carrying a workbook
  // into a different session. Panel switches keep it (the session is unchanged).
  const lastSessionIdRef = useRef(sessionId);
  useEffect(() => {
    if (lastSessionIdRef.current === sessionId) return;
    lastSessionIdRef.current = sessionId;
    setSelectedFile(null);
  }, [sessionId, setSelectedFile]);

  useEffect(() => {
    if (!chartEditTarget) return;
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, [chartEditTarget]);

  useEffect(() => {
    if (!actionMenuOpen) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && actionMenuRef.current?.contains(target)) {
        return;
      }
      setActionMenuOpen(false);
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [actionMenuOpen]);

  useEffect(() => {
    if (!actionMenuOpen) {
      setSavedPromptsSubmenuOpen(false);
    }
  }, [actionMenuOpen]);

  useEffect(() => {
    if (activeChartIndex >= filteredChartOptions.length) {
      setActiveChartIndex(0);
    }
  }, [activeChartIndex, filteredChartOptions.length]);

  useEffect(() => {
    if (activeColumnIndex >= filteredColumns.length) {
      setActiveColumnIndex(0);
    }
  }, [activeColumnIndex, filteredColumns.length]);

  const handleSubmit = useCallback(() => {
    const content = composerText.trim();
    if ((!content && !selectedFile) || isSending || inputLockedByApproval) return;
    const chartType = resolveSelectedChartType({
      explicitSelection: selectedChartType,
      text: content,
    });

    sendMessage.mutate({
      sessionId,
      content,
      attachment: selectedFile ?? undefined,
      preferredChartType: chartType ?? undefined,
      ...buildGenerationOptionPayload(selectedOptions),
      // Sticky mode: carried by every turn of this conversation, and
      // deliberately not reset below with the per-message selections.
      agentCanvas: agentMode,
      chartEditTarget: chartEditTarget ?? undefined,
    });
    setComposerText("");
    setSelectedChartType(null);
    setSelectedOptions(new Set());
    setActionMenuOpen(false);
    setChartTrigger(null);
    setColumnTrigger(null);
    setSelectedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }

    requestAnimationFrame(() => {
      textareaRef.current?.focus();
    });
  }, [
    agentMode,
    composerText,
    inputLockedByApproval,
    isSending,
    selectedChartType,
    selectedOptions,
    selectedFile,
    chartEditTarget,
    sendMessage,
    sessionId,
    setComposerText,
    setSelectedFile,
  ]);

  const handleStop = useCallback(() => {
    stopChatResponse(sessionId);
  }, [sessionId]);

  const handleApprovalOption = useCallback(
    (approvedAction: IngestionProposalAction) => {
      if (!pendingApproval || isSending) {
        return;
      }
      const label = formatApprovalActionLabel({
        action: approvedAction,
        timeGrain: pendingApproval.plan.proposal.timeGrain,
        t,
      });
      sendMessage.mutate({
        sessionId,
        content: label,
        approvedAction,
      });
      setComposerText("");
      setSelectedChartType(null);
      setSelectedOptions(new Set());
      setActionMenuOpen(false);
      setChartTrigger(null);
      setColumnTrigger(null);
      setCustomApprovalInput(false);
      requestAnimationFrame(() => {
        textareaRef.current?.focus();
      });
    },
    [isSending, pendingApproval, sendMessage, sessionId, setComposerText, t]
  );

  const updateTriggers = useCallback(
    (text: string, caretPosition: number | null) => {
      const pos = caretPosition ?? text.length;
      // Chart trigger
      const nextChartTrigger = getChartTriggerState(text, pos);
      setChartTrigger(nextChartTrigger);
      setActiveChartIndex(0);
      setSelectedChartType((current) => {
        if (!current) return null;
        return text.includes(`#${current}`) ? current : null;
      });
      // Column trigger — only active when chart trigger is inactive
      const nextColumnTrigger = nextChartTrigger ? null : getColumnTriggerState(text, pos);
      setColumnTrigger(nextColumnTrigger);
      setActiveColumnIndex(0);
    },
    []
  );

  const applyChartSelection = useCallback(
    (option: ChartTypeOption) => {
      const trigger = chartTrigger ?? getChartTriggerState(composerText, textareaRef.current?.selectionStart ?? composerText.length);
      if (!trigger) {
        setSelectedChartType(option.type);
        setChartTrigger(null);
        return;
      }

      const before = composerText.slice(0, trigger.start);
      const after = composerText.slice(trigger.end);
      const replacement = `#${option.type} `;
      const nextText = `${before}${replacement}${after}`;
      const nextCaret = before.length + replacement.length;
      setComposerText(nextText);
      setSelectedChartType(option.type);
      setChartTrigger(null);
      requestAnimationFrame(() => {
        if (!textareaRef.current) return;
        textareaRef.current.focus();
        textareaRef.current.setSelectionRange(nextCaret, nextCaret);
      });
    },
    [chartTrigger, composerText, setComposerText]
  );

  const applyColumnSelection = useCallback(
    (item: ColumnMentionItem) => {
      const trigger =
        columnTrigger ??
        getColumnTriggerState(composerText, textareaRef.current?.selectionStart ?? composerText.length);
      if (!trigger) return;

      const before = composerText.slice(0, trigger.start);
      const after = composerText.slice(trigger.end);
      const replacement = `@${item.columnName} `;
      const nextText = `${before}${replacement}${after}`;
      const nextCaret = before.length + replacement.length;
      setComposerText(nextText);
      setColumnTrigger(null);
      requestAnimationFrame(() => {
        if (!textareaRef.current) return;
        textareaRef.current.focus();
        textareaRef.current.setSelectionRange(nextCaret, nextCaret);
      });
    },
    [columnTrigger, composerText, setComposerText]
  );

  const rememberSelection = useCallback((target: HTMLTextAreaElement) => {
    composerSelectionRef.current = {
      start: target.selectionStart ?? target.value.length,
      end: target.selectionEnd ?? target.value.length,
    };
  }, []);

  // Insert rendered prompt text at the captured caret/selection without
  // auto-sending; preserves the surrounding draft and restores focus.
  const insertPromptText = useCallback(
    (text: string) => {
      const selection = composerSelectionRef.current ?? {
        start: composerText.length,
        end: composerText.length,
      };
      const { text: nextText, caret } = insertAtSelection(
        composerText,
        selection.start,
        selection.end,
        text,
      );
      setComposerText(nextText);
      composerSelectionRef.current = { start: caret, end: caret };
      requestAnimationFrame(() => {
        if (!textareaRef.current) return;
        textareaRef.current.focus();
        textareaRef.current.setSelectionRange(caret, caret);
      });
    },
    [composerText, setComposerText],
  );

  const applyPrompt = useCallback(
    (prompt: SavedPrompt) => {
      setActionMenuOpen(false);
      setSavedPromptsSubmenuOpen(false);
      // Preselect any generation options the prompt hints at; hints never make
      // a backend call beyond mark-used and never auto-send. A hint at a sticky
      // mode turns the mode on rather than joining the per-message set.
      const optionIds = capabilitiesToGenerationOptions(prompt.capabilities);
      const menuOptionIds = optionIds.filter(
        (id) => findGenerationOption(id)?.placement !== "composer"
      );
      if (menuOptionIds.length > 0) {
        setSelectedOptions((current) => {
          const next = new Set(current);
          for (const id of menuOptionIds) next.add(id);
          return next;
        });
      }
      if (optionIds.includes("agent_canvas") && agentModeAvailable) {
        setAgentMode(sessionId, true);
      }
      if (prompt.variables.length > 0) {
        setVariablePrompt(prompt);
        return;
      }
      insertPromptText(prompt.body);
      markPromptUsed.mutate(prompt.id);
    },
    [agentModeAvailable, insertPromptText, markPromptUsed, sessionId, setAgentMode],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (columnTrigger && filteredColumns.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setActiveColumnIndex((current) => (current + 1) % filteredColumns.length);
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setActiveColumnIndex((current) =>
            current === 0 ? filteredColumns.length - 1 : current - 1
          );
          return;
        }
        if (e.key === "Enter" || e.key === "Tab") {
          e.preventDefault();
          applyColumnSelection(filteredColumns[activeColumnIndex] ?? filteredColumns[0]);
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          setColumnTrigger(null);
          return;
        }
      }
      if (chartTrigger && filteredChartOptions.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setActiveChartIndex((current) => (current + 1) % filteredChartOptions.length);
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setActiveChartIndex((current) =>
            current === 0 ? filteredChartOptions.length - 1 : current - 1
          );
          return;
        }
        if (e.key === "Enter" || e.key === "Tab") {
          e.preventDefault();
          applyChartSelection(filteredChartOptions[activeChartIndex] ?? filteredChartOptions[0]);
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          setChartTrigger(null);
          return;
        }
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [
      activeChartIndex,
      activeColumnIndex,
      applyChartSelection,
      applyColumnSelection,
      chartTrigger,
      columnTrigger,
      filteredChartOptions,
      filteredColumns,
      handleSubmit,
    ]
  );

  return (
    <div className="border-t border-border-cream bg-ivory px-4 py-3 shrink-0">
      <div className="max-w-4xl mx-auto space-y-2">
        {chartEditTarget ? (
          <section
            data-testid="chart-edit-context"
            aria-label={t("chat.chartEdit.contextAria", { title: chartEditTarget.title })}
            className="relative overflow-hidden rounded-comfortable border border-terracotta/30 bg-[linear-gradient(120deg,rgba(201,100,66,0.10),rgba(245,240,232,0.78))] shadow-[0_10px_28px_rgba(80,58,41,0.08)]"
          >
            <div className="grid min-h-[116px] grid-cols-[minmax(132px,0.8fr)_minmax(0,1.2fr)_auto] items-stretch">
              <div className="overflow-hidden border-r border-terracotta/15 bg-parchment/80 p-1">
                <ChartPreview spec={chartEditTarget.spec} height={108} />
              </div>
              <div className="flex min-w-0 flex-col justify-center gap-1 px-3 py-2.5">
                <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-terracotta">
                  <WandSparkles className="h-3.5 w-3.5" />
                  {t("chat.chartEdit.badge")}
                </p>
                <p className="truncate text-body-sm font-semibold text-near-black" title={chartEditTarget.title}>
                  {chartEditTarget.title}
                </p>
                <p className="text-caption text-stone-gray">
                  {t("chat.chartEdit.instruction", { chartType: chartEditTarget.chartType })}
                </p>
              </div>
              <button
                type="button"
                className="m-2 self-start rounded-full p-1 text-stone-gray transition-colors hover:bg-ivory/80 hover:text-near-black focus:outline-none focus-visible:ring-2 focus-visible:ring-terracotta"
                onClick={() => clearChartEditTarget(chartEditTarget.nodeId)}
                aria-label={t("chat.chartEdit.remove", { title: chartEditTarget.title })}
                disabled={isSending}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </section>
        ) : null}

        {pendingSetup ? (
          <IngestionSetupCard
            initialSeed={pendingSetup.plan.suggestedCatalogSeed}
            setupQuestions={pendingSetup.plan.setupQuestions}
            agentConfidence={pendingSetup.plan.agentGuess.confidence}
            isSubmitting={isSending}
            onConfirm={(seed: IngestionCatalogSetupSeed) => {
              confirmSetup.mutate({ sessionId, seed });
            }}
            onCancel={() => clearPendingSetup(sessionId)}
          />
        ) : pendingApproval ? (
          <div className="rounded-comfortable border border-border-cream bg-amber-50 px-3 py-3">
            {pendingApproval.plan.proposals.length > 1 ? (
              <p className="mb-1 text-caption text-stone-gray">
                {`Proposal 1 of ${pendingApproval.plan.proposals.length}`}
                {pendingApproval.plan.proposal.targetTable
                  ? ` · ${pendingApproval.plan.proposal.targetTable}`
                  : ""}
              </p>
            ) : null}
            <p className="text-body-sm font-medium text-near-black">
              {pendingApproval.plan.humanApproval.question || t("chat.ingestion.approvalOptionsTitle")}
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {approvalOptions.map((option) => {
                const isRecommended = pendingApproval.plan.humanApproval.recommendedOption === option;
                return (
                  <Button
                    key={option}
                    type="button"
                    size="sm"
                    variant={isRecommended ? "default" : "outline"}
                    onClick={() => handleApprovalOption(option)}
                    disabled={isSending}
                  >
                    {formatApprovalActionLabel({
                      action: option,
                      timeGrain: pendingApproval.plan.proposal.timeGrain,
                      t,
                    })}
                    {isRecommended ? ` · ${t("chat.ingestion.awaitingApprovalRecommendedTag")}` : ""}
                  </Button>
                );
              })}
              <Button
                type="button"
                size="sm"
                variant={customApprovalInput ? "default" : "outline"}
                onClick={() => {
                  setCustomApprovalInput(true);
                  requestAnimationFrame(() => textareaRef.current?.focus());
                }}
                disabled={isSending}
              >
                {t("chat.ingestion.approvalCustomInput")}
              </Button>
            </div>
            <p className="pt-2 text-caption text-stone-gray">
              {customApprovalInput
                ? t("chat.ingestion.approvalCustomInputHint")
                : t("chat.ingestion.approvalQuickPickHint")}
            </p>
          </div>
        ) : null}

        {selectedFile || activeOptions.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            {selectedFile ? (
              <div className="inline-flex max-w-full items-center gap-2 rounded-full border border-border-cream bg-parchment px-3 py-1 text-caption text-near-black">
                <FileSpreadsheet className="h-3.5 w-3.5 shrink-0 text-stone-gray" />
                <span className="truncate" title={selectedFile.name}>
                  {t("chat.fileAttached", { fileName: selectedFile.name })}
                </span>
                <button
                  type="button"
                  className="rounded-full p-0.5 text-stone-gray hover:text-near-black"
                  onClick={() => {
                    setSelectedFile(null);
                    if (fileInputRef.current) {
                      fileInputRef.current.value = "";
                    }
                  }}
                  aria-label={t("chat.removeFile")}
                  disabled={isSending}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ) : null}
            {activeOptions.map((option) => {
              const Icon = option.icon;
              const tone = OPTION_TONE_CHIP[option.tone];
              return (
                <div
                  key={option.id}
                  className={cn(
                    "inline-flex max-w-full items-center gap-2 rounded-full border px-3 py-1 text-caption font-medium",
                    tone.container
                  )}
                >
                  <Icon className="h-3.5 w-3.5 shrink-0" />
                  <span>{t(option.chipLabelKey)}</span>
                  <button
                    type="button"
                    className={cn("rounded-full p-0.5", tone.remove)}
                    onClick={() => setSelectedOptions((current) => toggleGenerationOption(current, option.id))}
                    aria-label={t(option.removeLabelKey)}
                    disabled={isSending}
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
          </div>
        ) : null}

        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept={`${ALLOWED_ATTACHMENT_EXTENSIONS.join(",")},application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`}
            className="hidden"
            onChange={(event) => {
              // Same rules as the drop zone: one workbook, .xlsx, within size cap.
              const { file, notice } = selectChatAttachment(Array.from(event.target.files ?? []));
              if (notice) {
                const message = t(notice.key, notice.params);
                if (notice.level === "error") {
                  toast.error(message);
                } else {
                  toast.warning(message);
                }
              }
              if (file) {
                setSelectedFile(file);
              }
              // Allow re-picking the same file after a rejection.
              event.target.value = "";
            }}
            disabled={isSending}
          />

          <div ref={actionMenuRef} className="relative shrink-0 self-center">
            <Button
              type="button"
              variant={actionMenuOpen ? "secondary" : "outline"}
              size="icon-sm"
              className={cn(
                "h-[44px] w-[44px] rounded-full transition-transform",
                actionMenuOpen && "rotate-45"
              )}
              onClick={() => setActionMenuOpen((open) => !open)}
              disabled={isSending || Boolean(pendingApproval) || Boolean(pendingSetup)}
              aria-label={t("chat.actions.open")}
              aria-haspopup="menu"
              aria-expanded={actionMenuOpen}
            >
              <Plus className="h-5 w-5" />
            </Button>
            {actionMenuOpen ? (
              <div
                role="menu"
                aria-label={t("chat.actions.menuLabel")}
                className="absolute bottom-[52px] left-0 z-30 w-64 rounded-comfortable border border-border-cream bg-ivory p-1.5 shadow-xl"
              >
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full items-center gap-3 rounded-comfortable px-3 py-2 text-left text-body-sm text-near-black hover:bg-parchment focus:bg-parchment focus:outline-none"
                  onClick={() => {
                    setActionMenuOpen(false);
                    fileInputRef.current?.click();
                  }}
                >
                  <FileSpreadsheet className="h-4 w-4 shrink-0 text-stone-gray" />
                  <span>{t("chat.actions.attachFile")}</span>
                </button>
                {MENU_GENERATION_OPTIONS.map((option) => {
                  const Icon = option.icon;
                  const checked = selectedOptions.has(option.id);
                  return (
                    <button
                      key={option.id}
                      type="button"
                      role="menuitemcheckbox"
                      aria-checked={checked}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-comfortable px-3 py-2 text-left text-body-sm focus:outline-none",
                        checked
                          ? OPTION_TONE_MENU_ACTIVE[option.tone]
                          : "text-near-black hover:bg-parchment focus:bg-parchment"
                      )}
                      onClick={() => {
                        setSelectedOptions((current) => toggleGenerationOption(current, option.id));
                        setActionMenuOpen(false);
                      }}
                    >
                      <Icon className="h-4 w-4 shrink-0" />
                      <span>{t(option.menuLabelKey)}</span>
                    </button>
                  );
                })}

                <div className="my-1 h-px bg-border-cream" />

                <div className="relative">
                  <button
                    type="button"
                    role="menuitem"
                    aria-haspopup="menu"
                    aria-expanded={savedPromptsSubmenuOpen}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-comfortable px-3 py-2 text-left text-body-sm text-near-black hover:bg-parchment focus:bg-parchment focus:outline-none",
                      savedPromptsSubmenuOpen && "bg-parchment"
                    )}
                    onClick={() => setSavedPromptsSubmenuOpen((open) => !open)}
                  >
                    <BookMarked className="h-4 w-4 shrink-0 text-stone-gray" />
                    <span className="flex-1">{t("savedPrompts.menu.label")}</span>
                    <ChevronRight className="h-4 w-4 shrink-0 text-stone-gray" />
                  </button>

                  {savedPromptsSubmenuOpen ? (
                    <div
                      role="menu"
                      aria-label={t("savedPrompts.menu.submenuLabel")}
                      className="absolute bottom-0 left-[calc(100%+0.5rem)] z-40 max-h-[min(24rem,calc(100vh-2rem))] w-64 overflow-y-auto rounded-comfortable border border-border-cream bg-ivory p-1.5 shadow-xl"
                    >
                      <button
                        type="button"
                        role="menuitem"
                        className="flex w-full items-center gap-3 rounded-comfortable px-3 py-2 text-left text-body-sm text-near-black hover:bg-parchment focus:bg-parchment focus:outline-none"
                        onClick={() => {
                          setActionMenuOpen(false);
                          setEditorState({ open: true, prompt: null });
                        }}
                      >
                        <Plus className="h-4 w-4 shrink-0 text-stone-gray" />
                        <span>{t("savedPrompts.menu.create")}</span>
                      </button>
                      <button
                        type="button"
                        role="menuitem"
                        className="flex w-full items-center gap-3 rounded-comfortable px-3 py-2 text-left text-body-sm text-near-black hover:bg-parchment focus:bg-parchment focus:outline-none"
                        onClick={() => {
                          setActionMenuOpen(false);
                          setManagerOpen(true);
                        }}
                      >
                        <BookMarked className="h-4 w-4 shrink-0 text-stone-gray" />
                        <span>{t("savedPrompts.menu.manage")}</span>
                      </button>

                      {recentPromptsQuery.isLoading ? (
                        <p className="px-3 py-2 text-caption text-stone-gray">
                          {t("savedPrompts.menu.loading")}
                        </p>
                      ) : recentPrompts.length === 0 ? (
                        <p className="px-3 py-2 text-caption text-stone-gray">
                          {t("savedPrompts.menu.empty")}
                        </p>
                      ) : (
                        <>
                          <p className="px-3 pt-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-stone-gray">
                            {t("savedPrompts.menu.recentLabel")}
                          </p>
                          {recentPrompts.map((prompt) => (
                            <button
                              key={prompt.id}
                              type="button"
                              role="menuitem"
                              aria-label={t("savedPrompts.menu.insertAria", { name: prompt.name })}
                              className="flex w-full items-center gap-2 rounded-comfortable px-3 py-1.5 text-left text-body-sm text-near-black hover:bg-parchment focus:bg-parchment focus:outline-none"
                              onClick={() => applyPrompt(prompt)}
                            >
                              <span className="truncate">{prompt.name}</span>
                            </button>
                          ))}
                        </>
                      )}
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>

          {agentModeAvailable && agentOption ? (
            <button
              type="button"
              role="switch"
              aria-checked={agentMode}
              data-testid="agent-mode-toggle"
              aria-label={t("chat.agentCanvas.toggleAriaLabel")}
              title={t(agentMode ? "chat.agentCanvas.toggleOnTitle" : "chat.agentCanvas.toggleOffTitle")}
              onClick={() => setAgentMode(sessionId, !agentMode)}
              disabled={isSending || Boolean(pendingApproval) || Boolean(pendingSetup)}
              className={cn(
                "inline-flex h-[44px] shrink-0 select-none items-center gap-2 self-center rounded-full border px-2 sm:px-3",
                "transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-focus-blue",
                "disabled:cursor-not-allowed disabled:opacity-50",
                agentMode
                  ? "border-terracotta/40 bg-terracotta/10 text-terracotta shadow-[0_0_0_3px_rgba(201,100,66,0.08)]"
                  : "border-border-cream bg-parchment text-stone-gray hover:border-terracotta/30 hover:text-near-black"
              )}
            >
              <agentOption.icon className="h-4 w-4 shrink-0" />
              <span className="hidden text-caption font-medium sm:inline">
                {t("chat.agentCanvas.toggleLabel")}
              </span>
              <span
                aria-hidden="true"
                className={cn(
                  "relative h-[14px] w-[26px] shrink-0 rounded-full transition-colors duration-200",
                  agentMode ? "bg-terracotta" : "bg-border-cream"
                )}
              >
                <span
                  className={cn(
                    "absolute top-[2px] h-[10px] w-[10px] rounded-full bg-ivory transition-all duration-200",
                    agentMode ? "left-[14px]" : "left-[2px]"
                  )}
                />
              </span>
            </button>
          ) : null}

          <div className="relative flex-1">
            <textarea
              ref={textareaRef}
              data-chat-composer="true"
              value={composerText}
              aria-label={t("chat.inputAriaLabel")}
              aria-autocomplete="list"
              aria-controls={columnTrigger ? "column-mention-picker" : "chart-type-picker"}
              aria-activedescendant={
                columnTrigger
                  ? (filteredColumns[activeColumnIndex] ? `column-mention-option-${filteredColumns[activeColumnIndex].id}` : undefined)
                  : (activeChartOption ? `chart-type-option-${activeChartOption.type}` : undefined)
              }
              onChange={(e) => {
                setComposerText(e.target.value);
                updateTriggers(e.target.value, e.target.selectionStart);
              }}
              onKeyDown={handleKeyDown}
              onClick={(e) => {
                const target = e.currentTarget;
                updateTriggers(target.value, target.selectionStart);
              }}
              onFocus={(e) => {
                const target = e.currentTarget;
                updateTriggers(target.value, target.selectionStart);
                rememberSelection(target);
              }}
              onSelect={(e) => rememberSelection(e.currentTarget)}
              placeholder={
                inputLockedByApproval
                  ? t("chat.ingestion.approvalInputLocked")
                  : chartEditTarget
                    ? t("chat.chartEdit.placeholder")
                  : agentMode
                    ? t("chat.agentCanvas.placeholder")
                    : t("chat.inputPlaceholder")
              }
              rows={1}
              disabled={isSending || inputLockedByApproval}
              className={cn(
                "w-full resize-none rounded-generous border bg-parchment px-4 py-2 text-body-sm text-near-black placeholder:text-stone-gray focus:outline-none focus:ring-2 transition-colors disabled:opacity-50 min-h-[44px] max-h-[160px] scrollbar-thin",
                // While the conversation is in Agent mode the composer carries
                // the mode's accent, so the state is legible even mid-typing.
                agentMode
                  ? "border-terracotta/40 focus:border-terracotta focus:ring-terracotta/40"
                  : "border-border-cream focus:ring-focus-blue focus:border-focus-blue"
              )}
              style={{
                height: "44px",
                minHeight: "44px",
              }}
              onInput={(e) => {
                const target = e.target as HTMLTextAreaElement;
                target.style.height = "44px";
                target.style.height = Math.min(target.scrollHeight, 160) + "px";
              }}
            />

            {columnTrigger ? (
              <ColumnMentionPicker
                items={filteredColumns}
                activeIndex={activeColumnIndex}
                onActiveIndexChange={setActiveColumnIndex}
                onSelect={applyColumnSelection}
                t={t}
              />
            ) : chartTrigger && filteredChartOptions.length > 0 ? (
              <ChartTypePicker
                options={filteredChartOptions}
                activeIndex={activeChartIndex}
                onActiveIndexChange={setActiveChartIndex}
                onSelect={applyChartSelection}
                t={t}
              />
            ) : null}
          </div>

          <Button
            size="default"
            variant={isSending ? "secondary" : "default"}
            onClick={isSending ? handleStop : handleSubmit}
            disabled={isSending ? false : (!composerText.trim() && !selectedFile) || inputLockedByApproval}
            className="shrink-0 h-[44px] w-[44px] rounded-generous p-0 self-center"
            aria-label={isSending ? t("chat.stop") : t("chat.send")}
          >
            {isSending ? (
              <Square className="w-4 h-4 fill-current" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </Button>
        </div>
      </div>

      <p className="text-label text-stone-gray text-center mt-2">
        {chartEditTarget
          ? t("chat.chartEdit.hint")
          : agentMode
          ? t("chat.inputHintWithAgentCanvas")
          : activeOptions.length > 1
          ? t("chat.inputHintWithOptions", { count: activeOptions.length })
          : activeOptions.length === 1
          ? t(activeOptions[0].hintKey)
          : selectedChartType
          ? t("chat.inputHintWithChartType", { chartType: selectedChartType })
          : t("chat.inputHintWithAttachment")}
      </p>

      <SavedPromptEditorDialog
        open={editorState.open}
        prompt={editorState.prompt}
        onOpenChange={(open) => setEditorState((current) => ({ ...current, open }))}
      />
      <SavedPromptsManager
        open={managerOpen}
        onOpenChange={setManagerOpen}
        onCreate={() => {
          setManagerOpen(false);
          setEditorState({ open: true, prompt: null });
        }}
        onEdit={(prompt) => {
          setManagerOpen(false);
          setEditorState({ open: true, prompt });
        }}
        onInsert={(prompt) => {
          setManagerOpen(false);
          applyPrompt(prompt);
        }}
      />
      <SavedPromptVariableDialog
        prompt={variablePrompt}
        open={Boolean(variablePrompt)}
        onOpenChange={(open) => {
          if (!open) setVariablePrompt(null);
        }}
        onConfirm={(renderedText) => {
          insertPromptText(renderedText);
          if (variablePrompt) markPromptUsed.mutate(variablePrompt.id);
        }}
      />
    </div>
  );
}

// ─── Trigger state types ───────────────────────────────────────────────────

type ChartTriggerState = {
  start: number;
  end: number;
  query: string;
};

type ColumnTriggerState = {
  start: number;
  end: number;
  query: string;
};

// ─── Trigger detection ─────────────────────────────────────────────────────

function getChartTriggerState(text: string, caretPosition: number): ChartTriggerState | null {
  const beforeCaret = text.slice(0, caretPosition);
  const triggerStart = beforeCaret.lastIndexOf("#");
  if (triggerStart < 0) return null;
  const previousChar = triggerStart === 0 ? "" : beforeCaret[triggerStart - 1];
  if (previousChar && !/\s/.test(previousChar)) return null;
  const query = beforeCaret.slice(triggerStart + 1);
  if (/\s/.test(query)) return null;
  return {
    start: triggerStart,
    end: caretPosition,
    query,
  };
}

function getColumnTriggerState(text: string, caretPosition: number): ColumnTriggerState | null {
  const beforeCaret = text.slice(0, caretPosition);
  const triggerStart = beforeCaret.lastIndexOf("@");
  if (triggerStart < 0) return null;
  const previousChar = triggerStart === 0 ? "" : beforeCaret[triggerStart - 1];
  if (previousChar && !/\s/.test(previousChar)) return null;
  const query = beforeCaret.slice(triggerStart + 1);
  if (/\s/.test(query)) return null;
  return {
    start: triggerStart,
    end: caretPosition,
    query,
  };
}

// ─── Filter helpers ────────────────────────────────────────────────────────

function filterChartOptions(options: ChartTypeOption[], query: string): ChartTypeOption[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return options;
  }
  return options.filter((option) => {
    const haystack = `${option.type} ${option.label} ${option.description} ${option.group}`.toLowerCase();
    return haystack.includes(normalized);
  });
}

function filterColumnOptions(items: ColumnMentionItem[], query: string): ColumnMentionItem[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return items;
  return items.filter((item) => {
    const haystack =
      `${item.columnName} ${item.columnLabel} ${item.tableName} ${item.tableLabel}`.toLowerCase();
    return haystack.includes(normalized);
  });
}

// ─── Chart type resolution ─────────────────────────────────────────────────

function resolveSelectedChartType({
  explicitSelection,
  text,
}: {
  explicitSelection: QueryChartType | null;
  text: string;
}): QueryChartType | null {
  if (explicitSelection && text.includes(`#${explicitSelection}`)) {
    return explicitSelection;
  }
  const match = text.match(/(?:^|\s)#([A-Za-z_]+)/);
  return match ? findQueryChartType(match[1]) : null;
}

// ─── ColumnMentionPicker ───────────────────────────────────────────────────

function ColumnMentionPicker({
  items,
  activeIndex,
  onActiveIndexChange,
  onSelect,
  t,
}: {
  items: ColumnMentionItem[];
  activeIndex: number;
  onActiveIndexChange: (index: number) => void;
  onSelect: (item: ColumnMentionItem) => void;
  t: (key: string, params?: Record<string, string | number | null | undefined>) => string;
}) {
  const boundedActiveIndex = Math.min(activeIndex, Math.max(items.length - 1, 0));
  const listRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    const list = listRef.current;
    const activeElement = itemRefs.current[boundedActiveIndex];
    if (!list || !activeElement) return;

    const itemTop = activeElement.offsetTop;
    const itemBottom = itemTop + activeElement.offsetHeight;
    const visibleTop = list.scrollTop;
    const visibleBottom = visibleTop + list.clientHeight;

    if (itemTop < visibleTop) {
      list.scrollTo({ top: itemTop, behavior: "smooth" });
      return;
    }
    if (itemBottom > visibleBottom) {
      list.scrollTo({ top: itemBottom - list.clientHeight, behavior: "smooth" });
    }
  }, [boundedActiveIndex, items.length]);

  return (
    <div
      id="column-mention-picker"
      role="listbox"
      aria-label={t("chat.columnMentionPicker.ariaLabel")}
      className="absolute bottom-[calc(100%+8px)] left-0 z-30 w-full max-w-[520px] overflow-hidden rounded-comfortable border border-border-cream bg-ivory shadow-[0_18px_48px_rgba(38,35,28,0.16)]"
    >
      <div ref={listRef} className="max-h-[280px] overflow-y-auto py-1">
        {items.length === 0 ? (
          <p className="px-4 py-3 text-caption text-stone-gray">
            {t("chat.columnMentionPicker.noResults")}
          </p>
        ) : (
          items.map((item, index) => {
            const active = index === boundedActiveIndex;
            return (
              <button
                ref={(el) => {
                  itemRefs.current[index] = el;
                }}
                id={`column-mention-option-${item.id}`}
                key={item.id}
                type="button"
                role="option"
                aria-selected={active}
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-2 text-left transition-colors",
                  active ? "bg-warm-sand text-near-black" : "text-charcoal-warm hover:bg-parchment"
                )}
                onMouseEnter={() => onActiveIndexChange(index)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  onSelect(item);
                }}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-body-sm font-medium text-near-black">@{item.columnLabel}</p>
                  {item.columnLabel !== item.columnName ? (
                    <code className="block truncate font-mono text-[11px] text-terracotta">@{item.columnName}</code>
                  ) : null}
                </div>
                <span className="shrink-0 rounded-full bg-parchment px-2 py-0.5 text-[10px] font-medium text-olive-gray">
                  {item.tableLabel}
                </span>
                <span className="shrink-0 rounded-full bg-warm-sand px-2 py-0.5 text-[10px] font-medium text-stone-gray uppercase">
                  {item.columnType.toLowerCase()}
                </span>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

// ─── ChartTypePicker ───────────────────────────────────────────────────────

function ChartTypePicker({
  options,
  activeIndex,
  onActiveIndexChange,
  onSelect,
  t,
}: {
  options: ChartTypeOption[];
  activeIndex: number;
  onActiveIndexChange: (index: number) => void;
  onSelect: (option: ChartTypeOption) => void;
  t: (key: string, params?: Record<string, string | number | null | undefined>) => string;
}) {
  const boundedActiveIndex = Math.min(activeIndex, options.length - 1);
  const activeOption = options[boundedActiveIndex] ?? options[0];
  const listRef = useRef<HTMLDivElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    const list = listRef.current;
    const activeElement = optionRefs.current[boundedActiveIndex];
    if (!list || !activeElement) return;

    const itemTop = activeElement.offsetTop;
    const itemBottom = itemTop + activeElement.offsetHeight;
    const visibleTop = list.scrollTop;
    const visibleBottom = visibleTop + list.clientHeight;

    if (itemTop < visibleTop) {
      list.scrollTo({ top: itemTop, behavior: "smooth" });
      return;
    }
    if (itemBottom > visibleBottom) {
      list.scrollTo({ top: itemBottom - list.clientHeight, behavior: "smooth" });
    }
  }, [boundedActiveIndex, options.length]);

  return (
    <div
      id="chart-type-picker"
      role="listbox"
      aria-label={t("chat.chartTypePicker.ariaLabel")}
      className="absolute bottom-[calc(100%+8px)] left-0 z-30 grid w-full max-w-[720px] grid-cols-[minmax(210px,280px)_1fr] overflow-hidden rounded-comfortable border border-border-cream bg-ivory shadow-[0_18px_48px_rgba(38,35,28,0.16)]"
    >
      <div
        id="chart-type-options"
        ref={listRef}
        className="max-h-[320px] overflow-y-auto border-r border-border-cream py-2"
      >
        {options.map((option, index) => {
          const active = index === boundedActiveIndex;
          return (
            <button
              ref={(element) => {
                optionRefs.current[index] = element;
              }}
              id={`chart-type-option-${option.type}`}
              key={option.type}
              type="button"
              role="option"
              aria-selected={active}
              className={cn(
                "grid w-full grid-cols-[1fr_auto] gap-2 px-3 py-2 text-left transition-colors",
                active ? "bg-warm-sand text-near-black" : "text-charcoal-warm hover:bg-parchment"
              )}
              onMouseEnter={() => onActiveIndexChange(index)}
              onMouseDown={(event) => {
                event.preventDefault();
                onSelect(option);
              }}
            >
              <span className="min-w-0">
                <span className="block truncate text-body-sm font-medium">{option.label}</span>
                <span className="block truncate text-caption text-stone-gray">#{option.type}</span>
              </span>
              <span className="rounded-full bg-parchment px-2 py-0.5 text-[10px] font-medium text-olive-gray">
                {option.group}
              </span>
            </button>
          );
        })}
      </div>
      <div className="min-h-[260px] bg-parchment p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-body-sm font-semibold text-near-black">{activeOption.label}</p>
            <p className="mt-1 text-caption text-stone-gray">{activeOption.description}</p>
          </div>
          <code className="shrink-0 rounded-full bg-ivory px-2 py-1 text-[11px] text-terracotta">
            chart_type: {activeOption.type}
          </code>
        </div>
        <ChartExamplePreview type={activeOption.type} />
      </div>
    </div>
  );
}

function ChartExamplePreview({ type }: { type: QueryChartType }) {
  if (type === "table") {
    return (
      <div className="mt-5 overflow-hidden rounded-comfortable border border-border-cream bg-ivory">
        {[0, 1, 2, 3].map((row) => (
          <div key={row} className="grid grid-cols-3 border-b border-border-cream last:border-b-0">
            {[0, 1, 2].map((col) => (
              <div
                key={`${row}-${col}`}
                className={cn("h-9 border-r border-border-cream last:border-r-0", row === 0 ? "bg-warm-sand" : "bg-ivory")}
              />
            ))}
          </div>
        ))}
      </div>
    );
  }

  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 320 180"
      className="mt-5 h-[180px] w-full rounded-comfortable bg-ivory shadow-ring-warm"
    >
      <ChartExampleShape type={type} />
    </svg>
  );
}

function polarPoint(cx: number, cy: number, radius: number, angle: number) {
  const radians = ((angle - 90) * Math.PI) / 180;
  return {
    x: cx + radius * Math.cos(radians),
    y: cy + radius * Math.sin(radians),
  };
}

function annularSegmentPath(
  cx: number,
  cy: number,
  innerRadius: number,
  outerRadius: number,
  startAngle: number,
  endAngle: number
) {
  const outerStart = polarPoint(cx, cy, outerRadius, startAngle);
  const outerEnd = polarPoint(cx, cy, outerRadius, endAngle);
  const innerEnd = polarPoint(cx, cy, innerRadius, endAngle);
  const innerStart = polarPoint(cx, cy, innerRadius, startAngle);
  const largeArc = endAngle - startAngle > 180 ? 1 : 0;

  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${outerRadius} ${outerRadius} 0 ${largeArc} 1 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerEnd.x} ${innerEnd.y}`,
    `A ${innerRadius} ${innerRadius} 0 ${largeArc} 0 ${innerStart.x} ${innerStart.y}`,
    "Z",
  ].join(" ");
}

function ChartExampleShape({ type }: { type: QueryChartType }) {
  const axis = (
    <>
      <line x1="38" y1="142" x2="286" y2="142" stroke="#d9d3c4" strokeWidth="2" />
      <line x1="38" y1="32" x2="38" y2="142" stroke="#d9d3c4" strokeWidth="2" />
    </>
  );

  if (type === "stacked_line") {
    // Three stacked series: each series' values are cumulative on top of the previous
    const xs = [42, 88, 132, 178, 224, 272];
    // Series A (bottom): gentle rise
    const s1y = [128, 118, 112, 106, 100, 92];
    // Series B (mid): stacked on top of A
    const s2y = [108, 94, 86, 76, 68, 56];
    // Series C (top): stacked on top of A+B
    const s3y = [80, 66, 54, 42, 36, 28];
    const pts = (ys: number[]) => xs.map((x, i) => `${x},${ys[i]}`).join(" L ");
    return (
      <>
        {axis}
        {/* Fill areas from bottom (x-axis) up */}
        <path d={`M${pts(s1y)} L272,142 L42,142 Z`} fill="#9bb7a5" opacity="0.4" />
        <path d={`M${pts(s2y)} L272,${s1y[5]} L${xs.slice().reverse().map((x, i) => `${x},${s1y[5 - i]}`).join(" L")} Z`} fill="#4b7f8c" opacity="0.3" />
        <path d={`M${pts(s3y)} L272,${s2y[5]} L${xs.slice().reverse().map((x, i) => `${x},${s2y[5 - i]}`).join(" L")} Z`} fill="#c96442" opacity="0.25" />
        {/* Series lines */}
        <path d={`M${pts(s1y)}`} fill="none" stroke="#9bb7a5" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d={`M${pts(s2y)}`} fill="none" stroke="#4b7f8c" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d={`M${pts(s3y)}`} fill="none" stroke="#c96442" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        {/* Dots for each series */}
        {xs.map((x, i) => <circle key={`s1-${x}`} cx={x} cy={s1y[i]} r="3.5" fill="#9bb7a5" stroke="#fff" strokeWidth="1" />)}
        {xs.map((x, i) => <circle key={`s2-${x}`} cx={x} cy={s2y[i]} r="3.5" fill="#4b7f8c" stroke="#fff" strokeWidth="1" />)}
        {xs.map((x, i) => <circle key={`s3-${x}`} cx={x} cy={s3y[i]} r="3.5" fill="#c96442" stroke="#fff" strokeWidth="1" />)}
      </>
    );
  }

  if (type === "line" || type === "area") {
    return (
      <>
        {axis}
        {type === "area" ? <path d="M42 130 L88 112 L132 118 L178 72 L224 86 L272 48 L272 142 L42 142 Z" fill="#9bb7a5" opacity="0.35" /> : null}
        <path d="M42 130 L88 112 L132 118 L178 72 L224 86 L272 48" fill="none" stroke="#4b7f8c" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
        {[42, 88, 132, 178, 224, 272].map((x, i) => (
          <circle key={x} cx={x} cy={[130, 112, 118, 72, 86, 48][i]} r="5" fill="#c96442" />
        ))}
      </>
    );
  }

  if (type === "negative_bar") {
    const zeroX = 160;
    const rows = [
      { y: 50, value: -58 },
      { y: 72, value: 76 },
      { y: 94, value: -36 },
      { y: 116, value: 92 },
      { y: 138, value: -64 },
    ];
    const scale = 1.05;
    return (
      <>
        <line x1="42" y1="32" x2="286" y2="32" stroke="#d9d3c4" strokeWidth="2" />
        <line x1={zeroX} y1="36" x2={zeroX} y2="148" stroke="#bdb5a6" strokeWidth="2" strokeDasharray="4 4" />
        {rows.map(({ y, value }, index) => {
          const width = Math.abs(value) * scale;
          const x = value < 0 ? zeroX - width : zeroX;
          return (
            <g key={index}>
              <rect x={x} y={y - 8} width={width} height="16" rx="3" fill={value < 0 ? "#c96442" : "#4b7f8c"} />
              <line x1="42" y1={y} x2="286" y2={y} stroke="#efe9dc" strokeWidth="1" strokeDasharray="3 4" />
            </g>
          );
        })}
      </>
    );
  }

  if (type === "bar" || type === "grouped_bar" || type === "stacked_bar") {
    const bars = [
      [58, 86],
      [104, 58],
      [150, 94],
      [196, 42],
      [242, 70],
    ];
    return (
      <>
        {axis}
        {bars.map(([x, height]) =>
          type === "stacked_bar" ? (
            <g key={x}>
              <rect x={x} y={142 - height} width="26" height={height * 0.48} rx="3" fill="#4b7f8c" />
              <rect x={x} y={142 - height * 0.52} width="26" height={height * 0.52} rx="3" fill="#c96442" />
            </g>
          ) : type === "grouped_bar" ? (
            <g key={x}>
              <rect x={x - 8} y={142 - height * 0.72} width="12" height={height * 0.72} rx="2" fill="#4b7f8c" />
              <rect x={x + 8} y={142 - height} width="12" height={height} rx="2" fill="#c96442" />
            </g>
          ) : (
            <rect key={x} x={x} y={142 - height} width="28" height={height} rx="4" fill="#c96442" />
          )
        )}
      </>
    );
  }

  if (type === "pie") {
    return (
      <>
        <circle cx="160" cy="90" r="62" fill="#4b7f8c" />
        <path d="M160 90 L160 28 A62 62 0 0 1 216 116 Z" fill="#c96442" />
        <path d="M160 90 L216 116 A62 62 0 0 1 130 144 Z" fill="#9bb7a5" />
        <circle cx="160" cy="90" r="28" fill="#faf9f5" />
      </>
    );
  }

  if (type === "scatter" || type === "scatter_clustering") {
    const colors = type === "scatter_clustering"
      ? ["#37A2DA", "#e06343", "#37a354"]
      : ["#4b7f8c"];
    return (
      <>
        {axis}
        {[
          [70, 116],
          [96, 94],
          [122, 105],
          [148, 78],
          [174, 86],
          [202, 56],
          [232, 68],
          [258, 44],
        ].map(([x, y], index) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r="7" fill={colors[index % colors.length]} opacity="0.86" />
        ))}
      </>
    );
  }

  if (type === "funnel") {
    return (
      <>
        <path d="M70 36 H250 L224 68 H96 Z" fill="#4b7f8c" />
        <path d="M96 76 H224 L204 108 H116 Z" fill="#c96442" />
        <path d="M122 116 H198 L182 148 H138 Z" fill="#9bb7a5" />
      </>
    );
  }

  if (type === "multiple_funnel") {
    return (
      <>
        <path d="M42 34 H138 L122 58 H58 Z" fill="#4b7f8c" />
        <path d="M58 64 H122 L112 88 H68 Z" fill="#c96442" />
        <path d="M70 94 H110 L102 118 H78 Z" fill="#9bb7a5" />
        <path d="M58 148 H122 L110 124 H70 Z" fill="#4b7f8c" opacity="0.75" />
        <path d="M42 174 H138 L122 150 H58 Z" fill="#c96442" opacity="0.75" />
        <path d="M182 34 H278 L262 58 H198 Z" fill="#4b7f8c" />
        <path d="M198 64 H262 L252 88 H208 Z" fill="#c96442" />
        <path d="M210 94 H250 L242 118 H218 Z" fill="#9bb7a5" />
        <path d="M198 148 H262 L250 124 H210 Z" fill="#4b7f8c" opacity="0.75" />
        <path d="M182 174 H278 L262 150 H198 Z" fill="#c96442" opacity="0.75" />
      </>
    );
  }

  if (type === "radar") {
    return (
      <>
        {[62, 42, 22].map((offset) => (
          <polygon key={offset} points={`160,${28 + offset} 220,${70 + offset / 3} 198,${136 - offset / 4} 122,${136 - offset / 4} 100,${70 + offset / 3}`} fill="none" stroke="#d9d3c4" />
        ))}
        <polygon points="160,46 214,82 190,130 126,124 110,76" fill="#4b7f8c" opacity="0.32" stroke="#4b7f8c" strokeWidth="4" />
      </>
    );
  }

  if (type === "treemap") {
    return (
      <>
        <rect x="48" y="36" width="116" height="108" rx="4" fill="#4b7f8c" />
        <rect x="172" y="36" width="100" height="62" rx="4" fill="#c96442" />
        <rect x="172" y="106" width="46" height="38" rx="4" fill="#9bb7a5" />
        <rect x="226" y="106" width="46" height="38" rx="4" fill="#d6a94a" />
      </>
    );
  }

  if (type === "sunburst") {
    const cx = 160;
    const cy = 90;
    const outerSegments = [
      { start: 0, end: 90, fill: "#c96442" },
      { start: 90, end: 220, fill: "#9bb7a5" },
      { start: 220, end: 360, fill: "#d6a94a" },
    ];
    const innerSegments = [
      { start: 0, end: 145, fill: "#4b7f8c" },
      { start: 145, end: 250, fill: "#c96442" },
      { start: 250, end: 360, fill: "#d6a94a" },
    ];

    return (
      <>
        {outerSegments.map((segment) => (
          <path
            key={`outer-${segment.start}`}
            d={annularSegmentPath(cx, cy, 38, 64, segment.start, segment.end)}
            fill={segment.fill}
          />
        ))}
        {innerSegments.map((segment) => (
          <path
            key={`inner-${segment.start}`}
            d={annularSegmentPath(cx, cy, 17, 32, segment.start, segment.end)}
            fill={segment.fill}
          />
        ))}
        <circle cx={cx} cy={cy} r="15" fill="#faf9f5" />
      </>
    );
  }

  if (type === "sankey") {
    return (
      <>
        <path d="M74 56 C130 56 138 86 190 86 C220 86 232 72 260 72" fill="none" stroke="#4b7f8c" strokeWidth="22" opacity="0.45" />
        <path d="M74 116 C132 116 142 94 190 94 C226 94 232 124 260 124" fill="none" stroke="#c96442" strokeWidth="18" opacity="0.45" />
        {[74, 190, 260].map((x) => (
          <rect key={x} x={x - 8} y="40" width="16" height="96" rx="4" fill="#4d4c48" />
        ))}
      </>
    );
  }

  if (type === "graph") {
    const nodes = [
      [86, 74],
      [150, 44],
      [220, 78],
      [128, 130],
      [224, 132],
    ];
    return (
      <>
        <path d="M86 74 L150 44 L220 78 L224 132 L128 130 L86 74 L220 78" fill="none" stroke="#d9d3c4" strokeWidth="3" />
        {nodes.map(([x, y], index) => (
          <circle key={index} cx={x} cy={y} r="17" fill={index % 2 ? "#c96442" : "#4b7f8c"} />
        ))}
      </>
    );
  }

  if (type === "boxplot") {
    return (
      <>
        {axis}
        {[82, 144, 206, 268].map((x, index) => (
          <g key={x}>
            <line x1={x} y1={48 + index * 8} x2={x} y2="134" stroke="#4d4c48" strokeWidth="2" />
            <rect x={x - 18} y={72 + index * 5} width="36" height="42" fill="#9bb7a5" stroke="#4b7f8c" strokeWidth="3" />
            <line x1={x - 18} y1={94 + index * 2} x2={x + 18} y2={94 + index * 2} stroke="#c96442" strokeWidth="3" />
          </g>
        ))}
      </>
    );
  }

  if (type === "candlestick") {
    return (
      <>
        {axis}
        {[70, 108, 146, 184, 222, 260].map((x, index) => (
          <g key={x}>
            <line x1={x} y1={42 + index * 8} x2={x} y2={126 - index * 3} stroke="#4d4c48" strokeWidth="2" />
            <rect x={x - 9} y={62 + index * 5} width="18" height={42 - index * 3} fill={index % 2 ? "#4b7f8c" : "#c96442"} />
          </g>
        ))}
      </>
    );
  }

  if (type === "map") {
    return (
      <>
        <path
          d="M52,82 L62,48 L90,38 L118,28 L152,24 L188,22 L212,18 L230,30 L232,52 L238,72 L236,86 L242,102 L238,114 L234,126 L218,138 L198,148 L174,148 L154,142 L142,132 L126,122 L108,112 L90,104 L72,92 Z"
          fill="#e0f3db"
          stroke="#4b7f8c"
          strokeWidth="2"
        />
        <path d="M188,22 L212,18 L230,30 L232,52 L210,62 L192,50 Z" fill="#43a2ca" opacity="0.7" />
        <path d="M210,62 L232,52 L238,72 L236,86 L242,102 L238,114 L222,110 L218,86 Z" fill="#c96442" opacity="0.6" />
        <path d="M222,110 L238,114 L234,126 L218,138 L198,148 L178,146 L182,126 Z" fill="#a8ddb5" opacity="0.8" />
        <ellipse cx="200" cy="156" rx="11" ry="5.5" fill="#a8ddb5" stroke="#4b7f8c" strokeWidth="1.5" />
      </>
    );
  }

  if (type === "heatmap") {
    return (
      <>
        {Array.from({ length: 5 }).map((_, row) =>
          Array.from({ length: 7 }).map((__, col) => (
            <rect
              key={`${row}-${col}`}
              x={54 + col * 30}
              y={34 + row * 24}
              width="24"
              height="18"
              rx="3"
              fill={["#e0f3db", "#a8ddb5", "#43a2ca", "#c96442"][(row + col) % 4]}
            />
          ))
        )}
      </>
    );
  }

  if (type === "parallel") {
    return (
      <>
        {[62, 110, 158, 206, 254].map((x) => (
          <line key={x} x1={x} y1="36" x2={x} y2="142" stroke="#d9d3c4" strokeWidth="2" />
        ))}
        <path d="M62 124 L110 70 L158 96 L206 44 L254 86" fill="none" stroke="#4b7f8c" strokeWidth="4" opacity="0.8" />
        <path d="M62 62 L110 116 L158 74 L206 104 L254 48" fill="none" stroke="#c96442" strokeWidth="4" opacity="0.75" />
      </>
    );
  }

  if (type === "gauge") {
    return (
      <>
        <path d="M88 126 A72 72 0 0 1 232 126" fill="none" stroke="#d9d3c4" strokeWidth="18" strokeLinecap="round" />
        <path d="M88 126 A72 72 0 0 1 198 66" fill="none" stroke="#c96442" strokeWidth="18" strokeLinecap="round" />
        <line x1="160" y1="126" x2="198" y2="82" stroke="#4d4c48" strokeWidth="5" strokeLinecap="round" />
        <circle cx="160" cy="126" r="8" fill="#4d4c48" />
        <text x="160" y="158" textAnchor="middle" fontSize="26" fontWeight="700" fill="#141413">76</text>
      </>
    );
  }

  if (type === "single_value") {
    return (
      <>
        <rect x="72" y="42" width="176" height="96" rx="8" fill="#faf9f5" stroke="#d9d3c4" strokeWidth="2" />
        <rect x="72" y="42" width="6" height="96" rx="3" fill="#4b7f8c" />
        <text x="160" y="94" textAnchor="middle" fontSize="42" fontWeight="800" fill="#141413">76</text>
        <text x="160" y="120" textAnchor="middle" fontSize="14" fontWeight="600" fill="#777066">metric_value</text>
      </>
    );
  }

  if (type === "wordCloud") {
    return (
      <>
        <text x="72" y="74" fontSize="30" fontWeight="700" fill="#4b7f8c">Talent</text>
        <text x="150" y="108" fontSize="24" fontWeight="700" fill="#c96442">HR</text>
        <text x="56" y="122" fontSize="18" fill="#9bb7a5">salary</text>
        <text x="192" y="70" fontSize="16" fill="#d6a94a">team</text>
        <text x="190" y="134" fontSize="20" fill="#4d4c48">project</text>
      </>
    );
  }

  return null;
}

// ─── Approval helpers ──────────────────────────────────────────────────────

function collectPendingApprovalOptions(
  values: string[] | undefined
): IngestionProposalAction[] {
  const options = (values ?? [])
    .map(normalizeApprovalAction)
    .filter((item): item is IngestionProposalAction => item !== null);
  if (options.length === 0) {
    return ["update_existing", "time_partitioned_new_table", "new_table", "cancel"];
  }
  const deduped: IngestionProposalAction[] = [];
  for (const item of options) {
    if (!deduped.includes(item)) {
      deduped.push(item);
    }
  }
  return deduped;
}

function normalizeApprovalAction(value: string): IngestionProposalAction | null {
  const normalized = value.trim().toLowerCase();
  if (
    normalized === "update_existing" ||
    normalized === "time_partitioned_new_table" ||
    normalized === "new_table" ||
    normalized === "cancel"
  ) {
    return normalized;
  }
  return null;
}

function formatApprovalActionLabel({
  action,
  timeGrain,
  t,
}: {
  action: IngestionProposalAction;
  timeGrain: IngestionTimeGrain;
  t: (key: string, params?: Record<string, string | number | null | undefined>) => string;
}): string {
  if (action === "update_existing") {
    return t("ingestion.lifecycle.action.updateExisting");
  }
  if (action === "new_table") {
    return t("ingestion.lifecycle.action.newTable");
  }
  if (action === "time_partitioned_new_table") {
    if (timeGrain === "month") {
      return t("ingestion.lifecycle.action.newMonthly");
    }
    if (timeGrain === "quarter") {
      return t("ingestion.lifecycle.action.newQuarterly");
    }
    if (timeGrain === "year") {
      return t("ingestion.lifecycle.action.newYearly");
    }
    return t("ingestion.lifecycle.action.newTimePartitioned");
  }
  return t("ingestion.lifecycle.action.cancel");
}
