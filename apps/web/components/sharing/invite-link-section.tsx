"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n/context";
import { toast } from "sonner";
import type { WorkspaceInvite } from "@/lib/workspace/collaboration";

type Props = {
  invites: WorkspaceInvite[];
  onGenerate: (role: string) => Promise<WorkspaceInvite>;
  onRevoke: (inviteId: string) => Promise<void>;
};

export function InviteLinkSection({ invites, onGenerate, onRevoke }: Props) {
  const { t } = useI18n();
  const [role, setRole] = useState("editor");
  const [generating, setGenerating] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [newInvite, setNewInvite] = useState<WorkspaceInvite | null>(null);

  const activeInvite = newInvite ?? invites.find((i) => !i.revoked_at) ?? null;

  async function handleGenerate() {
    setGenerating(true);
    try {
      const invite = await onGenerate(role);
      setNewInvite(invite);
    } catch {
      toast.error(t("collab.generateLinkFailed"));
    } finally {
      setGenerating(false);
    }
  }

  async function handleRevoke(inviteId: string) {
    setRevoking(inviteId);
    try {
      await onRevoke(inviteId);
      if (newInvite?.id === inviteId) setNewInvite(null);
    } catch {
      toast.error(t("collab.revokeLinkFailed"));
    } finally {
      setRevoking(null);
    }
  }

  async function handleCopy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      toast.success(t("collab.linkCopied"));
    } catch {
      toast.error(t("collab.copyLinkFailed"));
    }
  }

  const inviteUrl = (activeInvite as any)?.invite_url ?? null;

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">{t("collab.inviteLink")}</p>

      <div className="flex items-center gap-2">
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="text-xs border rounded px-1 py-0.5"
        >
          <option value="editor">{t("collab.roleEditor")}</option>
          <option value="viewer">{t("collab.roleViewer")}</option>
        </select>
        <Button size="sm" variant="outline" onClick={handleGenerate} disabled={generating}>
          {generating ? t("collab.generatingLink") : t("collab.generateLink")}
        </Button>
      </div>

      {inviteUrl && (
        <div className="flex items-center gap-2 rounded border bg-muted p-2 text-xs">
          <span className="flex-1 truncate">{inviteUrl}</span>
          <Button size="sm" variant="ghost" className="h-6 px-2 text-xs shrink-0"
            onClick={() => handleCopy(inviteUrl)}>
            {t("collab.copyLink")}
          </Button>
          <Button size="sm" variant="ghost" className="h-6 px-2 text-xs shrink-0 text-destructive"
            disabled={revoking === activeInvite?.id}
            onClick={() => activeInvite && handleRevoke(activeInvite.id)}>
            {t("collab.revokeLink")}
          </Button>
        </div>
      )}

      {invites.filter((i) => !i.revoked_at && i.id !== newInvite?.id).slice(0, 3).map((inv) => (
        <div key={inv.id} className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="flex-1">{inv.role === "editor" ? t("collab.roleEditor") : t("collab.roleViewer")} · {new Date(inv.expires_at).toLocaleDateString()}</span>
          <Button size="sm" variant="ghost" className="h-5 px-1 text-xs text-destructive"
            disabled={revoking === inv.id}
            onClick={() => handleRevoke(inv.id)}>
            {t("collab.revokeLink")}
          </Button>
        </div>
      ))}
    </div>
  );
}
