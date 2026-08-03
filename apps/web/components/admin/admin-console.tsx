"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowLeft,
  Bot,
  Boxes,
  Check,
  ChevronRight,
  CircleGauge,
  CloudCog,
  Database,
  GitBranch,
  KeyRound,
  LayoutGrid,
  Loader2,
  LockKeyhole,
  LogOut,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  ServerCog,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  PlugZap,
  TerminalSquare,
  Upload,
  UserCog,
  Users,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";
import { apiLogout } from "@/lib/auth/auth-client";
import { clearInMemoryToken, getInMemoryToken } from "@/lib/auth/session";
import { useSession } from "@/lib/auth/use-session";
import {
  AdminControlError,
  type AdminMeta,
  type AdminSetting,
  type AdminUser,
  type ModelProviderProfile,
  type ModelSettings,
  type ModelSettingsUpdate,
  type UsageOverview,
  type UsageUser,
  getAdminMeta,
  getAdminSettings,
  getAdminUsers,
  getModelSettings,
  getSkillsMeta,
  getUsageOverview,
  getUsageUsers,
  resetAdminSetting,
  setAdminUserRole,
  setAdminUserStatus,
  testModelConnection,
  updateAdminSetting,
  updateModelSettings,
} from "@/lib/admin/control";
import {
  KNOWN_AGENT_NAMES,
  assignSkill,
  deleteSkill,
  listSkills,
  setSkillStatus,
  unassignSkill,
  uploadSkill,
  type AgentName,
  type Skill,
} from "@/lib/admin/skills";

type Section = "overview" | "users" | "configuration" | "models" | "usage" | "skills";

const NAV: Array<{ id: Section; label: string; eyebrow: string; icon: LucideIcon }> = [
  { id: "overview", label: "运营总览", eyebrow: "OVERVIEW", icon: LayoutGrid },
  { id: "users", label: "用户管理", eyebrow: "IDENTITY", icon: Users },
  { id: "configuration", label: "环境配置", eyebrow: "RUNTIME", icon: SlidersHorizontal },
  { id: "models", label: "模型设置", eyebrow: "INTELLIGENCE", icon: Bot },
  { id: "usage", label: "使用指标", eyebrow: "TELEMETRY", icon: Activity },
  { id: "skills", label: "Agent Skills", eyebrow: "CAPABILITIES", icon: Wrench },
];

export default function AdminConsole() {
  const { user, isLoading } = useSession();
  const [mounted, setMounted] = useState(false);
  const [section, setSection] = useState<Section>("overview");
  const [meta, setMeta] = useState<AdminMeta | null>(null);
  const [overview, setOverview] = useState<UsageOverview | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    const hash = window.location.hash.replace("#", "") as Section;
    if (NAV.some((item) => item.id === hash)) setSection(hash);
  }, []);

  useEffect(() => {
    if (!getInMemoryToken()) {
      window.location.href = "/login?next=%2Fadmin";
    }
  }, []);

  const loadShell = useCallback(async () => {
    const [nextMeta, nextOverview] = await Promise.all([
      getAdminMeta(),
      getUsageOverview(30),
    ]);
    setMeta(nextMeta);
    setOverview(nextOverview);
  }, []);

  useEffect(() => {
    if (user?.role !== "superadmin") return;
    void loadShell().catch((error) => {
      setNotice({ kind: "error", text: errorMessage(error) });
    });
  }, [loadShell, user?.role]);

  const navigate = (next: Section) => {
    setSection(next);
    window.history.replaceState(null, "", `/admin#${next}`);
  };

  const handleLogout = async () => {
    await apiLogout().catch(() => undefined);
    clearInMemoryToken();
    window.location.href = "/login";
  };

  if (!mounted || isLoading || (getInMemoryToken() && !user)) {
    return <AdminLoading />;
  }

  if (!user || user.role !== "superadmin") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#0d0f0c] text-[#ece8dc]">
        <div className="text-center">
          <p className="mb-3 font-mono text-[10px] tracking-[0.35em] text-[#a89d86]">404 / RESTRICTED</p>
          <h1 className="font-serif text-4xl text-[#ece8dc]">Page not found</h1>
        </div>
      </main>
    );
  }

  const active = NAV.find((item) => item.id === section) ?? NAV[0];

  return (
    <div className="min-h-screen bg-[#0d0f0c] text-[#ece8dc] [background-image:radial-gradient(circle_at_20%_0%,rgba(215,171,82,0.08),transparent_32%),linear-gradient(rgba(255,255,255,0.018)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.018)_1px,transparent_1px)] [background-size:auto,32px_32px,32px_32px]">
      <div className="mx-auto flex min-h-screen max-w-[1800px] flex-col lg:flex-row">
        <aside className="border-b border-white/10 bg-[#11130f]/95 lg:sticky lg:top-0 lg:h-screen lg:w-[270px] lg:shrink-0 lg:border-b-0 lg:border-r">
          <div className="flex items-center justify-between border-b border-white/10 px-5 py-5 lg:block lg:px-7 lg:py-8">
            <div>
              <div className="mb-1 flex items-center gap-2 text-[#e0b45d]">
                <TerminalSquare className="h-4 w-4" />
                <span className="font-mono text-[10px] tracking-[0.28em]">CONTROL PLANE</span>
              </div>
              <p className="font-serif text-2xl tracking-tight text-[#f2efe5]">Cognitrix</p>
            </div>
            <span className="rounded-full border border-[#90a871]/30 bg-[#90a871]/10 px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.18em] text-[#b7c99e]">
              {meta?.environment ?? "loading"}
            </span>
          </div>

          <nav className="flex gap-1 overflow-x-auto px-3 py-3 lg:block lg:space-y-1 lg:px-4 lg:py-6">
            {NAV.map((item, index) => {
              const Icon = item.icon;
              const selected = item.id === section;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => navigate(item.id)}
                  className={`group flex min-w-[150px] items-center gap-3 rounded-md border px-3 py-3 text-left transition lg:w-full ${
                    selected
                      ? "border-[#ddb35c]/35 bg-[#ddb35c]/10 text-[#f1c876]"
                      : "border-transparent text-[#a7a496] hover:border-white/10 hover:bg-white/[0.035] hover:text-[#ece8dc]"
                  }`}
                >
                  <span className="font-mono text-[9px] text-[#666a5f]">0{index + 1}</span>
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">{item.label}</span>
                    <span className="block truncate font-mono text-[8px] tracking-[0.18em] opacity-55">
                      {item.eyebrow}
                    </span>
                  </span>
                  <ChevronRight
                    className={`ml-auto hidden h-3.5 w-3.5 lg:block ${selected ? "opacity-100" : "opacity-0 group-hover:opacity-60"}`}
                  />
                </button>
              );
            })}
          </nav>

          <div className="hidden border-t border-white/10 p-4 lg:absolute lg:inset-x-0 lg:bottom-0 lg:block">
            <div className="mb-3 rounded-md border border-white/10 bg-black/20 px-3 py-3">
              <div className="mb-1 flex items-center gap-2">
                <ShieldCheck className="h-3.5 w-3.5 text-[#90a871]" />
                <span className="font-mono text-[9px] tracking-[0.14em] text-[#90a871]">SUPERADMIN</span>
              </div>
              <p className="truncate text-sm text-[#e9e5d9]">{user.display_name}</p>
              <p className="truncate font-mono text-[9px] text-[#787b71]">{user.email}</p>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Link
                href="/"
                className="flex items-center justify-center gap-2 rounded border border-white/10 px-3 py-2 text-xs text-[#aaa79b] transition hover:bg-white/5 hover:text-white"
              >
                <ArrowLeft className="h-3.5 w-3.5" /> 工作台
              </Link>
              <button
                type="button"
                onClick={handleLogout}
                className="flex items-center justify-center gap-2 rounded border border-white/10 px-3 py-2 text-xs text-[#aaa79b] transition hover:border-[#b95d4e]/40 hover:bg-[#b95d4e]/10 hover:text-[#e68f7f]"
              >
                <LogOut className="h-3.5 w-3.5" /> 登出
              </button>
            </div>
          </div>
        </aside>

        <main className="min-w-0 flex-1">
          <header className="flex flex-col gap-4 border-b border-white/10 bg-[#0d0f0c]/80 px-5 py-6 backdrop-blur-xl sm:flex-row sm:items-end sm:justify-between lg:px-10 lg:py-8">
            <div>
              <p className="mb-2 font-mono text-[9px] tracking-[0.3em] text-[#7f8178]">
                ADMIN / {active.eyebrow}
              </p>
              <h1 className="font-serif text-3xl text-[#f1eee4] sm:text-4xl">{active.label}</h1>
            </div>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 rounded-full border border-white/10 bg-black/20 px-3 py-1.5">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#9db77b]" />
                <span className="font-mono text-[9px] tracking-[0.15em] text-[#999b91]">SYSTEM ONLINE</span>
              </div>
              <button
                type="button"
                onClick={() => void loadShell()}
                aria-label="刷新管理数据"
                className="rounded-full border border-white/10 p-2 text-[#9b9d93] transition hover:border-[#ddb35c]/40 hover:text-[#e8bd69]"
              >
                <RefreshCw className="h-4 w-4" />
              </button>
            </div>
          </header>

          {notice && (
            <div
              role="status"
              className={`mx-5 mt-5 flex items-center justify-between rounded-md border px-4 py-3 text-sm lg:mx-10 ${
                notice.kind === "ok"
                  ? "border-[#90a871]/30 bg-[#90a871]/10 text-[#c3d3ad]"
                  : "border-[#b95d4e]/35 bg-[#b95d4e]/10 text-[#eba091]"
              }`}
            >
              <span>{notice.text}</span>
              <button type="button" onClick={() => setNotice(null)} aria-label="关闭通知">
                <X className="h-4 w-4" />
              </button>
            </div>
          )}

          <div className="px-5 py-6 lg:px-10 lg:py-9">
            {section === "overview" && (
              <OverviewSection meta={meta} overview={overview} navigate={navigate} />
            )}
            {section === "users" && (
              <UsersSection currentUserId={user.id} notify={setNotice} />
            )}
            {section === "configuration" && <ConfigurationSection notify={setNotice} />}
            {section === "models" && <ModelsSection notify={setNotice} />}
            {section === "usage" && <UsageSection overview={overview} />}
            {section === "skills" && <SkillsSection notify={setNotice} />}
          </div>
        </main>
      </div>
    </div>
  );
}

function OverviewSection({
  meta,
  overview,
  navigate,
}: {
  meta: AdminMeta | null;
  overview: UsageOverview | null;
  navigate: (section: Section) => void;
}) {
  const summary = overview?.summary;
  const cards = [
    {
      label: "注册用户",
      value: formatNumber(summary?.total_users),
      sub: `${formatNumber(summary?.active_users)} 位近期活跃`,
      icon: Users,
      tone: "gold",
    },
    {
      label: "Chat Turns",
      value: formatNumber(summary?.chat_turns),
      sub: "近 30 天对话轮次",
      icon: Sparkles,
      tone: "green",
    },
    {
      label: "Tool Calls",
      value: formatNumber(summary?.tool_calls),
      sub: "Agent 工具执行",
      icon: Wrench,
      tone: "blue",
    },
    {
      label: "平均延迟",
      value: summary ? `${Math.round(summary.avg_latency_ms)}ms` : "—",
      sub: `${formatNumber(summary?.errors)} 个错误响应`,
      icon: CircleGauge,
      tone: "red",
    },
  ] as const;

  return (
    <div className="space-y-7">
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {cards.map((card) => (
          <MetricCard key={card.label} {...card} />
        ))}
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.75fr)]">
        <Panel>
          <PanelHeader
            eyebrow="30 DAY SIGNAL"
            title="使用趋势"
            action={
              <button
                type="button"
                onClick={() => navigate("usage")}
                className="font-mono text-[9px] tracking-[0.14em] text-[#d8ad58] hover:text-[#f1ca79]"
              >
                VIEW TELEMETRY →
              </button>
            }
          />
          <TrendChart rows={overview?.trend ?? []} />
        </Panel>

        <div className="space-y-5">
          <Panel>
            <PanelHeader eyebrow="RUNTIME" title="系统状态" />
            <div className="space-y-3">
              <StatusRow
                icon={ServerCog}
                label="环境"
                value={(meta?.environment ?? "—").toUpperCase()}
                ok
              />
              <StatusRow
                icon={SlidersHorizontal}
                label="可管理配置"
                value={`${meta?.settings_count ?? "—"} 项`}
                ok
              />
              <StatusRow
                icon={Wrench}
                label="Agent Skills"
                value={meta?.skills.enabled ? "已启用" : "未启用"}
                ok={Boolean(meta?.skills.enabled)}
              />
              <StatusRow
                icon={Database}
                label="用量事件"
                value={`${formatNumber(summary?.requests)} 请求`}
                ok
              />
            </div>
          </Panel>

          <button
            type="button"
            onClick={() => navigate("models")}
            className="group w-full overflow-hidden rounded-lg border border-[#ddb35c]/25 bg-[#ddb35c]/[0.07] p-5 text-left transition hover:border-[#ddb35c]/45 hover:bg-[#ddb35c]/[0.1]"
          >
            <div className="mb-6 flex items-start justify-between">
              <div className="rounded-md border border-[#ddb35c]/25 bg-[#ddb35c]/10 p-2.5 text-[#ecc56f]">
                <CloudCog className="h-5 w-5" />
              </div>
              <ChevronRight className="h-4 w-4 text-[#8e7b55] transition group-hover:translate-x-1 group-hover:text-[#e7bd65]" />
            </div>
            <p className="font-mono text-[9px] tracking-[0.2em] text-[#a38c5f]">MODEL GATEWAY</p>
            <h3 className="mt-1 font-serif text-xl text-[#f0e8d7]">连接与凭据管理</h3>
            <p className="mt-2 text-xs leading-5 text-[#8e8d83]">
              在不暴露 API Key 的前提下修改模型与验证连接。
            </p>
          </button>
        </div>
      </section>
    </div>
  );
}

function UsersSection({
  currentUserId,
  notify,
}: {
  currentUserId: string;
  notify: (notice: { kind: "ok" | "error"; text: string }) => void;
}) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async (q = query) => {
    setLoading(true);
    try {
      setUsers((await getAdminUsers(q)).users);
    } catch (error) {
      notify({ kind: "error", text: errorMessage(error) });
    } finally {
      setLoading(false);
    }
  }, [notify, query]);

  useEffect(() => {
    void load("");
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const mutate = async (userId: string, action: () => Promise<void>, message: string) => {
    setBusyId(userId);
    try {
      await action();
      await load();
      notify({ kind: "ok", text: message });
    } catch (error) {
      notify({ kind: "error", text: errorMessage(error) });
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Panel>
      <PanelHeader
        eyebrow="REGISTERED IDENTITIES"
        title="账号目录"
        action={<span className="font-mono text-[9px] text-[#777a71]">{users.length} RECORDS</span>}
      />
      <form
        className="mb-5 flex max-w-xl gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void load(query);
        }}
      >
        <label className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#6f7269]" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索邮箱或显示名称"
            aria-label="搜索用户"
            className="h-10 w-full rounded-md border border-white/10 bg-black/25 pl-10 pr-3 text-sm text-[#ede9de] placeholder:text-[#65685f] focus:border-[#d9ae59]/50 focus:outline-none"
          />
        </label>
        <button
          type="submit"
          className="rounded-md border border-[#d9ae59]/30 bg-[#d9ae59]/10 px-4 text-xs text-[#e8bd68] hover:bg-[#d9ae59]/15"
        >
          查询
        </button>
      </form>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[980px] border-collapse text-left">
          <thead>
            <tr className="border-y border-white/10 font-mono text-[9px] uppercase tracking-[0.16em] text-[#777a71]">
              <th className="px-3 py-3 font-normal">User</th>
              <th className="px-3 py-3 font-normal">Role</th>
              <th className="px-3 py-3 font-normal">Status</th>
              <th className="px-3 py-3 font-normal">Workspace</th>
              <th className="px-3 py-3 font-normal">30d Usage</th>
              <th className="px-3 py-3 font-normal">Last Login</th>
              <th className="px-3 py-3 text-right font-normal">Action</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <TableLoading columns={7} />
            ) : (
              users.map((item) => (
                <tr key={item.id} className="border-b border-white/[0.07] text-sm hover:bg-white/[0.018]">
                  <td className="px-3 py-4">
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-full border border-white/10 bg-white/[0.035] font-serif text-sm text-[#d8b163]">
                        {item.display_name.slice(0, 1).toUpperCase()}
                      </div>
                      <div>
                        <div className="font-medium text-[#e8e4d9]">
                          {item.display_name}
                          {item.id === currentUserId && (
                            <span className="ml-2 rounded border border-[#90a871]/25 px-1.5 py-0.5 font-mono text-[8px] text-[#aac18d]">
                              YOU
                            </span>
                          )}
                        </div>
                        <div className="font-mono text-[10px] text-[#777a71]">{item.email}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-4">
                    <select
                      aria-label={`${item.display_name} role`}
                      value={item.role}
                      disabled={busyId === item.id}
                      onChange={(event) =>
                        void mutate(
                          item.id,
                          () => setAdminUserRole(item.id, event.target.value),
                          `${item.display_name} 的角色已更新`,
                        )
                      }
                      className="rounded border border-white/10 bg-[#151712] px-2 py-1.5 text-xs text-[#cbc8bd] focus:border-[#d9ae59]/50 focus:outline-none"
                    >
                      {["superadmin", "admin", "hr", "pm", "viewer"].map((role) => (
                        <option key={role} value={role}>{role}</option>
                      ))}
                    </select>
                  </td>
                  <td className="px-3 py-4">
                    <StatePill active={item.status === "active"} label={item.status} />
                  </td>
                  <td className="px-3 py-4 text-[#aaa79d]">{item.workspace_count}</td>
                  <td className="px-3 py-4">
                    <div className="text-[#d9d5ca]">{formatNumber(item.usage.chat_turns)} chats</div>
                    <div className="font-mono text-[9px] text-[#6f7269]">
                      {formatNumber(item.usage.tool_calls)} tools · {formatNumber(item.usage.tokens)} tokens
                    </div>
                  </td>
                  <td className="px-3 py-4 font-mono text-[10px] text-[#85877f]">
                    {formatDate(item.last_login_at)}
                  </td>
                  <td className="px-3 py-4 text-right">
                    <button
                      type="button"
                      disabled={busyId === item.id || item.id === currentUserId}
                      onClick={() =>
                        void mutate(
                          item.id,
                          () =>
                            setAdminUserStatus(
                              item.id,
                              item.status === "active" ? "suspended" : "active",
                            ),
                          item.status === "active" ? "账号已暂停" : "账号已恢复",
                        )
                      }
                      className="rounded border border-white/10 px-3 py-1.5 text-xs text-[#aaa79d] transition hover:border-[#d9ae59]/30 hover:text-[#e7bb66] disabled:cursor-not-allowed disabled:opacity-35"
                    >
                      {busyId === item.id ? "处理中…" : item.status === "active" ? "暂停" : "恢复"}
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function ConfigurationSection({
  notify,
}: {
  notify: (notice: { kind: "ok" | "error"; text: string }) => void;
}) {
  const [settings, setSettings] = useState<AdminSetting[]>([]);
  const [category, setCategory] = useState("all");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSettings((await getAdminSettings()).settings);
    } catch (error) {
      notify({ kind: "error", text: errorMessage(error) });
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const categories = useMemo(
    () => ["all", ...Array.from(new Set(settings.map((item) => item.category)))],
    [settings],
  );
  const visible = category === "all" ? settings : settings.filter((item) => item.category === category);

  const save = async (setting: AdminSetting) => {
    const raw = drafts[setting.key] ?? "";
    setBusy(setting.key);
    try {
      await updateAdminSetting(setting.key, parseSettingValue(setting, raw));
      setDrafts((current) => withoutKey(current, setting.key));
      await load();
      notify({
        kind: "ok",
        text: `${setting.key} 已保存${setting.restart_required ? "，重启 API 后生效" : "并已热加载"}`,
      });
    } catch (error) {
      notify({ kind: "error", text: errorMessage(error) });
    } finally {
      setBusy(null);
    }
  };

  const reset = async (setting: AdminSetting) => {
    setBusy(setting.key);
    try {
      await resetAdminSetting(setting.key);
      setDrafts((current) => withoutKey(current, setting.key));
      await load();
      notify({ kind: "ok", text: `${setting.key} 已恢复环境基线` });
    } catch (error) {
      notify({ kind: "error", text: errorMessage(error) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2">
        {categories.map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => setCategory(item)}
            className={`rounded-full border px-3 py-1.5 font-mono text-[9px] uppercase tracking-[0.12em] transition ${
              item === category
                ? "border-[#d9ae59]/40 bg-[#d9ae59]/10 text-[#edc36f]"
                : "border-white/10 text-[#82857c] hover:text-[#c5c1b5]"
            }`}
          >
            {item}
          </button>
        ))}
      </div>
      <Panel>
        <PanelHeader
          eyebrow="DECLARED SETTINGS"
          title="环境与运行时配置"
          action={
            <span className="flex items-center gap-2 font-mono text-[9px] text-[#7e8178]">
              <LockKeyhole className="h-3 w-3" /> SECRET-SAFE
            </span>
          }
        />
        <div className="space-y-2">
          {loading ? (
            <InlineLoading />
          ) : (
            visible.map((setting) => (
              <SettingRow
                key={setting.key}
                setting={setting}
                draft={drafts[setting.key]}
                busy={busy === setting.key}
                onDraft={(value) => setDrafts((current) => ({ ...current, [setting.key]: value }))}
                onSave={() => void save(setting)}
                onReset={() => void reset(setting)}
              />
            ))
          )}
        </div>
      </Panel>
    </div>
  );
}

function ModelsSection({
  notify,
}: {
  notify: (notice: { kind: "ok" | "error"; text: string }) => void;
}) {
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [draft, setDraft] = useState<ModelSettingsUpdate | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<"primary" | "backup" | null>(null);
  const [testResults, setTestResults] = useState<Partial<Record<"primary" | "backup", string>>>({});

  const load = useCallback(async () => {
    try {
      const next = await getModelSettings();
      setSettings(next);
      setDraft(toModelDraft(next));
    } catch (error) {
      notify({ kind: "error", text: errorMessage(error) });
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const next = await updateModelSettings(draft);
      setSettings(next);
      setDraft(toModelDraft(next));
      notify({ kind: "ok", text: "主备模型与路由策略已保存并即时生效" });
    } catch (error) {
      notify({ kind: "error", text: errorMessage(error) });
    } finally {
      setSaving(false);
    }
  };

  const runTest = async (slot: "primary" | "backup") => {
    if (!draft) return;
    setTesting(slot);
    setTestResults((current) => ({ ...current, [slot]: undefined }));
    const prefix = slot === "primary" ? "primary" : "backup";
    try {
      const result = await testModelConnection({
        target: slot,
        protocol: "anthropic",
        provider: draft[`${prefix}_provider`],
        provider_url: draft[`${prefix}_openai_url`],
        anthropic_url: draft[`${prefix}_anthropic_url`],
        model: draft[`${prefix}_model`],
        api_key: draft[`${prefix}_api_key`] || undefined,
      });
      setTestResults((current) => ({
        ...current,
        [slot]: `PASS · ${result.model} · ${Math.round(result.latency_ms)}ms`,
      }));
      notify({ kind: "ok", text: `${slot === "primary" ? "主力" : "备选"}模型调用成功` });
    } catch (error) {
      const message = errorMessage(error);
      setTestResults((current) => ({ ...current, [slot]: `FAIL · ${message}` }));
      notify({ kind: "error", text: message });
    } finally {
      setTesting(null);
    }
  };

  const update = <K extends keyof ModelSettingsUpdate>(key: K, value: ModelSettingsUpdate[K]) => {
    setDraft((current) => current ? { ...current, [key]: value } : current);
  };

  const selectProvider = (slot: "primary" | "backup", provider: string) => {
    const profile = settings?.profiles.find((item) => item.name === provider);
    if (!profile) return;
    setDraft((current) => current ? {
      ...current,
      [`${slot}_provider`]: provider,
      [`${slot}_openai_url`]: profile.default_openai_url,
      [`${slot}_anthropic_url`]: profile.default_anthropic_url,
      [`${slot}_model`]: profile.default_model,
      [`${slot}_fast_model`]: profile.default_fast_model,
    } : current);
  };

  if (!settings || !draft) return <InlineLoading />;

  const servingBackup = settings.router.serving_slot === "backup";

  return (
    <div className="space-y-5">
      <section className={`relative overflow-hidden rounded-lg border px-5 py-4 ${
        servingBackup
          ? "border-[#c7774d]/35 bg-[#c7774d]/[0.08]"
          : "border-[#90a871]/30 bg-[#90a871]/[0.065]"
      }`}>
        <div className="absolute inset-y-0 right-0 w-1/3 bg-[radial-gradient(circle_at_right,rgba(255,255,255,0.06),transparent_68%)]" />
        <div className="relative flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className={`flex h-10 w-10 items-center justify-center rounded-full border ${
            servingBackup ? "border-[#c7774d]/40 text-[#dc8e68]" : "border-[#90a871]/40 text-[#b5ca98]"
          }`}>
            <GitBranch className="h-4 w-4" />
          </div>
          <div>
            <p className="font-mono text-[8px] tracking-[0.22em] text-[#797d72]">LIVE ROUTING STATE</p>
            <p className="mt-0.5 text-sm text-[#dedbd0]">
              当前由{servingBackup ? "备选" : "主力"}模型服务
              <span className="ml-2 font-mono text-[10px] text-[#8f9288]">
                {settings.router.slots[settings.router.serving_slot]?.model ?? "未配置"}
              </span>
            </p>
          </div>
          <div className="sm:ml-auto">
            <StatePill active={!servingBackup} label={servingBackup ? `FAILOVER · ${settings.router.cooldown_remaining_seconds}s` : "PRIMARY HEALTHY"} />
          </div>
        </div>
      </section>

      <div className="grid gap-5 2xl:grid-cols-[minmax(0,1.45fr)_minmax(350px,0.55fr)]">
        <div className="grid gap-5 xl:grid-cols-2">
          <ModelEndpointCard
            slot="primary"
            title="主力模型"
            eyebrow="01 / PRIMARY"
            profile={settings.profiles.find((item) => item.name === draft.primary_provider)}
            profiles={settings.profiles}
            draft={draft}
            keyConfigured={settings.slots.primary.api_key_configured}
            testing={testing === "primary"}
            testResult={testResults.primary}
            onProvider={(provider) => selectProvider("primary", provider)}
            onUpdate={update}
            onTest={() => void runTest("primary")}
          />
          <ModelEndpointCard
            slot="backup"
            title="备选模型"
            eyebrow="02 / FAILOVER"
            profile={settings.profiles.find((item) => item.name === draft.backup_provider)}
            profiles={settings.profiles}
            draft={draft}
            keyConfigured={settings.slots.backup.api_key_configured}
            testing={testing === "backup"}
            testResult={testResults.backup}
            inactive={!draft.backup_enabled}
            onProvider={(provider) => selectProvider("backup", provider)}
            onUpdate={update}
            onTest={() => void runTest("backup")}
          />
        </div>

        <div className="space-y-5">
          <Panel>
            <PanelHeader eyebrow="FAILOVER POLICY" title="路由与熔断" />
            <div className="space-y-4">
              <SwitchRow label="启用备选模型" detail="主力不可用时允许故障切换" checked={draft.backup_enabled} onChange={(value) => update("backup_enabled", value)} />
              <SwitchRow label="启用智能路由" detail="按失败与响应延迟自动开合熔断器" checked={draft.router_enabled} onChange={(value) => update("router_enabled", value)} />
              <ModelNumberField label="连续失败阈值" value={draft.failure_threshold} suffix="次" onChange={(value) => update("failure_threshold", value)} />
              <ModelNumberField label="主力恢复窗口" value={draft.cooldown_seconds} suffix="秒" onChange={(value) => update("cooldown_seconds", value)} />
              <ModelNumberField label="慢响应阈值" value={draft.slow_ttft_ms} suffix="ms" onChange={(value) => update("slow_ttft_ms", value)} />
            </div>
            <button
              type="button"
              onClick={() => void save()}
              disabled={saving}
              className="mt-6 flex w-full items-center justify-center gap-2 rounded-md border border-[#d9ae59]/40 bg-[#d9ae59]/12 px-4 py-3 text-sm text-[#f0c873] transition hover:bg-[#d9ae59]/20 disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {saving ? "正在应用…" : "保存并即时应用"}
            </button>
          </Panel>
        <Panel>
          <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-lg border border-[#d9ae59]/25 bg-[#d9ae59]/10 text-[#edc36f]">
            <KeyRound className="h-5 w-5" />
          </div>
          <p className="font-mono text-[9px] tracking-[0.2em] text-[#8b7b58]">WRITE-ONLY SECRETS</p>
          <h2 className="mt-1 font-serif text-xl text-[#eee9dc]">凭据不会回传浏览器</h2>
          <p className="mt-3 text-sm leading-6 text-[#8d8e86]">
            留空表示保留已保存的 Key。连接测试直接走 Agent 使用的 Anthropic Messages 协议，而不是只探测网关端口。
          </p>
        </Panel>
        </div>
      </div>
    </div>
  );
}

function ModelEndpointCard({
  slot,
  title,
  eyebrow,
  profile,
  profiles,
  draft,
  keyConfigured,
  testing,
  testResult,
  inactive = false,
  onProvider,
  onUpdate,
  onTest,
}: {
  slot: "primary" | "backup";
  title: string;
  eyebrow: string;
  profile?: ModelProviderProfile;
  profiles: ModelProviderProfile[];
  draft: ModelSettingsUpdate;
  keyConfigured: boolean;
  testing: boolean;
  testResult?: string;
  inactive?: boolean;
  onProvider: (provider: string) => void;
  onUpdate: <K extends keyof ModelSettingsUpdate>(key: K, value: ModelSettingsUpdate[K]) => void;
  onTest: () => void;
}) {
  const field = <T extends "provider" | "openai_url" | "anthropic_url" | "model" | "fast_model" | "api_key">(name: T) => `${slot}_${name}` as keyof ModelSettingsUpdate;
  const value = (name: "provider" | "openai_url" | "anthropic_url" | "model" | "fast_model" | "api_key") => String(draft[field(name)] ?? "");
  const listId = `${slot}-model-presets`;

  return (
    <Panel className={inactive ? "opacity-60" : ""}>
      <PanelHeader
        eyebrow={eyebrow}
        title={title}
        action={<StatePill active={!inactive && keyConfigured} label={inactive ? "STANDBY OFF" : keyConfigured ? "KEY READY" : "KEY REQUIRED"} />}
      />
      <div className="space-y-4">
        <ModelField label="Provider">
          <select
            aria-label={`${title} Provider`}
            value={value("provider")}
            onChange={(event) => onProvider(event.target.value)}
            className="model-control"
          >
            {profiles.map((item) => <option key={item.name} value={item.name}>{item.label}</option>)}
          </select>
        </ModelField>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
          <ModelField label="OpenAI Base URL" detail="轻量任务与结构推断">
            <input aria-label={`${title} OpenAI Base URL`} value={value("openai_url")} onChange={(event) => onUpdate(field("openai_url"), event.target.value)} className="model-control font-mono text-[10px]" placeholder={profile?.default_openai_url || "可选"} />
          </ModelField>
          <ModelField label="Anthropic Base URL" detail="Agent 主调用链">
            <input aria-label={`${title} Anthropic Base URL`} value={value("anthropic_url")} onChange={(event) => onUpdate(field("anthropic_url"), event.target.value)} className="model-control font-mono text-[10px]" placeholder={profile?.default_anthropic_url || "必填"} />
          </ModelField>
        </div>
        <ModelField label="模型">
          <input list={listId} aria-label={`${title} 模型`} value={value("model")} onChange={(event) => onUpdate(field("model"), event.target.value)} className="model-control font-mono text-[11px]" placeholder={profile?.default_model} />
          <datalist id={listId}>{profile?.models.map((model) => <option key={model} value={model} />)}</datalist>
        </ModelField>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
          <ModelField label="小 / 快模型">
            <input aria-label={`${title} 快模型`} value={value("fast_model")} onChange={(event) => onUpdate(field("fast_model"), event.target.value)} className="model-control font-mono text-[11px]" placeholder={profile?.default_fast_model} />
          </ModelField>
          <ModelField label="API Key" detail={keyConfigured ? "已保存；留空保持不变" : "尚未配置"}>
            <input type="password" autoComplete="off" aria-label={`${title} API Key`} value={value("api_key")} onChange={(event) => onUpdate(field("api_key"), event.target.value)} className="model-control font-mono text-[11px]" placeholder={keyConfigured ? "•••••••• 已配置" : "sk-…"} />
          </ModelField>
        </div>
        {profile?.notes && <p className="rounded border border-white/[0.07] bg-black/15 px-3 py-2 text-[11px] leading-5 text-[#777b71]">{profile.notes}</p>}
        <button type="button" disabled={testing || inactive} onClick={onTest} className="flex w-full items-center justify-center gap-2 rounded border border-white/10 px-3 py-2.5 text-xs text-[#b7b3a8] transition hover:border-[#90a871]/30 hover:bg-[#90a871]/[0.07] hover:text-[#c5d6ae] disabled:opacity-40">
          {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlugZap className="h-3.5 w-3.5" />}
          {testing ? "正在完成真实调用…" : `测试${title}`}
        </button>
        {testResult && <div className="rounded border border-[#90a871]/25 bg-[#90a871]/10 px-3 py-2 font-mono text-[9px] text-[#bdd1a4]">{testResult}</div>}
      </div>
    </Panel>
  );
}

function ModelField({ label, detail, children }: { label: string; detail?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 flex items-center justify-between gap-3 text-xs text-[#aaa79d]">
        {label}
        {detail && <span className="font-mono text-[7px] tracking-[0.08em] text-[#62665d]">{detail}</span>}
      </span>
      {children}
    </label>
  );
}

function SwitchRow({ label, detail, checked, onChange }: { label: string; detail: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-3 rounded border border-white/[0.07] bg-black/10 px-3 py-3">
      <input type="checkbox" className="sr-only" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span className={`relative h-5 w-9 rounded-full border transition ${checked ? "border-[#d9ae59]/45 bg-[#d9ae59]/25" : "border-white/10 bg-black/20"}`}>
        <span className={`absolute top-0.5 h-3.5 w-3.5 rounded-full transition ${checked ? "left-[18px] bg-[#edc36f]" : "left-0.5 bg-[#666a60]"}`} />
      </span>
      <span className="min-w-0">
        <span className="block text-xs text-[#d4d0c4]">{label}</span>
        <span className="block truncate text-[10px] text-[#696d64]">{detail}</span>
      </span>
    </label>
  );
}

function ModelNumberField({ label, value, suffix, onChange }: { label: string; value: number; suffix: string; onChange: (value: number) => void }) {
  return (
    <label className="grid grid-cols-[1fr_110px] items-center gap-3 text-xs text-[#aaa79d]">
      <span>{label}</span>
      <span className="relative">
        <input type="number" min={1} value={value} onChange={(event) => onChange(Math.max(1, Number(event.target.value)))} className="model-control pr-9 text-right font-mono text-[10px]" />
        <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 font-mono text-[8px] text-[#62665d]">{suffix}</span>
      </span>
    </label>
  );
}

function toModelDraft(settings: ModelSettings): ModelSettingsUpdate {
  const primary = settings.slots.primary;
  const backup = settings.slots.backup;
  return {
    primary_provider: primary.provider ?? "deepseek",
    primary_openai_url: primary.openai_url ?? "",
    primary_anthropic_url: primary.anthropic_url ?? "",
    primary_model: primary.model ?? "",
    primary_fast_model: primary.fast_model ?? primary.model ?? "",
    primary_api_key: "",
    backup_enabled: settings.configuration.backup_enabled,
    backup_provider: backup.provider ?? "yinhe",
    backup_openai_url: backup.openai_url ?? "",
    backup_anthropic_url: backup.anthropic_url ?? "",
    backup_model: backup.model ?? "",
    backup_fast_model: backup.fast_model ?? backup.model ?? "",
    backup_api_key: "",
    router_enabled: settings.configuration.router_enabled,
    failure_threshold: settings.configuration.failure_threshold,
    cooldown_seconds: settings.configuration.cooldown_seconds,
    slow_ttft_ms: settings.configuration.slow_ttft_ms,
  };
}

function UsageSection({ overview }: { overview: UsageOverview | null }) {
  const [users, setUsers] = useState<UsageUser[]>([]);
  useEffect(() => {
    void getUsageUsers(30).then((result) => setUsers(result.users)).catch(() => undefined);
  }, []);

  const summary = overview?.summary;
  return (
    <div className="space-y-5">
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="API Requests" value={formatNumber(summary?.requests)} sub="authenticated requests" icon={Activity} tone="gold" />
        <MetricCard label="Active Users" value={formatNumber(summary?.active_users)} sub="30-day unique users" icon={Users} tone="green" />
        <MetricCard label="Model Tokens" value={formatNumber((summary?.input_tokens ?? 0) + (summary?.output_tokens ?? 0))} sub={`${formatNumber(summary?.input_tokens)} in / ${formatNumber(summary?.output_tokens)} out`} icon={Bot} tone="blue" />
        <MetricCard label="Error Events" value={formatNumber(summary?.errors)} sub="HTTP 4xx/5xx" icon={CircleGauge} tone="red" />
      </section>
      <Panel>
        <PanelHeader eyebrow="UTC DAILY BUCKETS" title="请求、对话与工具调用" />
        <TrendChart rows={overview?.trend ?? []} expanded />
      </Panel>
      <Panel>
        <PanelHeader eyebrow="PER-USER BREAKDOWN" title="用户使用排行" />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="border-y border-white/10 font-mono text-[9px] uppercase tracking-[0.14em] text-[#777a71]">
              <tr>
                <th className="px-3 py-3 font-normal">User</th>
                <th className="px-3 py-3 font-normal">Requests</th>
                <th className="px-3 py-3 font-normal">Chats</th>
                <th className="px-3 py-3 font-normal">Tools</th>
                <th className="px-3 py-3 font-normal">Tokens</th>
                <th className="px-3 py-3 font-normal">Last Activity</th>
              </tr>
            </thead>
            <tbody>
              {users.map((item) => (
                <tr key={item.id} className="border-b border-white/[0.07]">
                  <td className="px-3 py-4">
                    <div className="text-[#e0ddd2]">{item.display_name}</div>
                    <div className="font-mono text-[9px] text-[#73766d]">{item.email}</div>
                  </td>
                  <td className="px-3 py-4 text-[#aaa79d]">{formatNumber(item.requests)}</td>
                  <td className="px-3 py-4 text-[#e3b85f]">{formatNumber(item.chat_turns)}</td>
                  <td className="px-3 py-4 text-[#aaa79d]">{formatNumber(item.tool_calls)}</td>
                  <td className="px-3 py-4 text-[#aaa79d]">{formatNumber(item.tokens)}</td>
                  <td className="px-3 py-4 font-mono text-[9px] text-[#777a71]">{formatDate(item.last_activity_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function SkillsSection({
  notify,
}: {
  notify: (notice: { kind: "ok" | "error"; text: string }) => void;
}) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [meta, setMeta] = useState<Awaited<ReturnType<typeof getSkillsMeta>> | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [skillResult, metaResult] = await Promise.all([listSkills(), getSkillsMeta()]);
      setSkills(skillResult.skills);
      setMeta(metaResult);
    } catch (error) {
      notify({ kind: "error", text: errorMessage(error) });
    } finally {
      setLoading(false);
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const upload = async (file: File) => {
    setUploading(true);
    try {
      await uploadSkill(file);
      await load();
      notify({ kind: "ok", text: `${file.name} 已验证并安装` });
    } catch (error) {
      notify({ kind: "error", text: errorMessage(error) });
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const mutation = async (action: () => Promise<unknown>, message: string) => {
    try {
      await action();
      await load();
      notify({ kind: "ok", text: message });
    } catch (error) {
      notify({ kind: "error", text: errorMessage(error) });
    }
  };

  return (
    <div className="space-y-5">
      <div
        className={`flex flex-col gap-4 rounded-lg border p-5 sm:flex-row sm:items-center sm:justify-between ${
          meta?.enabled
            ? "border-[#90a871]/25 bg-[#90a871]/[0.07]"
            : "border-[#d9ae59]/25 bg-[#d9ae59]/[0.07]"
        }`}
      >
        <div className="flex items-start gap-3">
          <div className={`rounded-md p-2 ${meta?.enabled ? "bg-[#90a871]/10 text-[#b3ca95]" : "bg-[#d9ae59]/10 text-[#e8bc66]"}`}>
            <Boxes className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-serif text-xl text-[#eee9dc]">Runtime loading</h2>
              <StatePill active={Boolean(meta?.enabled)} label={meta?.enabled ? "enabled" : "disabled"} />
            </div>
            <p className="mt-1 max-w-2xl break-all font-mono text-[9px] leading-5 text-[#7f8179]">
              {meta?.directory ?? "读取技能目录…"}
            </p>
          </div>
        </div>
        <label className="flex cursor-pointer items-center justify-center gap-2 rounded-md border border-[#d9ae59]/30 bg-[#d9ae59]/10 px-4 py-2.5 text-sm text-[#e9bd68] transition hover:bg-[#d9ae59]/15">
          {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          {uploading ? "正在校验…" : "上传 ZIP Skill"}
          <input
            ref={inputRef}
            type="file"
            accept=".zip,application/zip"
            className="sr-only"
            disabled={uploading}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void upload(file);
            }}
          />
        </label>
      </div>

      <Panel>
        <PanelHeader
          eyebrow="VALIDATED BUNDLES"
          title="已安装 Skills"
          action={<span className="font-mono text-[9px] text-[#777a71]">{skills.length} INSTALLED</span>}
        />
        {loading ? (
          <InlineLoading />
        ) : skills.length === 0 ? (
          <div className="flex min-h-48 flex-col items-center justify-center rounded-md border border-dashed border-white/10 text-center">
            <Boxes className="mb-3 h-7 w-7 text-[#62655d]" />
            <p className="text-sm text-[#aaa79e]">尚未安装 Skill bundle</p>
            <p className="mt-1 font-mono text-[9px] text-[#666960]">UPLOAD A VALIDATED ZIP TO BEGIN</p>
          </div>
        ) : (
          <div className="grid gap-3 xl:grid-cols-2">
            {skills.map((skill) => (
              <article key={skill.id} className="rounded-lg border border-white/10 bg-black/15 p-4">
                <div className="mb-4 flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-serif text-lg text-[#e9e5d9]">{skill.name}</h3>
                      <StatePill active={skill.status === "enabled"} label={skill.status} />
                    </div>
                    <p className="mt-1 font-mono text-[9px] text-[#6f7269]">
                      v{skill.version || "—"} · {skill.sha256.slice(0, 12)}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      void mutation(
                        () =>
                          setSkillStatus(
                            skill.id,
                            skill.status === "enabled" ? "disabled" : "enabled",
                          ),
                        `${skill.name} 已${skill.status === "enabled" ? "停用" : "启用"}`,
                      )
                    }
                    className="rounded border border-white/10 px-3 py-1.5 text-xs text-[#aaa79d] hover:border-[#d9ae59]/30 hover:text-[#e7bb66]"
                  >
                    {skill.status === "enabled" ? "停用" : "启用"}
                  </button>
                </div>
                <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
                  {KNOWN_AGENT_NAMES.map((agent) => {
                    const assigned = skill.assignments.includes(agent);
                    return (
                      <button
                        key={agent}
                        type="button"
                        aria-pressed={assigned}
                        onClick={() =>
                          void mutation(
                            () =>
                              assigned
                                ? unassignSkill(skill.id, agent)
                                : assignSkill(skill.id, agent),
                            `${skill.name} 的 Agent 分配已更新`,
                          )
                        }
                        className={`rounded border px-2 py-2 text-left font-mono text-[8px] leading-4 transition ${
                          assigned
                            ? "border-[#90a871]/30 bg-[#90a871]/10 text-[#b9cb9f]"
                            : "border-white/10 text-[#6f7269] hover:text-[#aaa79d]"
                        }`}
                      >
                        <span className="mb-1 block">{assigned ? "● ASSIGNED" : "○ AVAILABLE"}</span>
                        {shortAgentName(agent)}
                      </button>
                    );
                  })}
                </div>
                {skill.load_error && (
                  <p className="mb-3 rounded border border-[#b95d4e]/25 bg-[#b95d4e]/10 px-3 py-2 text-xs text-[#de8d7d]">
                    {skill.load_error}
                  </p>
                )}
                <div className="flex items-center justify-between border-t border-white/[0.07] pt-3">
                  <span className="font-mono text-[8px] text-[#62655d]">
                    {new Date(skill.uploaded_at * 1000).toLocaleString()}
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      if (window.confirm(`永久删除 ${skill.name}？`)) {
                        void mutation(() => deleteSkill(skill.id), `${skill.name} 已删除`);
                      }
                    }}
                    className="text-xs text-[#8d655d] hover:text-[#e18b7b]"
                  >
                    删除
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

function SettingRow({
  setting,
  draft,
  busy,
  onDraft,
  onSave,
  onReset,
}: {
  setting: AdminSetting;
  draft: string | undefined;
  busy: boolean;
  onDraft: (value: string) => void;
  onSave: () => void;
  onReset: () => void | Promise<void>;
}) {
  const displayValue = draft ?? (setting.secret ? "" : String(setting.value ?? ""));
  return (
    <div className="grid gap-3 rounded-md border border-white/[0.08] bg-black/10 p-3 transition hover:border-white/[0.14] lg:grid-cols-[minmax(220px,0.9fr)_minmax(260px,1fr)_auto] lg:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <code className="break-all font-mono text-[11px] text-[#d7d3c8]">{setting.key}</code>
          <SourceBadge source={setting.source} />
          {setting.restart_required && (
            <span className="rounded border border-[#c7774d]/25 bg-[#c7774d]/10 px-1.5 py-0.5 font-mono text-[8px] text-[#d98c65]">
              RESTART
            </span>
          )}
          {setting.secret && <LockKeyhole className="h-3 w-3 text-[#7d8177]" />}
        </div>
        <p className="mt-1 truncate text-xs text-[#74776e]" title={setting.description}>
          {setting.description}
        </p>
      </div>
      <div>
        {setting.type === "boolean" ? (
          <select
            value={displayValue || String(setting.value)}
            onChange={(event) => onDraft(event.target.value)}
            aria-label={setting.key}
            className="h-9 w-full rounded border border-white/10 bg-[#141611] px-3 text-sm text-[#d9d5ca] focus:border-[#d9ae59]/45 focus:outline-none"
          >
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        ) : (
          <input
            type={setting.secret ? "password" : setting.type === "integer" || setting.type === "number" ? "number" : "text"}
            value={displayValue}
            step={setting.type === "number" ? "any" : undefined}
            onChange={(event) => onDraft(event.target.value)}
            aria-label={setting.key}
            placeholder={setting.secret ? setting.masked_value || "未配置" : ""}
            className="h-9 w-full rounded border border-white/10 bg-[#141611] px-3 font-mono text-[11px] text-[#d9d5ca] placeholder:text-[#666960] focus:border-[#d9ae59]/45 focus:outline-none"
          />
        )}
      </div>
      <div className="flex items-center justify-end gap-2">
        {setting.has_override && (
          <button
            type="button"
            onClick={onReset}
            aria-label={`重置 ${setting.key}`}
            className="rounded border border-white/10 p-2 text-[#777a71] hover:text-[#c7c3b7]"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={onSave}
          aria-label={`保存 ${setting.key}`}
          className="flex min-w-[74px] items-center justify-center gap-1.5 rounded border border-[#d9ae59]/30 bg-[#d9ae59]/10 px-3 py-2 text-xs text-[#e9bd68] hover:bg-[#d9ae59]/15 disabled:opacity-45"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
          保存
        </button>
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  sub,
  icon: Icon,
  tone,
}: {
  label: string;
  value: string;
  sub: string;
  icon: LucideIcon;
  tone: "gold" | "green" | "blue" | "red";
}) {
  const tones = {
    gold: "border-[#d9ae59]/22 text-[#e9bd68] bg-[#d9ae59]/[0.055]",
    green: "border-[#90a871]/22 text-[#aec68e] bg-[#90a871]/[0.055]",
    blue: "border-[#6e89ad]/22 text-[#91abd0] bg-[#6e89ad]/[0.055]",
    red: "border-[#ad6558]/22 text-[#d18375] bg-[#ad6558]/[0.055]",
  };
  return (
    <article className={`relative overflow-hidden rounded-lg border p-5 ${tones[tone]}`}>
      <div className="mb-7 flex items-center justify-between">
        <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-[#898b82]">{label}</span>
        <Icon className="h-4 w-4" />
      </div>
      <p className="font-serif text-3xl text-[#f0ede3]">{value}</p>
      <p className="mt-1 text-xs text-[#7e8178]">{sub}</p>
    </article>
  );
}

function TrendChart({ rows, expanded = false }: { rows: UsageOverview["trend"]; expanded?: boolean }) {
  const visible = rows.slice(expanded ? -30 : -14);
  const max = Math.max(1, ...visible.map((row) => row.requests + row.chat_turns + row.tool_calls));
  return (
    <div>
      <div className={`flex items-end gap-1.5 ${expanded ? "h-72" : "h-56"}`}>
        {visible.map((row) => {
          const height = Math.max(4, ((row.requests + row.chat_turns + row.tool_calls) / max) * 100);
          return (
            <div key={row.date} className="group relative flex h-full min-w-0 flex-1 items-end">
              <div
                className="w-full rounded-t-[2px] border-t border-[#ddb35c]/50 bg-gradient-to-t from-[#6e5c35]/25 to-[#ddb35c]/60 transition group-hover:to-[#f0c973]/80"
                style={{ height: `${height}%` }}
              />
              <div className="pointer-events-none absolute bottom-[calc(100%+8px)] left-1/2 z-10 hidden -translate-x-1/2 whitespace-nowrap rounded border border-white/10 bg-[#171914] px-2 py-1 font-mono text-[8px] text-[#c8c5bb] shadow-xl group-hover:block">
                {row.date} · {row.requests} req · {row.chat_turns} chat
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex justify-between border-t border-white/[0.07] pt-3 font-mono text-[8px] text-[#5f625a]">
        <span>{visible[0]?.date ?? "—"}</span>
        <span>UTC / DAILY</span>
        <span>{visible.at(-1)?.date ?? "—"}</span>
      </div>
    </div>
  );
}

function Panel({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-lg border border-white/10 bg-[#121410]/90 p-5 shadow-[0_24px_80px_rgba(0,0,0,0.18)] sm:p-6 ${className}`}>
      {children}
    </section>
  );
}

function PanelHeader({
  eyebrow,
  title,
  action,
}: {
  eyebrow: string;
  title: string;
  action?: React.ReactNode;
}) {
  return (
    <header className="mb-6 flex items-end justify-between gap-4">
      <div>
        <p className="font-mono text-[9px] tracking-[0.22em] text-[#777a71]">{eyebrow}</p>
        <h2 className="mt-1 font-serif text-2xl text-[#ece8dc]">{title}</h2>
      </div>
      {action}
    </header>
  );
}

function StatusRow({
  icon: Icon,
  label,
  value,
  ok,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  ok: boolean;
}) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-white/[0.07] bg-black/10 px-3 py-3">
      <Icon className="h-4 w-4 text-[#7d8177]" />
      <span className="text-sm text-[#aaa79d]">{label}</span>
      <span className={`ml-auto font-mono text-[9px] ${ok ? "text-[#aac18c]" : "text-[#d9ae59]"}`}>{value}</span>
    </div>
  );
}

function StatePill({ active, label }: { active: boolean; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[8px] uppercase tracking-[0.12em] ${
        active
          ? "border-[#90a871]/30 bg-[#90a871]/10 text-[#b6cb99]"
          : "border-[#b56e58]/30 bg-[#b56e58]/10 text-[#db8b75]"
      }`}
    >
      <span className={`h-1 w-1 rounded-full ${active ? "bg-[#9fb982]" : "bg-[#c87560]"}`} />
      {label}
    </span>
  );
}

function SourceBadge({ source }: { source: AdminSetting["source"] }) {
  const styles = {
    override: "border-[#d9ae59]/25 text-[#deb45f]",
    environment: "border-[#6f89aa]/25 text-[#8ba5c7]",
    default: "border-white/10 text-[#6f7269]",
  };
  return (
    <span className={`rounded border px-1.5 py-0.5 font-mono text-[7px] uppercase tracking-[0.12em] ${styles[source]}`}>
      {source}
    </span>
  );
}

function InlineLoading() {
  return (
    <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-[#777a71]">
      <Loader2 className="h-4 w-4 animate-spin" /> Loading control data…
    </div>
  );
}

function TableLoading({ columns }: { columns: number }) {
  return (
    <tr>
      <td colSpan={columns} className="py-16 text-center">
        <span className="inline-flex items-center gap-2 text-sm text-[#777a71]">
          <Loader2 className="h-4 w-4 animate-spin" /> 读取账号目录…
        </span>
      </td>
    </tr>
  );
}

function AdminLoading() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[#0d0f0c]">
      <div className="text-center text-[#d9ae59]">
        <TerminalSquare className="mx-auto mb-4 h-7 w-7 animate-pulse" />
        <p className="font-mono text-[9px] tracking-[0.28em]">AUTHORIZING CONTROL PLANE</p>
      </div>
    </main>
  );
}

function parseSettingValue(setting: AdminSetting, value: string): unknown {
  if (setting.secret && value === "") return "";
  if (setting.type === "boolean") return value === "true";
  if (setting.type === "integer") return Number.parseInt(value, 10);
  if (setting.type === "number") return Number.parseFloat(value);
  return value;
}

function withoutKey(values: Record<string, string>, key: string): Record<string, string> {
  const next = { ...values };
  delete next[key];
  return next;
}

function errorMessage(error: unknown): string {
  if (error instanceof AdminControlError) return error.message;
  if (error instanceof Error) return error.message;
  return "管理操作失败";
}

function formatNumber(value: number | undefined): string {
  if (value === undefined) return "—";
  return new Intl.NumberFormat("zh-CN", { notation: value > 9999 ? "compact" : "standard" }).format(value);
}

function formatDate(value: string | null): string {
  if (!value) return "NEVER";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("zh-CN", { dateStyle: "medium", timeStyle: "short" });
}

function shortAgentName(agent: AgentName): string {
  return agent.replace("Agent", "").replace(/([a-z])([A-Z])/g, "$1 $2").toUpperCase();
}
