import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IngestionLifecyclePanel } from "../../components/chat/ingestion-lifecycle-panel";

const ingestionApiMocks = vi.hoisted(() => ({
  createIngestionUpload: vi.fn(),
  createIngestionPlan: vi.fn(),
  confirmIngestionSetup: vi.fn(),
  approveIngestionProposal: vi.fn(),
  executeIngestionProposal: vi.fn(),
  streamIngestionPlan: vi.fn(),
  streamIngestionSetupConfirm: vi.fn(),
  streamIngestionExecute: vi.fn(),
}));

const {
  createIngestionUpload,
  approveIngestionProposal,
  streamIngestionPlan,
  streamIngestionSetupConfirm,
  streamIngestionExecute,
} = ingestionApiMocks;

vi.mock("../../lib/ingestion/api", () => {
  class MockIngestionApiError extends Error {
    code?: string;
    status: number;

    constructor(message: string, code?: string, status = 400) {
      super(message);
      this.code = code;
      this.status = status;
      this.name = "IngestionApiError";
    }
  }

  return {
    ...ingestionApiMocks,
    IngestionApiError: MockIngestionApiError,
  };
});

function sampleUploadResult() {
  return {
    uploadId: "upload-1",
    jobId: "job-1",
    workspaceId: "ws-1",
    status: "uploaded" as const,
    fileSummary: {
      fileName: "roster.xlsx",
      sizeBytes: 1024,
      fileHash: "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
      storagePath: "/tmp/roster.xlsx",
    },
    sheetSummary: {},
    columnSummary: {},
    samplePreview: [],
  };
}

// Raw backend snake_case format as returned by streaming decision event
function sampleProposalDecision() {
  return {
    status: "awaiting_user_approval",
    workspace_id: "ws-1",
    job_id: "job-1",
    proposal_id: "proposal-1",
    proposal_json: {
      business_type: "roster",
      confidence: 0.9,
      recommended_action: "update_existing",
      candidate_actions: ["update_existing", "time_partitioned_new_table", "new_table", "cancel"],
      target_table: "employee_roster",
      time_grain: "none",
      match_columns: ["employee_id"],
      column_mapping: { "Employee ID": "employee_id" },
      diff_preview: {
        predicted_insert_count: 2,
        predicted_update_count: 1,
        predicted_conflict_count: 0,
      },
      risks: ["Potential duplicate employee_id rows"],
      explanation: "matched",
      sql_draft: "MERGE INTO employee_roster ...",
      requires_catalog_setup: false,
      created_at: "2026-04-17T00:00:00Z",
    },
    human_approval: {
      required: true,
      mechanism: "frontend_approval_card",
      stage: "proposal_approval",
      question: "是否将数据合并到现有花名册表？",
      options: ["update_existing", "time_partitioned_new_table", "new_table", "cancel"],
      recommended_option: "update_existing",
    },
    route: { route: "write_ingestion", reason: "has_files" },
    tool_trace: [],
  };
}

function sampleCatalogSetupDecision() {
  return {
    status: "awaiting_catalog_setup",
    workspace_id: "ws-1",
    job_id: "job-1",
    agent_guess: { business_type: "roster", confidence: 0.8 },
    setup_questions: [
      { question_id: "business_type", title: "Type", options: ["roster", "other"] },
      { question_id: "write_mode", title: "Mode", options: ["update_existing"] },
    ],
    suggested_catalog_seed: {
      business_type: "roster",
      table_name: "employee_roster",
      human_label: "Employee Roster",
      write_mode: "update_existing",
      time_grain: "none",
      primary_keys: ["employee_id"],
      match_columns: ["employee_id"],
      is_active_target: true,
      description: "seed",
    },
    human_approval: {
      required: true,
      mechanism: "catalog_setup_card",
      stage: "catalog_setup",
      question: "先确认目录设置再继续？",
      options: ["confirm_catalog_setup", "cancel"],
      recommended_option: "confirm_catalog_setup",
    },
    route: { route: "write_ingestion", reason: "has_file" },
    tool_trace: [],
  };
}

function sampleExecuteDecision() {
  return {
    status: "succeeded",
    workspace_id: "ws-1",
    job_id: "job-1",
    proposal_id: "proposal-1",
    execution_id: "exec-1",
    receipt: {
      success: true,
      workspace_id: "ws-1",
      job_id: "job-1",
      target_table: "employee_roster",
      execution_mode: "update_existing",
      inserted_rows: 2,
      updated_rows: 1,
      affected_rows: 3,
      rows_after: 10,
      duckdb_path: "/tmp/ws-1.duckdb",
      finished_at: "2026-04-17T00:00:00Z",
    },
  };
}

async function* makeStreamDecision(decisionData: Record<string, unknown>) {
  yield { event: "decision", data: decisionData };
}

describe("IngestionLifecyclePanel", () => {
  beforeEach(() => {
    createIngestionUpload.mockReset();
    ingestionApiMocks.createIngestionPlan.mockReset();
    ingestionApiMocks.confirmIngestionSetup.mockReset();
    approveIngestionProposal.mockReset();
    ingestionApiMocks.executeIngestionProposal.mockReset();
    streamIngestionPlan.mockReset();
    streamIngestionSetupConfirm.mockReset();
    streamIngestionExecute.mockReset();
  });

  it("renders setup card when planning requires catalog setup", async () => {
    createIngestionUpload.mockResolvedValue(sampleUploadResult());
    streamIngestionPlan.mockImplementation(() => makeStreamDecision(sampleCatalogSetupDecision()));
    streamIngestionSetupConfirm.mockImplementation(() => makeStreamDecision(sampleProposalDecision()));
    approveIngestionProposal.mockResolvedValue({
      status: "approved",
      workspaceId: "ws-1",
      jobId: "job-1",
      proposalId: "proposal-1",
      approvedAction: "update_existing",
      targetTable: "employee_roster",
      dryRunSummary: { approvedAction: "update_existing", targetTable: "employee_roster", timeGrain: "none", predictedInsertCount: 2, predictedUpdateCount: 1, predictedConflictCount: 0 },
    });
    streamIngestionExecute.mockImplementation(() => makeStreamDecision(sampleExecuteDecision()));

    render(<IngestionLifecyclePanel workspaceId="ws-1" workspaceTitle="Ops Workspace" />);

    const file = new File(["demo"], "roster.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });

    await userEvent.upload(screen.getByTestId("ingestion-upload-input"), file);
    await userEvent.click(screen.getByRole("button", { name: "Upload & Plan" }));

    expect(await screen.findByTestId("ingestion-setup-flow")).toBeInTheDocument();
    expect(screen.getByText("Catalog setup is required before planning can continue.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Confirm & Import" }));
    expect(await screen.findByTestId("ingestion-receipt-card")).toBeInTheDocument();
    expect(streamIngestionSetupConfirm).toHaveBeenCalledTimes(1);
  });

  it("completes proposal approval and execution receipt flow", async () => {
    createIngestionUpload.mockResolvedValue(sampleUploadResult());
    streamIngestionPlan.mockImplementation(() => makeStreamDecision(sampleProposalDecision()));
    approveIngestionProposal.mockResolvedValue({
      status: "approved",
      workspaceId: "ws-1",
      jobId: "job-1",
      proposalId: "proposal-1",
      approvedAction: "update_existing",
      targetTable: "employee_roster",
      timeGrain: "none",
      dryRunSummary: {
        approvedAction: "update_existing",
        targetTable: "employee_roster",
        timeGrain: "none",
        predictedInsertCount: 2,
        predictedUpdateCount: 1,
        predictedConflictCount: 0,
        predictedAffectedRows: 3,
        schemaWarnings: [],
        risks: [],
      },
    });
    streamIngestionExecute.mockImplementation(() => makeStreamDecision(sampleExecuteDecision()));

    render(<IngestionLifecyclePanel workspaceId="ws-1" workspaceTitle="Ops Workspace" />);

    const file = new File(["demo"], "roster.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });

    await userEvent.upload(screen.getByTestId("ingestion-upload-input"), file);
    await userEvent.click(screen.getByRole("button", { name: "Upload & Plan" }));

    expect(await screen.findByTestId("ingestion-proposal-card")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Update Existing" }));

    expect(await screen.findByTestId("ingestion-approved-card")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Execute Write" }));

    expect(await screen.findByTestId("ingestion-receipt-card")).toBeInTheDocument();
    expect(screen.getByText(/Target: employee_roster/)).toBeInTheDocument();

    await waitFor(() => {
      expect(approveIngestionProposal).toHaveBeenCalledTimes(1);
      expect(streamIngestionExecute).toHaveBeenCalledTimes(1);
    });
  });

  it("shows interpretable error state when upload fails", async () => {
    createIngestionUpload.mockRejectedValue(new Error("upload_failed_500"));

    render(<IngestionLifecyclePanel workspaceId="ws-1" workspaceTitle="Ops Workspace" />);

    const file = new File(["demo"], "roster.xlsx", {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });

    await userEvent.upload(screen.getByTestId("ingestion-upload-input"), file);
    await userEvent.click(screen.getByRole("button", { name: "Upload & Plan" }));

    expect(await screen.findByTestId("ingestion-error-card")).toHaveTextContent("upload_failed_500");
    expect(screen.getByText(/Ingestion failed at upload_or_plan/)).toBeInTheDocument();
  });
});
