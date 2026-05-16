"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useI18n } from "@/lib/i18n/context";
import { useIsSuperadmin } from "@/lib/auth/use-role";
import {
  AdminSkillsError,
  KNOWN_AGENT_NAMES,
  type AgentName,
  type Skill,
  assignSkill,
  deleteSkill,
  listSkills,
  setSkillStatus,
  unassignSkill,
  uploadSkill,
} from "@/lib/admin/skills";

type Status = "idle" | "loading" | "ready";

export default function AdminSkillsPage() {
  const { t } = useI18n();
  const isSuperadmin = useIsSuperadmin();

  const [skills, setSkills] = useState<Skill[]>([]);
  const [status, setStatus] = useState<Status>("idle");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [manifestSkill, setManifestSkill] = useState<Skill | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const refresh = useCallback(async () => {
    setStatus("loading");
    try {
      const data = await listSkills();
      setSkills(data.skills);
    } catch {
      setSkills([]);
    } finally {
      setStatus("ready");
    }
  }, []);

  useEffect(() => {
    if (isSuperadmin) {
      void refresh();
    }
  }, [isSuperadmin, refresh]);

  // Hidden route: non-superadmins (and signed-out users) see a generic 404 page.
  if (!isSuperadmin) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-white">
        <h1 className="text-3xl font-semibold text-slate-800">{t("admin.skills.notFound")}</h1>
      </main>
    );
  }

  const handleUpload = async (file: File) => {
    setUploadError(null);
    setUploading(true);
    try {
      await uploadSkill(file);
      await refresh();
    } catch (error) {
      const message =
        error instanceof AdminSkillsError ? error.message : "unknown error";
      setUploadError(t("admin.skills.uploadError", { message }));
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const handleToggleStatus = async (skill: Skill) => {
    const next = skill.status === "enabled" ? "disabled" : "enabled";
    await setSkillStatus(skill.id, next);
    await refresh();
  };

  const handleDelete = async (skill: Skill) => {
    const confirmed = window.confirm(
      t("admin.skills.deleteConfirm", { name: skill.name }),
    );
    if (!confirmed) return;
    await deleteSkill(skill.id);
    await refresh();
  };

  const handleAssignmentToggle = async (skill: Skill, agent: AgentName) => {
    const isAssigned = skill.assignments.includes(agent);
    if (isAssigned) {
      await unassignSkill(skill.id, agent);
    } else {
      await assignSkill(skill.id, agent);
    }
    await refresh();
  };

  return (
    <main className="mx-auto max-w-5xl px-6 py-10 text-slate-800">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">{t("admin.skills.title")}</h1>
        <p className="text-sm text-slate-500">{t("admin.skills.subtitle")}</p>
      </header>

      <UploadCard
        onUpload={handleUpload}
        uploading={uploading}
        uploadError={uploadError}
        fileInputRef={fileInputRef}
      />

      <SkillsTable
        skills={skills}
        status={status}
        onToggleStatus={handleToggleStatus}
        onDelete={handleDelete}
        onAssignmentToggle={handleAssignmentToggle}
        onViewManifest={setManifestSkill}
      />

      {manifestSkill && (
        <ManifestDrawer
          skill={manifestSkill}
          onClose={() => setManifestSkill(null)}
        />
      )}
    </main>
  );
}

function UploadCard({
  onUpload,
  uploading,
  uploadError,
  fileInputRef,
}: {
  onUpload: (file: File) => void | Promise<void>;
  uploading: boolean;
  uploadError: string | null;
  fileInputRef: React.MutableRefObject<HTMLInputElement | null>;
}) {
  const { t } = useI18n();
  const [dragOver, setDragOver] = useState(false);

  return (
    <section
      className={
        "mb-6 rounded-lg border-2 border-dashed p-6 transition " +
        (dragOver ? "border-emerald-400 bg-emerald-50" : "border-slate-200 bg-slate-50")
      }
      onDragOver={(event) => {
        event.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragOver(false);
        const file = event.dataTransfer.files?.[0];
        if (file) void onUpload(file);
      }}
    >
      <label className="flex flex-col items-center gap-2 text-center">
        <span className="text-base font-medium">{t("admin.skills.upload")}</span>
        <span className="text-sm text-slate-500">{t("admin.skills.uploadHint")}</span>
        <input
          ref={fileInputRef}
          type="file"
          accept=".zip,application/zip"
          className="mt-2 block"
          aria-label={t("admin.skills.upload")}
          disabled={uploading}
          onChange={(event) => {
            const file = event.currentTarget.files?.[0];
            if (file) void onUpload(file);
          }}
        />
        {uploading && (
          <span className="text-sm text-slate-500">{t("admin.skills.uploading")}</span>
        )}
        {uploadError && (
          <span className="text-sm text-rose-600" role="alert">
            {uploadError}
          </span>
        )}
      </label>
    </section>
  );
}

function SkillsTable({
  skills,
  status,
  onToggleStatus,
  onDelete,
  onAssignmentToggle,
  onViewManifest,
}: {
  skills: Skill[];
  status: Status;
  onToggleStatus: (skill: Skill) => void | Promise<void>;
  onDelete: (skill: Skill) => void | Promise<void>;
  onAssignmentToggle: (skill: Skill, agent: AgentName) => void | Promise<void>;
  onViewManifest: (skill: Skill) => void;
}) {
  const { t } = useI18n();
  const headers = useMemo(
    () => [
      t("admin.skills.column.name"),
      t("admin.skills.column.version"),
      t("admin.skills.column.status"),
      t("admin.skills.column.assignments"),
      t("admin.skills.column.uploadedAt"),
      t("admin.skills.column.loadError"),
      t("admin.skills.column.actions"),
    ],
    [t],
  );

  if (status === "ready" && skills.length === 0) {
    return (
      <p className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">
        {t("admin.skills.empty")}
      </p>
    );
  }

  return (
    <table className="w-full overflow-hidden rounded-lg border border-slate-200 bg-white text-sm">
      <thead className="bg-slate-100 text-left text-xs font-medium uppercase text-slate-500">
        <tr>
          {headers.map((header) => (
            <th key={header} className="px-3 py-2">
              {header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {skills.map((skill) => (
          <tr key={skill.id} className="border-t border-slate-100">
            <td className="px-3 py-2 align-top">
              <div className="font-medium text-slate-800">{skill.name}</div>
              <div className="text-xs text-slate-400">{skill.id}</div>
            </td>
            <td className="px-3 py-2 align-top">{skill.version || "—"}</td>
            <td className="px-3 py-2 align-top">
              {skill.status === "enabled"
                ? t("admin.skills.statusEnabled")
                : t("admin.skills.statusDisabled")}
            </td>
            <td className="px-3 py-2 align-top">
              <div className="flex flex-col gap-1">
                <span className="text-xs text-slate-500">{t("admin.skills.assignTo")}</span>
                {KNOWN_AGENT_NAMES.map((agent) => (
                  <label key={agent} className="inline-flex items-center gap-1">
                    <input
                      type="checkbox"
                      checked={skill.assignments.includes(agent)}
                      aria-label={`${skill.name} ${agent}`}
                      onChange={() => void onAssignmentToggle(skill, agent)}
                    />
                    <span>{agent}</span>
                  </label>
                ))}
              </div>
            </td>
            <td className="px-3 py-2 align-top text-xs text-slate-500">
              {new Date(skill.uploaded_at * 1000).toISOString()}
            </td>
            <td className="px-3 py-2 align-top text-xs text-rose-600">
              {skill.load_error ?? "—"}
            </td>
            <td className="px-3 py-2 align-top">
              <div className="flex flex-col gap-1">
                <button
                  type="button"
                  className="rounded border border-slate-300 px-2 py-1 text-xs"
                  onClick={() => void onToggleStatus(skill)}
                >
                  {skill.status === "enabled"
                    ? t("admin.skills.action.disable")
                    : t("admin.skills.action.enable")}
                </button>
                <button
                  type="button"
                  className="rounded border border-slate-300 px-2 py-1 text-xs"
                  onClick={() => onViewManifest(skill)}
                >
                  {t("admin.skills.action.viewManifest")}
                </button>
                <button
                  type="button"
                  className="rounded border border-rose-300 px-2 py-1 text-xs text-rose-700"
                  onClick={() => void onDelete(skill)}
                >
                  {t("admin.skills.action.delete")}
                </button>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ManifestDrawer({
  skill,
  onClose,
}: {
  skill: Skill;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <aside
      className="fixed inset-y-0 right-0 z-50 w-96 overflow-y-auto border-l border-slate-200 bg-white p-6 shadow-xl"
      role="dialog"
      aria-modal="true"
      aria-label={t("admin.skills.manifestTitle", { name: skill.name })}
    >
      <header className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">
          {t("admin.skills.manifestTitle", { name: skill.name })}
        </h2>
        <button
          type="button"
          className="text-sm text-slate-500 hover:text-slate-800"
          onClick={onClose}
        >
          {t("admin.skills.close")}
        </button>
      </header>
      <pre className="overflow-x-auto rounded bg-slate-100 p-3 text-xs">
        {JSON.stringify(skill.manifest, null, 2)}
      </pre>
    </aside>
  );
}
