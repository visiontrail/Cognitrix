import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminSkillsPage from "../../components/admin/admin-skills-page";
import { I18nProvider } from "../../lib/i18n/context";
import * as skillsApi from "../../lib/admin/skills";
import type { Skill } from "../../lib/admin/skills";
import { clearInMemoryToken, setInMemoryToken } from "../../lib/auth/session";

const SUPERADMIN_JWT = buildJwt({
  role: "superadmin",
  sub: "ops-root",
  project_id: "default",
  exp: 9_999_999_999,
});

const ADMIN_JWT = buildJwt({
  role: "admin",
  sub: "user-admin",
  project_id: "default",
  exp: 9_999_999_999,
});

const SAMPLE_SKILL: Skill = {
  id: "skill-1",
  name: "anthropic/xlsx",
  version: "1.2.0",
  sha256: "abc123",
  status: "enabled",
  uploaded_by: "ops-root",
  uploaded_at: 1_715_000_000,
  bundle_dir: "/tmp/skill-1",
  manifest: { name: "anthropic/xlsx", description: "xlsx" },
  load_error: null,
  assignments: [],
};

function renderPage() {
  return render(
    <I18nProvider>
      <AdminSkillsPage />
    </I18nProvider>,
  );
}

function setStoredToken(token: string) {
  setInMemoryToken(token, 9_999_999_999);
}

describe("AdminSkillsPage", () => {
  beforeEach(() => {
    clearInMemoryToken();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    clearInMemoryToken();
    window.localStorage.clear();
  });

  it("renders a generic not-found page for non-superadmin users", () => {
    setStoredToken(ADMIN_JWT);
    renderPage();
    expect(screen.getByText("Not found")).toBeInTheDocument();
    expect(screen.queryByText(/Agent Skills/)).not.toBeInTheDocument();
  });

  it("renders the admin console for superadmins", async () => {
    setStoredToken(SUPERADMIN_JWT);
    vi.spyOn(skillsApi, "listSkills").mockResolvedValue({
      count: 1,
      skills: [SAMPLE_SKILL],
    });

    renderPage();
    expect(await screen.findByText("Agent Skills")).toBeInTheDocument();
    expect(await screen.findByText("anthropic/xlsx")).toBeInTheDocument();
  });

  it("uploads a zip file via the upload control", async () => {
    setStoredToken(SUPERADMIN_JWT);
    const listMock = vi.spyOn(skillsApi, "listSkills").mockResolvedValue({
      count: 0,
      skills: [],
    });
    const uploadMock = vi
      .spyOn(skillsApi, "uploadSkill")
      .mockResolvedValue(SAMPLE_SKILL);

    renderPage();
    await screen.findByText("Agent Skills");

    const file = new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04])], "skill.zip", {
      type: "application/zip",
    });

    const input = screen.getByLabelText("Upload skill (.zip)") as HTMLInputElement;
    await userEvent.upload(input, file);

    await waitFor(() => {
      expect(uploadMock).toHaveBeenCalledTimes(1);
    });
    expect(uploadMock.mock.calls[0][0].name).toBe("skill.zip");
    expect(listMock).toHaveBeenCalledTimes(2); // initial + post-upload refresh
  });

  it("toggles an agent assignment via the checkbox", async () => {
    setStoredToken(SUPERADMIN_JWT);
    vi.spyOn(skillsApi, "listSkills").mockResolvedValue({
      count: 1,
      skills: [SAMPLE_SKILL],
    });
    const assignMock = vi.spyOn(skillsApi, "assignSkill").mockResolvedValue();

    renderPage();
    const checkbox = await screen.findByLabelText("anthropic/xlsx WriteIngestionAgent");
    expect((checkbox as HTMLInputElement).checked).toBe(false);

    await userEvent.click(checkbox);

    await waitFor(() => {
      expect(assignMock).toHaveBeenCalledWith("skill-1", "WriteIngestionAgent");
    });
  });
});

// ------------------------------------------------------------
// Helpers
// ------------------------------------------------------------

function buildJwt(payload: Record<string, unknown>): string {
  const header = base64UrlEncode(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const body = base64UrlEncode(JSON.stringify(payload));
  // The frontend never verifies the signature, it only decodes the payload to
  // read `role`; the literal "sig" segment keeps the JWT shape valid.
  return `${header}.${body}.sig`;
}

function base64UrlEncode(text: string): string {
  return btoa(text).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
}
