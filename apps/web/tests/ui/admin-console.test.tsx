import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminConsole from "../../components/admin/admin-console";
import * as controlApi from "../../lib/admin/control";

const sessionState = vi.hoisted(() => ({
  user: {
    id: "root-1",
    email: "root@example.com",
    display_name: "Root",
    job_id: 1,
    role: "superadmin",
    status: "active" as const,
    last_login_at: null,
    available_workspaces: [],
  } as Record<string, unknown> | null,
}));

vi.mock("../../lib/auth/use-session", () => ({
  useSession: () => ({
    user: sessionState.user,
    isLoading: false,
    isLoggedIn: Boolean(sessionState.user),
    query: {},
  }),
}));

vi.mock("../../lib/auth/session", () => ({
  getInMemoryToken: () => "token",
  clearInMemoryToken: vi.fn(),
}));

vi.mock("../../lib/auth/auth-client", () => ({
  apiLogout: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../../lib/admin/skills", () => ({
  KNOWN_AGENT_NAMES: ["WriteIngestionAgent", "QueryAgent", "ChartQueryAgent"],
  listSkills: vi.fn().mockResolvedValue({ count: 0, skills: [] }),
  uploadSkill: vi.fn(),
  setSkillStatus: vi.fn(),
  deleteSkill: vi.fn(),
  assignSkill: vi.fn(),
  unassignSkill: vi.fn(),
}));

const overview = {
  range: { days: 30, start: "2026-06-23T00:00:00Z", end: "2026-07-23T00:00:00Z" },
  summary: {
    requests: 120,
    active_users: 7,
    chat_turns: 42,
    tool_calls: 88,
    errors: 2,
    input_tokens: 1000,
    output_tokens: 400,
    avg_latency_ms: 84,
    total_users: 12,
    enabled_users: 11,
  },
  trend: [
    {
      date: "2026-07-23",
      requests: 12,
      chat_turns: 4,
      tool_calls: 8,
      active_users: 3,
      tokens: 120,
    },
  ],
};

const modelSettings: controlApi.ModelSettings = {
  profiles: [
    {
      name: "deepseek",
      label: "DeepSeek 深度求索",
      default_openai_url: "https://api.deepseek.com",
      default_anthropic_url: "https://api.deepseek.com/anthropic",
      default_model: "deepseek-chat",
      default_fast_model: "deepseek-chat",
      models: ["deepseek-chat", "deepseek-reasoner"],
      notes: "OpenAI 与 Anthropic 兼容端点。",
    },
    {
      name: "yinhe",
      label: "银河内部模型（OneAPI）",
      default_openai_url: "https://oneapi.yhroot.com",
      default_anthropic_url: "https://oneapi.yhroot.com",
      default_model: "yinhe-thinking",
      default_fast_model: "yinhe-chat",
      models: ["yinhe-thinking", "yinhe-chat"],
      notes: "公司内部统一网关。",
    },
  ],
  configuration: {
    backup_enabled: false,
    router_enabled: true,
    failure_threshold: 2,
    cooldown_seconds: 60,
    slow_ttft_ms: 15000,
    first_token_deadline_ms: 20000,
  },
  slots: {
    primary: {
      slot: "primary",
      provider: "deepseek",
      openai_url: "https://api.deepseek.com",
      anthropic_url: "https://api.deepseek.com/anthropic",
      model: "deepseek-chat",
      fast_model: "deepseek-chat",
      api_key_configured: true,
      configured: true,
    },
    backup: {
      slot: "backup",
      provider: "yinhe",
      openai_url: "https://oneapi.yhroot.com",
      anthropic_url: "https://oneapi.yhroot.com",
      model: "yinhe-thinking",
      fast_model: "yinhe-chat",
      api_key_configured: false,
      configured: false,
    },
  },
  router: {
    enabled: true,
    serving_slot: "primary",
    primary_breaker_open: false,
    cooldown_remaining_seconds: 0,
    failure_threshold: 2,
    slow_ttft_ms: 15000,
    first_token_deadline_ms: 20000,
    slots: {
      primary: {
        slot: "primary",
        provider: "deepseek",
        model: "deepseek-chat",
        api_key_configured: true,
        configured: true,
        consecutive_failures: 0,
        samples: [],
      },
    },
  },
};

describe("AdminConsole", () => {
  beforeEach(() => {
    sessionState.user = {
      id: "root-1",
      email: "root@example.com",
      display_name: "Root",
      job_id: 1,
      role: "superadmin",
      status: "active",
      last_login_at: null,
      available_workspaces: [],
    };
    vi.spyOn(controlApi, "getAdminMeta").mockResolvedValue({
      actor: { user_id: "root-1", role: "superadmin" },
      environment: "development",
      app_name: "Cognitrix",
      settings_count: 48,
      restart_required_count: 9,
      skills: { enabled: false, directory: "/tmp/skills", max_upload_mb: 25 },
    });
    vi.spyOn(controlApi, "getUsageOverview").mockResolvedValue(overview);
    vi.spyOn(controlApi, "getUsageUsers").mockResolvedValue({
      users: [],
      page: 1,
      page_size: 25,
      total: 0,
      pages: 1,
    });
    vi.spyOn(controlApi, "getAdminUsers").mockResolvedValue({
      users: [],
      page: 1,
      page_size: 25,
      total: 0,
      pages: 1,
    });
    vi.spyOn(controlApi, "getAdminSettings").mockResolvedValue({
      count: 2,
      categories: ["agent", "models"],
      settings: [
        {
          key: "AGENT_MAX_TOOL_STEPS",
          category: "agent",
          type: "integer",
          value: 20,
          masked_value: "",
          configured: true,
          secret: false,
          source: "environment",
          has_override: false,
          restart_required: false,
          base_value: 20,
          description: "Agent Max Tool Steps",
        },
        {
          key: "AI_API_KEY",
          category: "models",
          type: "string",
          value: null,
          masked_value: "••••••••-key",
          configured: true,
          secret: true,
          source: "environment",
          has_override: false,
          restart_required: false,
          base_value: null,
          description: "Primary model provider API credential",
        },
      ],
    });
    vi.spyOn(controlApi, "getModelSettings").mockResolvedValue(modelSettings);
    vi.spyOn(controlApi, "getSkillsMeta").mockResolvedValue({
      enabled: false,
      directory: "/tmp/skills",
      max_upload_mb: 25,
      known_agents: ["WriteIngestionAgent", "QueryAgent", "ChartQueryAgent"],
    });
  });

  it("renders the operations overview and all control-plane sections", async () => {
    render(<AdminConsole />);

    expect(await screen.findByRole("heading", { name: "运营总览" })).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    for (const label of ["用户管理", "环境配置", "模型设置", "使用指标", "Agent Skills"]) {
      expect(screen.getByRole("button", { name: new RegExp(label) })).toBeInTheDocument();
    }
  });

  it("shows a generic not-found state to non-superadmins", () => {
    sessionState.user = { ...sessionState.user, role: "admin" };
    render(<AdminConsole />);
    expect(screen.getByText("Page not found")).toBeInTheDocument();
    expect(screen.queryByText("环境配置")).not.toBeInTheDocument();
  });

  it("renders typed settings and never places a secret in the input value", async () => {
    render(<AdminConsole />);
    await userEvent.click(screen.getByRole("button", { name: /环境配置/ }));

    expect(await screen.findByText("AGENT_MAX_TOOL_STEPS")).toBeInTheDocument();
    const secretInput = screen.getByLabelText("AI_API_KEY") as HTMLInputElement;
    expect(secretInput.type).toBe("password");
    expect(secretInput.value).toBe("");
    expect(secretInput.placeholder).toBe("••••••••-key");
  });

  it("saves a typed configuration override", async () => {
    const update = vi
      .spyOn(controlApi, "updateAdminSetting")
      .mockResolvedValue({} as controlApi.AdminSetting);
    render(<AdminConsole />);
    await userEvent.click(screen.getByRole("button", { name: /环境配置/ }));
    const input = await screen.findByLabelText("AGENT_MAX_TOOL_STEPS");
    await userEvent.clear(input);
    await userEvent.type(input, "11");

    const row = input.closest("div.grid");
    expect(row).not.toBeNull();
    await userEvent.click(row!.querySelector("button:last-child") as HTMLButtonElement);

    await waitFor(() => {
      expect(update).toHaveBeenCalledWith("AGENT_MAX_TOOL_STEPS", 11);
    });
  });

  it("shows Skills availability even when runtime loading is disabled", async () => {
    render(<AdminConsole />);
    await userEvent.click(screen.getByRole("button", { name: /Agent Skills/ }));
    expect(await screen.findByText("Runtime loading")).toBeInTheDocument();
    expect(screen.getByText("disabled")).toBeInTheDocument();
    expect(screen.getByText("尚未安装 Skill bundle")).toBeInTheDocument();
  });

  it("adapts URLs and model presets when the primary provider changes", async () => {
    const update = vi.spyOn(controlApi, "updateModelSettings").mockResolvedValue(modelSettings);
    render(<AdminConsole />);
    await userEvent.click(screen.getByRole("button", { name: /模型设置/ }));

    const provider = await screen.findByLabelText("主力模型 Provider");
    await userEvent.selectOptions(provider, "yinhe");

    expect(screen.getByLabelText("主力模型 OpenAI Base URL")).toHaveValue("https://oneapi.yhroot.com");
    expect(screen.getByLabelText("主力模型 Anthropic Base URL")).toHaveValue("https://oneapi.yhroot.com");
    expect(screen.getByLabelText("主力模型 模型")).toHaveValue("yinhe-thinking");
    expect(screen.getByLabelText("主力模型 快模型")).toHaveValue("yinhe-chat");

    await userEvent.click(screen.getByRole("button", { name: "保存并即时应用" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith(expect.objectContaining({
      primary_provider: "yinhe",
      primary_model: "yinhe-thinking",
    })));
  });
});
