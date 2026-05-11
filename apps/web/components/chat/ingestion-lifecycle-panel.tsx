"use client";

import { ChangeEvent, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Upload, AlertTriangle, CheckCircle2, XCircle, Brain, ChevronDown, ChevronRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  IngestionApprovalResult,
  IngestionCatalogSetupSeed,
  IngestionExecuteResult,
  IngestionLifecyclePhase,
  IngestionPlanAwaitingApproval,
  IngestionPlanAwaitingSetup,
  IngestionProposalAction,
  IngestionTimeGrain,
  IngestionUploadResult,
} from "@/types/ingestion";
import {
  approveIngestionProposal,
  createIngestionUpload,
  streamIngestionExecute,
  streamIngestionPlan,
  streamIngestionSetupConfirm,
  IngestionApiError,
} from "@/lib/ingestion/api";
import { IngestionSetupCard } from "@/components/workspace/ingestion-setup-card";
import { AgentTraceStep } from "@/components/chat/agent-trace-step";
import { useI18n } from "@/lib/i18n/context";
import { refreshWorkspaceCatalog } from "@/lib/workspace/query-keys";
import type { TraceStep } from "@/types/trace";

type IngestionLifecyclePanelProps = {
  workspaceId: string;
  workspaceTitle?: string | null;
};

type IngestionErrorState = {
  stage: string;
  message: string;
  code?: string;
};

type ProposalActionButton = {
  labelKey: string;
  approvedAction: IngestionProposalAction;
  timeGrain?: IngestionTimeGrain;
};

type AgentTraceState = {
  state: "live" | "collapsed" | "expanded";
  steps: TraceStep[];
  startedAt: number;
  endedAt?: number;
};

const PROPOSAL_ACTION_BUTTONS: ProposalActionButton[] = [
  { labelKey: "ingestion.lifecycle.action.updateExisting", approvedAction: "update_existing" },
  { labelKey: "ingestion.lifecycle.action.newMonthly", approvedAction: "time_partitioned_new_table", timeGrain: "month" },
  { labelKey: "ingestion.lifecycle.action.newQuarterly", approvedAction: "time_partitioned_new_table", timeGrain: "quarter" },
  { labelKey: "ingestion.lifecycle.action.newYearly", approvedAction: "time_partitioned_new_table", timeGrain: "year" },
  { labelKey: "ingestion.lifecycle.action.newTable", approvedAction: "new_table" },
  { labelKey: "ingestion.lifecycle.action.cancel", approvedAction: "cancel" },
];

function isRecord(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

function ThinkingDots() {
  return (
    <span className="flex items-center gap-0.5">
      <span className="w-1 h-1 rounded-full bg-stone-gray animate-bounce" style={{ animationDelay: "0ms" }} />
      <span className="w-1 h-1 rounded-full bg-stone-gray animate-bounce" style={{ animationDelay: "160ms" }} />
      <span className="w-1 h-1 rounded-full bg-stone-gray animate-bounce" style={{ animationDelay: "320ms" }} />
    </span>
  );
}

function formatDurationSec(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

function computeResultPreview(result: unknown): string | undefined {
  if (!result) return undefined;
  const text = JSON.stringify(result);
  return text.length > 120 ? text.slice(0, 120) + "…" : text;
}

type IngestionAgentTraceProps = {
  trace: AgentTraceState;
  onToggle: () => void;
};

function IngestionAgentTrace({ trace, onToggle }: IngestionAgentTraceProps) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  const liveEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (trace.state !== "live") return;
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [trace.state]);

  useEffect(() => {
    if (trace.state === "live") {
      liveEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [trace.steps.length, trace.state]);

  const isLive = trace.state === "live";

  if (isLive) {
    if (trace.steps.length === 0) {
      return (
        <div className="mb-2">
          <div className="flex items-center gap-1.5 pl-3 border-l border-border-cream py-1">
            <Brain className="w-3 h-3 text-stone-gray shrink-0 animate-pulse" />
            <span className="text-[11px] text-stone-gray select-none">分析中</span>
            <ThinkingDots />
          </div>
        </div>
      );
    }

    const hasActionSteps = trace.steps.some((s) => s.kind === "tool" || s.kind === "error");

    if (!hasActionSteps) {
      const planningText = trace.steps.filter((s) => s.kind === "planning").map((s) => s.text).join("\n\n");
      return (
        <div className="mb-2">
          <div className="border-l border-border-cream pl-3">
            <div className="flex items-center gap-1.5 mb-1">
              <Brain className="w-3 h-3 text-stone-gray shrink-0 animate-pulse" />
              <span className="text-[10px] text-stone-gray select-none">分析中</span>
              <ThinkingDots />
            </div>
            <div className="max-h-[4.5rem] overflow-y-auto">
              <p className="text-[11px] text-stone-gray leading-snug whitespace-pre-wrap">{planningText}</p>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className="mb-2">
        <div className="max-h-[40vh] overflow-y-auto border-l border-border-cream pl-3 space-y-0.5">
          {trace.steps.map((step, i) => (
            <AgentTraceStep key={step.id} step={step} isLive={true} isLatest={i === trace.steps.length - 1} nowMs={nowMs} />
          ))}
          <div ref={liveEndRef} />
        </div>
      </div>
    );
  }

  const durationMs = (trace.endedAt ?? Date.now()) - trace.startedAt;
  const durationStr = formatDurationSec(durationMs);
  const toolCount = trace.steps.filter((s) => s.kind === "tool").length;
  const hasError = trace.steps.some((s) => s.kind === "error");
  const isExpanded = trace.state === "expanded";

  const chipLabel = hasError
    ? `分析出错 (${durationStr})`
    : `分析完成 · ${durationStr} · ${toolCount} 次工具调用`;

  return (
    <div className="mb-2">
      <button
        type="button"
        className={`text-[10px] underline-offset-2 hover:underline select-none ${hasError ? "text-terracotta" : "text-stone-gray"}`}
        onClick={onToggle}
      >
        {chipLabel}
        {isExpanded ? <ChevronDown className="inline ml-0.5 w-3 h-3" /> : <ChevronRight className="inline ml-0.5 w-3 h-3" />}
      </button>
      {isExpanded && trace.steps.length > 0 && (
        <div className="mt-1 max-h-[40vh] overflow-y-auto border-l border-border-cream pl-3 space-y-0.5">
          {trace.steps.map((step) => (
            <AgentTraceStep key={step.id} step={step} isLive={false} isLatest={false} nowMs={nowMs} />
          ))}
        </div>
      )}
    </div>
  );
}

export function IngestionLifecyclePanel({ workspaceId, workspaceTitle }: IngestionLifecyclePanelProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<IngestionLifecyclePhase>("idle");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadResult, setUploadResult] = useState<IngestionUploadResult | null>(null);
  const [setupPayload, setSetupPayload] = useState<IngestionPlanAwaitingSetup | null>(null);
  const [approvalPayload, setApprovalPayload] = useState<IngestionPlanAwaitingApproval | null>(null);
  const [approvedResult, setApprovedResult] = useState<IngestionApprovalResult | null>(null);
  const [executeResult, setExecuteResult] = useState<IngestionExecuteResult | null>(null);
  const [errorState, setErrorState] = useState<IngestionErrorState | null>(null);
  const [agentTrace, setAgentTrace] = useState<AgentTraceState | null>(null);

  const isBusy =
    phase === "uploading" || phase === "planning" || phase === "approving" || phase === "executing";

  const phaseLabel = (() => {
    switch (phase) {
      case "uploading": return t("ingestion.lifecycle.phase.uploading");
      case "planning": return t("ingestion.lifecycle.phase.planning");
      case "awaiting_catalog_setup": return t("ingestion.lifecycle.phase.awaiting_catalog_setup");
      case "awaiting_user_approval": return t("ingestion.lifecycle.phase.awaiting_user_approval");
      case "approving": return t("ingestion.lifecycle.phase.approving");
      case "approved": return t("ingestion.lifecycle.phase.approved");
      case "executing": return t("ingestion.lifecycle.phase.executing");
      case "succeeded": return t("ingestion.lifecycle.phase.succeeded");
      case "cancelled": return t("ingestion.lifecycle.phase.cancelled");
      case "failed": return t("ingestion.lifecycle.phase.failed");
      default: return t("ingestion.lifecycle.phase.idle");
    }
  })();

  function startTrace(): AgentTraceState {
    const trace: AgentTraceState = { state: "live", steps: [], startedAt: Date.now() };
    setAgentTrace(trace);
    return trace;
  }

  function pushTraceStep(step: TraceStep) {
    flushSync(() => {
      setAgentTrace((prev) => prev ? { ...prev, steps: [...prev.steps, step] } : prev);
    });
  }

  function patchTraceStep(stepId: string, updates: Partial<TraceStep>) {
    flushSync(() => {
      setAgentTrace((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          steps: prev.steps.map((s) => (s.id === stepId ? { ...s, ...updates } as TraceStep : s)),
        };
      });
    });
  }

  function finalizeTrace(hasError: boolean) {
    setAgentTrace((prev) => prev ? { ...prev, state: hasError ? "expanded" : "collapsed", endedAt: Date.now() } : prev);
  }

  async function consumeIngestionStream(
    gen: AsyncGenerator<{ event: string; data: unknown }>,
  ): Promise<Record<string, unknown> | null> {
    let planningStepCount = 0;
    let decisionPayload: Record<string, unknown> | null = null;
    let hasError = false;

    for await (const sseEvent of gen) {
      const payload = isRecord(sseEvent.data) ? sseEvent.data : {};

      if (sseEvent.event === "planning") {
        const text = String(payload.text ?? "");
        if (text) {
          pushTraceStep({
            kind: "planning",
            id: `planning-${planningStepCount++}`,
            text,
            startedAt: Date.now(),
          });
        }
      } else if (sseEvent.event === "tool_use") {
        const stepId = String(payload.step_id ?? `tool-${Date.now()}`);
        const toolName = String(payload.tool_name ?? "");
        const startedAt = typeof payload.started_at === "number" ? payload.started_at * 1000 : Date.now();
        pushTraceStep({
          kind: "tool",
          id: stepId,
          tool: toolName,
          args: isRecord(payload.arguments) ? payload.arguments : {},
          startedAt,
          status: "running",
        });
      } else if (sseEvent.event === "tool_result") {
        const stepId = String(payload.step_id ?? "");
        const completedAt = typeof payload.completed_at === "number" ? payload.completed_at * 1000 : Date.now();
        const status = payload.status === "error" ? "error" : "ok";
        const resultPreview = computeResultPreview(payload.result);
        patchTraceStep(stepId, {
          completedAt,
          status,
          result: payload.result,
          resultPreview,
        } as Partial<TraceStep>);
      } else if (sseEvent.event === "decision") {
        decisionPayload = payload;
      } else if (sseEvent.event === "error") {
        hasError = true;
        const code = String(payload.code ?? "");
        const message = String(payload.message ?? t("ingestion.lifecycle.error.unexpected"));
        pushTraceStep({
          kind: "error",
          id: `error-${Date.now()}`,
          message,
          code: code || undefined,
          at: Date.now(),
        });
        setErrorState({ stage: "agent", code: code || undefined, message });
      }
    }

    finalizeTrace(hasError);
    return decisionPayload;
  }

  async function handleUploadAndPlan() {
    if (!selectedFile) {
      setErrorState({ stage: "upload", message: t("ingestion.lifecycle.error.chooseFile") });
      setPhase("failed");
      return;
    }

    clearLifecycleError();
    setApprovalPayload(null);
    setSetupPayload(null);
    setApprovedResult(null);
    setExecuteResult(null);
    setAgentTrace(null);

    try {
      setPhase("uploading");
      const upload = await createIngestionUpload({ workspaceId, file: selectedFile });
      setUploadResult(upload);

      setPhase("planning");
      startTrace();

      const gen = streamIngestionPlan({
        workspaceId,
        jobId: upload.jobId,
        message: `ingest ${selectedFile.name}`,
      });

      const decisionPayload = await consumeIngestionStream(gen);

      if (decisionPayload) {
        const plan = mapPlanLikePayload(decisionPayload);
        applyPlanPayload(plan);
      } else if (errorState === null) {
        handleFailure("planning", new Error("No decision received from planning agent"));
      }
    } catch (error) {
      finalizeTrace(true);
      handleFailure("upload_or_plan", error);
    }
  }

  async function handleSetupConfirm(seed: IngestionCatalogSetupSeed) {
    if (!uploadResult) {
      handleFailure("setup", new Error(t("ingestion.lifecycle.error.uploadContextMissing")));
      return;
    }

    clearLifecycleError();
    setAgentTrace(null);

    try {
      setPhase("planning");
      startTrace();

      const gen = streamIngestionSetupConfirm({
        workspaceId,
        jobId: uploadResult.jobId,
        setup: seed,
      });

      const decisionPayload = await consumeIngestionStream(gen);

      if (!decisionPayload) {
        if (errorState === null) {
          handleFailure("setup", new Error("No decision received from setup agent"));
        }
        return;
      }

      const plan = mapPlanLikePayload(decisionPayload);

      // After catalog setup is confirmed and re-planning returns a proposal,
      // auto-approve with the recommended action and auto-execute so the user
      // only needs to click "Confirm & Import" once.
      if (plan.status === "awaiting_user_approval") {
        const approvalPlan = plan as IngestionPlanAwaitingApproval;
        await autoApproveAndExecute(approvalPlan);
      } else {
        applyPlanPayload(plan);
      }
    } catch (error) {
      finalizeTrace(true);
      handleFailure("setup", error);
    }
  }

  async function autoApproveAndExecute(plan: IngestionPlanAwaitingApproval) {
    if (!uploadResult) return;
    clearLifecycleError();
    try {
      setPhase("approving");
      const recommendedAction = plan.proposal.recommendedAction;
      const timeGrain =
        recommendedAction === "time_partitioned_new_table" ? plan.proposal.timeGrain : undefined;
      const approved = await approveIngestionProposal({
        workspaceId,
        jobId: uploadResult.jobId,
        proposalId: plan.proposalId,
        approvedAction: recommendedAction,
        userOverrides: timeGrain && timeGrain !== "none" ? { timeGrain } : undefined,
      });
      setApprovedResult(approved);
      if (approved.status === "cancelled") {
        setPhase("cancelled");
        return;
      }
      setPhase("executing");
      setAgentTrace(null);
      startTrace();
      const gen = streamIngestionExecute({
        workspaceId,
        jobId: uploadResult.jobId,
        proposalId: plan.proposalId,
      });
      const execPayload = await consumeIngestionStream(gen);
      if (execPayload) {
        const execution = mapExecutePayload(execPayload);
        setExecuteResult(execution);
        setPhase("succeeded");
        refreshCatalogAfterSuccessfulExecution(execution);
      } else if (errorState === null) {
        handleFailure("execute", new Error("No result received from execution agent"));
      } else {
        setPhase("failed");
      }
    } catch (error) {
      finalizeTrace(true);
      handleFailure("setup_execute", error);
    }
  }

  async function handleProposalAction(button: ProposalActionButton) {
    if (!uploadResult || !approvalPayload) {
      handleFailure("approval", new Error(t("ingestion.lifecycle.error.proposalContextMissing")));
      return;
    }

    clearLifecycleError();
    try {
      setPhase("approving");
      const approved = await approveIngestionProposal({
        workspaceId,
        jobId: uploadResult.jobId,
        proposalId: approvalPayload.proposalId,
        approvedAction: button.approvedAction,
        userOverrides: button.timeGrain ? { timeGrain: button.timeGrain } : undefined,
      });
      setApprovedResult(approved);
      if (approved.status === "cancelled") {
        setPhase("cancelled");
        return;
      }
      setPhase("approved");
    } catch (error) {
      handleFailure("approval", error);
    }
  }

  async function handleExecute() {
    if (!uploadResult || !approvalPayload) {
      handleFailure("execute", new Error(t("ingestion.lifecycle.error.executeContextMissing")));
      return;
    }

    clearLifecycleError();
    setAgentTrace(null);

    try {
      setPhase("executing");
      startTrace();

      const gen = streamIngestionExecute({
        workspaceId,
        jobId: uploadResult.jobId,
        proposalId: approvalPayload.proposalId,
      });

      const decisionPayload = await consumeIngestionStream(gen);

      if (decisionPayload) {
        const execution = mapExecutePayload(decisionPayload);
        setExecuteResult(execution);
        setPhase("succeeded");
        refreshCatalogAfterSuccessfulExecution(execution);
      } else if (errorState === null) {
        handleFailure("execute", new Error("No result received from execution agent"));
      } else {
        setPhase("failed");
      }
    } catch (error) {
      finalizeTrace(true);
      handleFailure("execute", error);
    }
  }

  function mapPlanLikePayload(record: Record<string, unknown>) {
    const status = String(record.status ?? "");
    if (status === "awaiting_catalog_setup") {
      const agentGuess = isRecord(record.agent_guess) ? record.agent_guess : {};
      return {
        status: "awaiting_catalog_setup" as const,
        workspaceId: String(record.workspace_id ?? ""),
        jobId: String(record.job_id ?? ""),
        agentGuess: {
          businessType: String(agentGuess.business_type ?? "") as never,
          confidence: Number(agentGuess.confidence ?? 0),
        },
        setupQuestions: Array.isArray(record.setup_questions)
          ? record.setup_questions.map((q: unknown) => {
              const qr = isRecord(q) ? q : {};
              return {
                questionId: String(qr.question_id ?? ""),
                title: String(qr.title ?? ""),
                options: Array.isArray(qr.options) ? qr.options.map(String) : [],
              };
            })
          : [],
        suggestedCatalogSeed: isRecord(record.suggested_catalog_seed)
          ? fromApiSetupSeedRecord(record.suggested_catalog_seed)
          : ({} as IngestionCatalogSetupSeed),
        humanApproval: mapHumanApprovalRecord(record.human_approval, "catalog_setup"),
        route: { route: String(isRecord(record.route) ? record.route.route : ""), reason: "" },
        toolTrace: [],
      };
    }
    const proposal = isRecord(record.proposal_json) ? record.proposal_json : {};
    const humanApproval = mapHumanApprovalRecord(record.human_approval, "proposal_approval");
    return {
      status: "awaiting_user_approval" as const,
      workspaceId: String(record.workspace_id ?? ""),
      jobId: String(record.job_id ?? ""),
      proposalId: String(record.proposal_id ?? ""),
      proposal: mapProposalRecord(proposal),
      humanApproval,
      route: { route: String(isRecord(record.route) ? record.route.route : ""), reason: "" },
      toolTrace: [],
      existingTables: isRecord(record.existing_tables) ? record.existing_tables : {},
    };
  }

  function mapExecutePayload(record: Record<string, unknown>): IngestionExecuteResult {
    const receipt = isRecord(record.receipt) ? record.receipt : {};
    return {
      status: "succeeded",
      workspaceId: String(record.workspace_id ?? ""),
      jobId: String(record.job_id ?? ""),
      proposalId: String(record.proposal_id ?? ""),
      executionId: String(record.execution_id ?? ""),
      receipt: {
        success: Boolean(receipt.success),
        workspaceId: String(receipt.workspace_id ?? ""),
        jobId: String(receipt.job_id ?? ""),
        targetTable: String(receipt.target_table ?? ""),
        executionMode: (String(receipt.execution_mode ?? "update_existing")) as IngestionProposalAction,
        insertedRows: Number(receipt.inserted_rows ?? 0),
        updatedRows: Number(receipt.updated_rows ?? 0),
        affectedRows: Number(receipt.affected_rows ?? 0),
        rowsAfter: Number(receipt.rows_after ?? 0),
        duckdbPath: String(receipt.duckdb_path ?? ""),
        finishedAt: String(receipt.finished_at ?? ""),
      },
    };
  }

  function refreshCatalogAfterSuccessfulExecution(execution: IngestionExecuteResult) {
    if (!execution.receipt.success) return;
    void refreshWorkspaceCatalog(queryClient, workspaceId);
  }

  function applyPlanPayload(plan: ReturnType<typeof mapPlanLikePayload>) {
    if (plan.status === "awaiting_catalog_setup") {
      setSetupPayload(plan as IngestionPlanAwaitingSetup);
      setApprovalPayload(null);
      setPhase("awaiting_catalog_setup");
      return;
    }
    setSetupPayload(null);
    setApprovalPayload(plan as IngestionPlanAwaitingApproval);
    setPhase("awaiting_user_approval");
  }

  function clearLifecycleError() {
    if (errorState) setErrorState(null);
    if (phase === "failed") setPhase("idle");
  }

  function handleFailure(stage: string, error: unknown) {
    if (error instanceof IngestionApiError) {
      setErrorState({ stage, code: error.code, message: error.message });
    } else if (error instanceof Error) {
      setErrorState({ stage, message: error.message });
    } else {
      setErrorState({ stage, message: t("ingestion.lifecycle.error.unexpected") });
    }
    setPhase("failed");
  }

  function resetLifecycle() {
    setPhase("idle");
    setSelectedFile(null);
    setUploadResult(null);
    setSetupPayload(null);
    setApprovalPayload(null);
    setApprovedResult(null);
    setExecuteResult(null);
    setErrorState(null);
    setAgentTrace(null);
  }

  const candidateActions = approvalPayload?.proposal.candidateActions ?? [];
  const approvalOptions = approvalPayload?.humanApproval.options ?? [];
  const supportedActions = approvalOptions.length > 0 ? approvalOptions : candidateActions;

  return (
    <div className="border-b border-border-cream bg-parchment/60 px-4 py-3" data-testid="ingestion-lifecycle-panel">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base">{t("ingestion.lifecycle.title")}</CardTitle>
              <CardDescription>{t("ingestion.lifecycle.description")}</CardDescription>
            </div>
            <Badge variant={phase === "failed" ? "secondary" : "outline"}>{phaseLabel}</Badge>
          </div>
          <p className="text-label text-stone-gray">
            {t("ingestion.lifecycle.boundWorkspace", { workspace: workspaceTitle ?? workspaceId })}
          </p>
        </CardHeader>

        <CardContent className="space-y-4">
          <div className="flex flex-col gap-2 md:flex-row md:items-center">
            <label className="text-label text-stone-gray" htmlFor="ingestion-upload-input">
              {t("ingestion.lifecycle.uploadXlsx")}
            </label>
            <input
              id="ingestion-upload-input"
              data-testid="ingestion-upload-input"
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={(event: ChangeEvent<HTMLInputElement>) => {
                setSelectedFile(event.target.files?.[0] ?? null);
                if (phase === "failed") {
                  setPhase("idle");
                  setErrorState(null);
                }
              }}
              disabled={isBusy}
              className="text-body-sm"
            />
            <Button onClick={handleUploadAndPlan} disabled={!selectedFile || isBusy} size="sm" type="button">
              {isBusy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Upload className="mr-1 h-4 w-4" />}
              {isBusy ? t("ingestion.lifecycle.processing") : t("ingestion.lifecycle.uploadAndPlan")}
            </Button>
            {(phase === "succeeded" || phase === "cancelled" || phase === "failed") && (
              <Button variant="ghost" size="sm" onClick={resetLifecycle} type="button" disabled={isBusy}>
                {t("ingestion.lifecycle.startNewUpload")}
              </Button>
            )}
          </div>

          {selectedFile ? (
            <p className="text-caption text-stone-gray" data-testid="ingestion-selected-file">
              {t("ingestion.lifecycle.selectedFile", { fileName: selectedFile.name })}
            </p>
          ) : null}

          {uploadResult ? (
            <div className="rounded-comfortable border border-border-cream bg-ivory/70 px-3 py-2">
              <p className="text-body-sm text-near-black">
                {t("ingestion.lifecycle.job", { jobId: uploadResult.jobId })}
              </p>
              <p className="text-caption text-stone-gray">
                {t("ingestion.lifecycle.fileHash", {
                  hash: uploadResult.fileSummary.fileHash.slice(0, 12),
                  size: uploadResult.fileSummary.sizeBytes,
                })}
              </p>
            </div>
          ) : null}

          {agentTrace ? (
            <IngestionAgentTrace
              trace={agentTrace}
              onToggle={() =>
                setAgentTrace((prev) =>
                  prev ? { ...prev, state: prev.state === "expanded" ? "collapsed" : "expanded" } : prev
                )
              }
            />
          ) : null}

          {setupPayload ? (
            <div className="space-y-2" data-testid="ingestion-setup-flow">
              <p className="text-body-sm text-stone-gray">{t("ingestion.lifecycle.setupRequired")}</p>
              <IngestionSetupCard
                initialSeed={setupPayload.suggestedCatalogSeed}
                setupQuestions={setupPayload.setupQuestions}
                agentConfidence={setupPayload.agentGuess?.confidence}
                isSubmitting={phase === "planning" || phase === "approving" || phase === "executing"}
                onConfirm={handleSetupConfirm}
                onCancel={() => {
                  setPhase("cancelled");
                  setSetupPayload(null);
                }}
              />
              {(phase === "approving" || phase === "executing") && (
                <div className="rounded-comfortable border border-amber-200 bg-amber-50 px-3 py-2 text-body-sm text-amber-800">
                  {t("ingestion.lifecycle.setupAutoApplied")}
                </div>
              )}
            </div>
          ) : null}

          {approvalPayload ? (
            <div className="space-y-3" data-testid="ingestion-proposal-card">
              {approvalPayload.humanApproval.question ? (
                <div
                  className="rounded-comfortable border border-border-cream bg-amber-50 px-3 py-3"
                  data-testid="ingestion-approval-question"
                >
                  <p className="text-body-sm text-near-black">{approvalPayload.humanApproval.question}</p>
                  {approvalPayload.humanApproval.recommendedOption ? (
                    <p className="pt-1 text-caption text-stone-gray">
                      Recommended: {approvalPayload.humanApproval.recommendedOption}
                    </p>
                  ) : null}
                </div>
              ) : null}
              <div className="rounded-comfortable border border-border-cream bg-ivory/70 px-3 py-3">
                <p className="text-body-sm font-medium text-near-black">
                  {t("ingestion.lifecycle.recommendedAction", {
                    action: approvalPayload.proposal.recommendedAction,
                  })}
                </p>
                <p className="text-caption text-stone-gray">
                  {t("ingestion.lifecycle.targetTableBusinessType", {
                    table: approvalPayload.proposal.targetTable ?? t("ingestion.lifecycle.targetNotSet"),
                    businessType: approvalPayload.proposal.businessType,
                  })}
                </p>
                <p className="text-caption text-stone-gray">
                  {t("ingestion.lifecycle.previewCounts", {
                    insertCount: approvalPayload.proposal.diffPreview.predictedInsertCount,
                    updateCount: approvalPayload.proposal.diffPreview.predictedUpdateCount,
                    conflictCount: approvalPayload.proposal.diffPreview.predictedConflictCount,
                  })}
                </p>
                {approvalPayload.proposal.risks.length > 0 ? (
                  <ul className="list-disc space-y-1 pl-5 pt-1 text-caption text-stone-gray">
                    {approvalPayload.proposal.risks.map((risk) => (
                      <li key={risk}>{risk}</li>
                    ))}
                  </ul>
                ) : null}
              </div>

              <div className="flex flex-wrap gap-2">
                {PROPOSAL_ACTION_BUTTONS.map((button) => {
                  const isSupported = supportedActions.includes(button.approvedAction);
                  return (
                    <Button
                      key={`${button.approvedAction}-${button.timeGrain ?? "none"}`}
                      size="sm"
                      variant={button.approvedAction === "cancel" ? "secondary" : "default"}
                      disabled={!isSupported || isBusy}
                      onClick={() => handleProposalAction(button)}
                      type="button"
                    >
                      {t(button.labelKey)}
                    </Button>
                  );
                })}
              </div>
            </div>
          ) : null}

          {approvedResult?.status === "approved" ? (
            <div className="rounded-comfortable border border-border-cream bg-green-50 px-3 py-3" data-testid="ingestion-approved-card">
              <p className="flex items-center gap-2 text-body-sm font-medium text-near-black">
                <CheckCircle2 className="h-4 w-4 text-green-700" />
                {t("ingestion.lifecycle.proposalApproved", { action: approvedResult.approvedAction })}
              </p>
              <p className="text-caption text-stone-gray">
                {t("ingestion.lifecycle.dryRunSummary", {
                  rows: approvedResult.dryRunSummary.predictedAffectedRows,
                  target: approvedResult.targetTable,
                })}
              </p>
              <div className="pt-2">
                <Button size="sm" onClick={handleExecute} type="button" disabled={isBusy}>
                  {phase === "executing" ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
                  {t("ingestion.lifecycle.executeWrite")}
                </Button>
              </div>
            </div>
          ) : null}

          {executeResult ? (
            <div className="rounded-comfortable border border-border-cream bg-emerald-50 px-3 py-3" data-testid="ingestion-receipt-card">
              <p className="flex items-center gap-2 text-body-sm font-medium text-near-black">
                <CheckCircle2 className="h-4 w-4 text-emerald-700" />
                {t("ingestion.lifecycle.receiptGenerated")}
              </p>
              <p className="text-caption text-stone-gray">
                {t("ingestion.lifecycle.receiptTarget", {
                  target: executeResult.receipt.targetTable,
                  insertedRows: executeResult.receipt.insertedRows,
                  updatedRows: executeResult.receipt.updatedRows,
                })}
              </p>
              <p className="text-caption text-stone-gray">
                {t("ingestion.lifecycle.receiptAffected", {
                  affectedRows: executeResult.receipt.affectedRows,
                  rowsAfter: executeResult.receipt.rowsAfter,
                })}
              </p>
            </div>
          ) : null}

          {phase === "cancelled" ? (
            <div className="rounded-comfortable border border-border-cream bg-stone-100 px-3 py-3 text-body-sm text-near-black" data-testid="ingestion-cancelled-card">
              <p className="flex items-center gap-2">
                <XCircle className="h-4 w-4 text-stone-700" />
                {t("ingestion.lifecycle.cancelled")}
              </p>
            </div>
          ) : null}

          {errorState ? (
            <div className="rounded-comfortable border border-red-200 bg-red-50 px-3 py-3" role="alert" data-testid="ingestion-error-card">
              <p className="flex items-center gap-2 text-body-sm font-medium text-red-700">
                <AlertTriangle className="h-4 w-4" />
                {t("ingestion.lifecycle.failedAt", { stage: errorState.stage })}
              </p>
              <p className="text-caption text-red-700">
                {errorState.code ? `[${errorState.code}] ` : ""}
                {errorState.message}
              </p>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

function mapHumanApprovalRecord(payload: unknown, fallbackStage: "catalog_setup" | "proposal_approval") {
  const record = isRecord(payload) ? payload : {};
  const stage = record.stage === "catalog_setup" || record.stage === "proposal_approval"
    ? (record.stage as "catalog_setup" | "proposal_approval")
    : fallbackStage;
  return {
    required: record.required === undefined ? true : Boolean(record.required),
    mechanism: String(record.mechanism ?? "frontend_approval_card"),
    stage,
    question: String(record.question ?? ""),
    options: Array.isArray(record.options) ? record.options.map(String) : [],
    recommendedOption: typeof record.recommended_option === "string" ? record.recommended_option : null,
  };
}

function mapProposalRecord(payload: Record<string, unknown>) {
  const diffPreview = isRecord(payload.diff_preview) ? payload.diff_preview : {};
  return {
    businessType: String(payload.business_type ?? "") as never,
    confidence: Number(payload.confidence ?? 0),
    recommendedAction: String(payload.recommended_action ?? "") as IngestionProposalAction,
    candidateActions: Array.isArray(payload.candidate_actions)
      ? payload.candidate_actions.map(String) as IngestionProposalAction[]
      : [],
    targetTable: typeof payload.target_table === "string" ? payload.target_table : null,
    timeGrain: (typeof payload.time_grain === "string" ? payload.time_grain : "none") as never,
    matchColumns: Array.isArray(payload.match_columns) ? payload.match_columns.map(String) : [],
    columnMapping: isRecord(payload.column_mapping)
      ? Object.fromEntries(Object.entries(payload.column_mapping).map(([k, v]) => [k, String(v)]))
      : {},
    diffPreview: {
      predictedInsertCount: Number(diffPreview.predicted_insert_count ?? 0),
      predictedUpdateCount: Number(diffPreview.predicted_update_count ?? 0),
      predictedConflictCount: Number(diffPreview.predicted_conflict_count ?? 0),
    },
    risks: Array.isArray(payload.risks) ? payload.risks.map(String) : [],
    explanation: String(payload.explanation ?? ""),
    sqlDraft: String(payload.sql_draft ?? ""),
    requiresCatalogSetup: Boolean(payload.requires_catalog_setup),
    createdAt: String(payload.created_at ?? ""),
  };
}

function fromApiSetupSeedRecord(seed: Record<string, unknown>): IngestionCatalogSetupSeed {
  return {
    businessType: String(seed.business_type ?? "") as never,
    tableName: String(seed.table_name ?? ""),
    humanLabel: String(seed.human_label ?? ""),
    writeMode: (["time_partitioned_new_table", "new_table"].includes(String(seed.write_mode))
      ? seed.write_mode
      : "update_existing") as never,
    timeGrain: (["month", "quarter", "year"].includes(String(seed.time_grain))
      ? seed.time_grain
      : "none") as never,
    primaryKeys: Array.isArray(seed.primary_keys) ? seed.primary_keys.map(String) : [],
    matchColumns: Array.isArray(seed.match_columns) ? seed.match_columns.map(String) : [],
    isActiveTarget: Boolean(seed.is_active_target),
    description: String(seed.description ?? ""),
  };
}
