import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => ({ get: () => null }),
}));

// vi.mock factories are hoisted above module-level consts, so the mock has to be
// created inside vi.hoisted() for the factory below to reference it.
const { mockRegister } = vi.hoisted(() => ({
  mockRegister: vi.fn().mockResolvedValue({
    access_token: "token123",
    expires_at: Date.now() / 1000 + 3600,
    user: { id: "u1", email: "new@example.com", display_name: "New User", job_id: 1 },
  }),
}));

vi.mock("@/lib/auth/auth-client", () => ({
  apiRegister: mockRegister,
  AuthError: class AuthError extends Error {
    code: string;
    status: number;
    constructor(code: string, message: string, status: number) {
      super(message);
      this.code = code;
      this.status = status;
    }
  },
}));

vi.mock("@/lib/auth/session", () => ({
  setInMemoryToken: vi.fn(),
}));

// Mock fetch for /jobs endpoint
global.fetch = vi.fn().mockResolvedValue({
  json: () => Promise.resolve({
    jobs: [
      { id: 1, code: "developer", label_zh: "开发者", label_en: "Developer", sort_order: 1 },
    ],
  }),
} as Response);

import RegisterPage from "../../app/(auth)/register/page";
import { DEFAULT_LOCALE, DICTIONARY } from "../../lib/i18n/dictionary";

// The form is localized and renders in DEFAULT_LOCALE (en-US) here, so fields are
// addressed by their stable input ids rather than by translated label text.
function field(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`missing form field #${id}`);
  }
  return element;
}

describe("RegisterPage", () => {
  it("renders registration fields", () => {
    render(<RegisterPage />);
    expect(field("email")).toBeInTheDocument();
    expect(field("displayName")).toBeInTheDocument();
    expect(field("password")).toBeInTheDocument();
    expect(screen.getByLabelText(DICTIONARY[DEFAULT_LOCALE]["auth.emailAddress"])).toBe(
      field("email")
    );
  });

  it("shows error when password is too short", async () => {
    render(<RegisterPage />);

    // Job is validated before the password, so pick one from the mocked /jobs
    // response first — otherwise the form stops at "select your role".
    await waitFor(() =>
      expect((field("job") as HTMLSelectElement).options.length).toBeGreaterThan(1)
    );
    fireEvent.change(field("job"), { target: { value: "1" } });
    fireEvent.change(field("email"), { target: { value: "a@b.com" } });
    fireEvent.change(field("displayName"), { target: { value: "Alice" } });
    fireEvent.change(field("password"), { target: { value: "short" } });
    fireEvent.submit(document.querySelector("form")!);

    await waitFor(() => {
      expect(screen.getByText(/at least 8 characters/i)).toBeInTheDocument();
    });
  });
});
