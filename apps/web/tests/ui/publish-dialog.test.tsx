import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PublishPanel } from "../../components/workspace/publish-dialog";
import type { PublicationState } from "../../lib/workspace/publish";

const copyTextToClipboardMock = vi.fn<(text: string) => Promise<boolean>>();

vi.mock("@/lib/clipboard", () => ({
  copyTextToClipboard: (text: string) => copyTextToClipboardMock(text),
}));

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

  it("renders no user-search or allowlist controls", () => {
    const { container } = render(
      <PublishPanel publication={ACTIVE_PUBLICATION} onPublish={vi.fn()} onCancel={vi.fn()} />
    );

    // The viewer/allowlist visibility model is gone: no search inputs, no
    // allowlist user pickers, no visibility radio options.
    expect(container.querySelector('input[type="search"]')).toBeNull();
    expect(container.querySelector('input[type="radio"]')).toBeNull();
    expect(screen.queryByText(/allowlist/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/visibility/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/registered users/i)).not.toBeInTheDocument();
  });

  it("treats a revoked publication as unpublished", () => {
    render(
      <PublishPanel publication={{ is_active: false }} onPublish={vi.fn()} onCancel={vi.fn()} />
    );

    expect(screen.getByTestId("publish-confirm")).toBeInTheDocument();
    expect(screen.queryByTestId("publish-link")).not.toBeInTheDocument();
  });
});
