import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PublishPanel } from "../../components/workspace/publish-dialog";
import type { PublicationState, PublishVisibilityUser } from "../../lib/workspace/publish";

const copyTextToClipboardMock = vi.fn<(text: string) => Promise<boolean>>();
const fetchUsersByIdsMock = vi.hoisted(() =>
  vi.fn<(userIds: string[]) => Promise<PublishVisibilityUser[]>>()
);

vi.mock("@/lib/clipboard", () => ({
  copyTextToClipboard: (text: string) => copyTextToClipboardMock(text),
}));

vi.mock("@/lib/workspace/publish", async () => {
  const actual = await vi.importActual<typeof import("../../lib/workspace/publish")>(
    "../../lib/workspace/publish"
  );
  return {
    ...actual,
    fetchUsersByIds: fetchUsersByIdsMock,
  };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const ACTIVE_PUBLICATION: PublicationState = {
  is_active: true,
  token: "tok-abc123",
  public_url: "https://share.example.com/p/tok-abc123",
  published_page_id: "page-1",
  version: 3,
  published_at: "2026-06-24T00:00:00+00:00",
};

// In jsdom, resolvePublicUrl rebuilds the URL from window.location.origin, so
// assert on the stable `/p/{token}` suffix rather than the server-provided host.
const EXPECTED_SUFFIX = "/p/tok-abc123";

describe("PublishPanel dialog states", () => {
  beforeEach(() => {
    copyTextToClipboardMock.mockReset().mockResolvedValue(true);
    fetchUsersByIdsMock.mockReset().mockResolvedValue([]);
  });

  it("shows the create-link action and no link when unpublished", () => {
    render(<PublishPanel publication={null} onPublish={vi.fn()} onCancel={vi.fn()} />);

    expect(screen.getByTestId("publish-confirm")).toBeInTheDocument();
    expect(screen.getByText("Publish and create link")).toBeInTheDocument();
    expect(screen.queryByTestId("publish-link")).not.toBeInTheDocument();
    expect(screen.queryByTestId("publish-update")).not.toBeInTheDocument();
    expect(screen.queryByTestId("publish-cancel")).not.toBeInTheDocument();
  });

  it("calls onPublish when creating the link", () => {
    const onPublish = vi.fn();
    render(<PublishPanel publication={null} onPublish={onPublish} onCancel={vi.fn()} />);

    fireEvent.click(screen.getByTestId("publish-confirm"));
    expect(onPublish).toHaveBeenCalledTimes(1);
  });

  it("renders link, copy, preview, update, and cancel when published", () => {
    render(
      <PublishPanel publication={ACTIVE_PUBLICATION} onPublish={vi.fn()} onCancel={vi.fn()} />
    );

    expect(screen.getByTestId("publish-link").textContent).toContain(EXPECTED_SUFFIX);
    expect(screen.getByTestId("publish-copy")).toBeInTheDocument();

    const preview = screen.getByTestId("publish-preview");
    expect(preview.getAttribute("href")).toContain(EXPECTED_SUFFIX);
    expect(preview).toHaveAttribute("target", "_blank");

    expect(screen.getByTestId("publish-update")).toBeInTheDocument();
    expect(screen.getByTestId("publish-cancel")).toBeInTheDocument();
    // The unpublished create-link action is gone once a link exists.
    expect(screen.queryByTestId("publish-confirm")).not.toBeInTheDocument();
  });

  it("copies the public link on copy click", async () => {
    render(
      <PublishPanel publication={ACTIVE_PUBLICATION} onPublish={vi.fn()} onCancel={vi.fn()} />
    );

    fireEvent.click(screen.getByTestId("publish-copy"));
    await waitFor(() => expect(copyTextToClipboardMock).toHaveBeenCalledTimes(1));
    expect(copyTextToClipboardMock.mock.calls[0][0]).toContain(EXPECTED_SUFFIX);
  });

  it("invokes update and cancel handlers", () => {
    const onPublish = vi.fn();
    const onCancel = vi.fn();
    render(
      <PublishPanel publication={ACTIVE_PUBLICATION} onPublish={onPublish} onCancel={onCancel} />
    );

    fireEvent.click(screen.getByTestId("publish-update"));
    expect(onPublish).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("publish-cancel"));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("renders visibility controls and passes registered visibility to publish", () => {
    const onPublish = vi.fn();
    render(<PublishPanel publication={null} onPublish={onPublish} onCancel={vi.fn()} />);

    expect(screen.getByTestId("publish-visibility-public")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByTestId("publish-visibility-registered"));
    expect(screen.getByTestId("publish-visibility-registered")).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByTestId("publish-confirm"));
    expect(onPublish).toHaveBeenCalledWith({
      visibility_mode: "registered",
      visibility_user_ids: [],
    });
  });

  it("requires at least one selected user for allowlist publishing", () => {
    const onPublish = vi.fn();
    render(<PublishPanel publication={null} onPublish={onPublish} onCancel={vi.fn()} />);

    fireEvent.click(screen.getByTestId("publish-visibility-allowlist"));

    expect(screen.getByTestId("publish-allowlist-controls")).toBeInTheDocument();
    expect(screen.getByText("Select at least one registered user.")).toBeInTheDocument();
    expect(screen.getByTestId("publish-confirm")).toBeDisabled();
    fireEvent.click(screen.getByTestId("publish-confirm"));
    expect(onPublish).not.toHaveBeenCalled();
  });

  it("loads allowlisted users for an active restricted publication", async () => {
    fetchUsersByIdsMock.mockResolvedValue([
      {
        id: "user-1",
        display_name: "Ada Analyst",
        email_masked: "ad***@example.com",
        job_label: "Data Analyst",
      },
    ]);

    render(
      <PublishPanel
        publication={{
          ...ACTIVE_PUBLICATION,
          visibility_mode: "allowlist",
          visibility_user_ids: ["user-1"],
          visibility_user_count: 1,
        }}
        onPublish={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    expect(await screen.findByText("Ada Analyst")).toBeInTheDocument();
    expect(fetchUsersByIdsMock).toHaveBeenCalledWith(["user-1"]);
  });

  it("treats a revoked publication as unpublished", () => {
    render(
      <PublishPanel publication={{ is_active: false }} onPublish={vi.fn()} onCancel={vi.fn()} />
    );

    expect(screen.getByTestId("publish-confirm")).toBeInTheDocument();
    expect(screen.queryByTestId("publish-link")).not.toBeInTheDocument();
  });
});
