"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n/context";
import type { WorkspaceMember } from "@/lib/workspace/collaboration";

type Props = {
  members: WorkspaceMember[];
  onRemove: (userId: string) => Promise<void>;
};

export function MembersList({ members, onRemove }: Props) {
  const { t } = useI18n();
  const [confirmRemoveId, setConfirmRemoveId] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);

  async function handleRemove(userId: string) {
    if (confirmRemoveId !== userId) {
      setConfirmRemoveId(userId);
      return;
    }
    setLoading(userId);
    try {
      await onRemove(userId);
      setConfirmRemoveId(null);
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="space-y-1">
      {members.map((member) => {
        const isOwner = member.role === "owner";
        return (
          <div key={member.user_id} className="flex items-center justify-between gap-2 py-1.5">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium truncate">{member.display_name}</p>
              <p className="text-xs text-[#777166] truncate">{member.email || member.user_id}</p>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              {isOwner ? (
                <span className="text-xs text-[#777166] px-2">{t("collab.roleOwner")}</span>
              ) : (
                <span className="text-xs text-[#777166] px-2">{t("collab.roleEditor")}</span>
              )}
              {!isOwner && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-xs h-6 px-2"
                  disabled={loading === member.user_id}
                  onClick={() => handleRemove(member.user_id)}
                >
                  {confirmRemoveId === member.user_id ? t("collab.confirmRemove") : t("collab.removeUser")}
                </Button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
