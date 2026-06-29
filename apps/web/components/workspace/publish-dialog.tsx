"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, Copy, ExternalLink, Globe, UserCheck, Users, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { UserSearchInput } from "@/components/sharing/user-search-input";
import {
  fetchUsersByIds,
  resolvePublicUrl,
  type PublicationState,
  type PublishVisibilityMode,
  type PublishVisibilityOptions,
  type PublishVisibilityUser,
} from "@/lib/workspace/publish";
import { copyTextToClipboard } from "@/lib/clipboard";
import { useI18n } from "@/lib/i18n/context";

type Props = {
  publication: PublicationState | null;
  onPublish: (visibility: PublishVisibilityOptions) => void;
  onCancel: () => void;
  isPublishing?: boolean;
  isCancelling?: boolean;
  modeLabel?: string;
};

export function PublishPanel({
  publication,
  onPublish,
  onCancel,
  isPublishing,
  isCancelling,
  modeLabel,
}: Props) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const isActive = Boolean(publication && publication.is_active);
  const active = isActive ? (publication as Extract<PublicationState, { is_active: true }>) : null;
  const publicUrl = active ? resolvePublicUrl(active) : "";
  const activeVisibilityMode = active?.visibility_mode ?? "public";
  const activeVisibilityUserIds = useMemo(
    () => active?.visibility_user_ids ?? [],
    [active?.visibility_user_ids]
  );
  const [visibilityMode, setVisibilityMode] = useState<PublishVisibilityMode>("public");
  const [selectedUsers, setSelectedUsers] = useState<PublishVisibilityUser[]>([]);

  useEffect(() => {
    if (!active) return;
    setVisibilityMode(activeVisibilityMode);
  }, [active, activeVisibilityMode]);

  useEffect(() => {
    if (!active || activeVisibilityMode !== "allowlist") {
      if (active && activeVisibilityMode !== "allowlist") setSelectedUsers([]);
      return;
    }
    const ids = activeVisibilityUserIds;
    if (ids.length === 0) {
      setSelectedUsers([]);
      return;
    }
    let cancelled = false;
    setSelectedUsers((current) => {
      const currentById = new Map(current.map((user) => [user.id, user]));
      return ids.map((id) => currentById.get(id) ?? {
        id,
        display_name: id,
        email_masked: "",
        job_label: "",
      });
    });
    fetchUsersByIds(ids)
      .then((users) => {
        if (!cancelled) setSelectedUsers(users);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [active, activeVisibilityMode, activeVisibilityUserIds]);

  const visibilityOptions: PublishVisibilityOptions = {
    visibility_mode: visibilityMode,
    visibility_user_ids:
      visibilityMode === "allowlist" ? selectedUsers.map((user) => user.id) : [],
  };
  const allowlistMissing = visibilityMode === "allowlist" && selectedUsers.length === 0;
  const canSubmit = !isPublishing && !allowlistMissing;
  const excludedUserIds = selectedUsers.map((user) => user.id);

  async function handleCopy() {
    if (!active) return;
    const succeeded = await copyTextToClipboard(publicUrl);
    if (succeeded) {
      setCopied(true);
      toast.success(t("publish.linkCopied"));
      window.setTimeout(() => setCopied(false), 2000);
    } else {
      toast.error(t("publish.copyFailed"));
    }
  }

  function handlePublish() {
    if (!canSubmit) return;
    onPublish(visibilityOptions);
  }

  function handleSelectUser(user: PublishVisibilityUser) {
    setSelectedUsers((current) => {
      if (current.some((item) => item.id === user.id)) return current;
      return [...current, user];
    });
  }

  function handleRemoveUser(userId: string) {
    setSelectedUsers((current) => current.filter((user) => user.id !== userId));
  }

  return (
    <div
      data-testid="publish-panel"
      className="absolute right-0 top-full z-[1000] mt-1.5 w-80 rounded-lg border border-[#d8d1c1] bg-[#ffffff] shadow-[0_18px_48px_rgba(38,35,28,0.18)] dark:border-white/15 dark:bg-[#1c1c38] dark:shadow-[0_24px_72px_rgba(0,0,0,0.48)]"
    >
      <div className="border-b border-[#d8d1c1] px-4 py-3 dark:border-white/15">
        <p className="flex items-center gap-2 text-sm font-semibold text-[#2f332f] dark:text-white">
          <Globe className="h-4 w-4 text-[#996b35] dark:text-amber-300" />
          {t("publish.title")}
        </p>
        <p className="mt-0.5 text-xs text-[#777166] dark:text-gray-300">
          {t(visibilityDescriptionKey(visibilityMode))}
        </p>
        {modeLabel && (
          <p className="mt-1 text-xs font-medium text-[#996b35] dark:text-amber-300">
            {modeLabel}
          </p>
        )}
      </div>

      {!isActive ? (
        <div className="space-y-3 p-4">
          <VisibilityControls
            value={visibilityMode}
            onChange={setVisibilityMode}
          />
          {visibilityMode === "allowlist" && (
            <AllowlistControls
              selectedUsers={selectedUsers}
              excludedUserIds={excludedUserIds}
              onSelectUser={handleSelectUser}
              onRemoveUser={handleRemoveUser}
            />
          )}
          <p className="text-xs text-[#777166] dark:text-gray-300">{t("publish.snapshotNote")}</p>
          {allowlistMissing && (
            <p className="text-xs text-[#b5483b] dark:text-red-300">{t("publish.allowlistRequired")}</p>
          )}
          <Button
            size="sm"
            className="w-full"
            onClick={handlePublish}
            disabled={!canSubmit}
            data-testid="publish-confirm"
          >
            {isPublishing ? t("publish.publishing") : t("publish.createLink")}
          </Button>
        </div>
      ) : (
        <div className="space-y-3 p-4">
          <VisibilityControls
            value={visibilityMode}
            onChange={setVisibilityMode}
          />
          {visibilityMode === "allowlist" && (
            <AllowlistControls
              selectedUsers={selectedUsers}
              excludedUserIds={excludedUserIds}
              onSelectUser={handleSelectUser}
              onRemoveUser={handleRemoveUser}
            />
          )}
          <div className="flex items-center gap-2 rounded-md border border-[#e2dccf] bg-[#fbf8f1] px-2 py-1.5 dark:border-white/15 dark:bg-[#25254d]">
            <span className="flex-1 truncate text-xs text-[#2f332f] dark:text-white" data-testid="publish-link">
              {publicUrl}
            </span>
            <button
              type="button"
              onClick={handleCopy}
              className="shrink-0 text-[#777166] hover:text-[#996b35] dark:text-gray-300 dark:hover:text-amber-300"
              aria-label={t("publish.copyLink")}
              data-testid="publish-copy"
            >
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            </button>
          </div>

          <p className="text-xs text-[#777166] dark:text-gray-300">
            {t("publish.snapshotTakenAt", {
              time: new Date(active!.published_at).toLocaleString(),
            })}
          </p>
          <p className="text-xs font-medium text-[#6d6258] dark:text-gray-200">
            {t("publish.currentVisibility", { visibility: t(visibilityLabelKey(activeVisibilityMode)) })}
          </p>
          <p className="text-xs text-[#b3792e] dark:text-amber-300">{t("publish.sensitiveWarning")}</p>
          {allowlistMissing && (
            <p className="text-xs text-[#b5483b] dark:text-red-300">{t("publish.allowlistRequired")}</p>
          )}

          <div className="flex flex-wrap gap-2">
            <a
              href={publicUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-md border border-[#d8d1c1] px-2.5 py-1 text-xs font-medium text-[#2f332f] hover:bg-[#f7f4eb] dark:border-white/15 dark:text-white dark:hover:bg-[#25254d]"
              data-testid="publish-preview"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              {t("publish.openPreview")}
            </a>
            <Button
              size="sm"
              variant="outline"
              onClick={handlePublish}
              disabled={!canSubmit}
              data-testid="publish-update"
            >
              {isPublishing ? t("publish.publishing") : t("publish.updatePublish")}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-error-crimson hover:bg-error-crimson/10"
              onClick={onCancel}
              disabled={isCancelling}
              data-testid="publish-cancel"
            >
              {isCancelling ? t("publish.cancelling") : t("publish.cancelPublish")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function VisibilityControls({
  value,
  onChange,
}: {
  value: PublishVisibilityMode;
  onChange: (value: PublishVisibilityMode) => void;
}) {
  const { t } = useI18n();
  const options: Array<{ mode: PublishVisibilityMode; icon: typeof Globe }> = [
    { mode: "public", icon: Globe },
    { mode: "registered", icon: Users },
    { mode: "allowlist", icon: UserCheck },
  ];

  return (
    <div className="grid grid-cols-3 gap-1 rounded-md border border-[#e2dccf] bg-[#fbf8f1] p-1 dark:border-white/15 dark:bg-[#25254d]">
      {options.map(({ mode, icon: Icon }) => {
        const selected = value === mode;
        return (
          <button
            key={mode}
            type="button"
            aria-pressed={selected}
            data-testid={`publish-visibility-${mode}`}
            onClick={() => onChange(mode)}
            className={`flex min-h-14 flex-col items-center justify-center gap-1 rounded px-1.5 text-center text-[11px] font-medium transition ${
              selected
                ? "bg-[#ffffff] text-[#2f332f] shadow-sm dark:bg-[#343465] dark:text-white"
                : "text-[#777166] hover:bg-white/70 hover:text-[#2f332f] dark:text-gray-300 dark:hover:bg-[#343465] dark:hover:text-white"
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
            <span className="leading-tight">{t(visibilityLabelKey(mode))}</span>
          </button>
        );
      })}
    </div>
  );
}

function AllowlistControls({
  selectedUsers,
  excludedUserIds,
  onSelectUser,
  onRemoveUser,
}: {
  selectedUsers: PublishVisibilityUser[];
  excludedUserIds: string[];
  onSelectUser: (user: PublishVisibilityUser) => void;
  onRemoveUser: (userId: string) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="space-y-2" data-testid="publish-allowlist-controls">
      <UserSearchInput
        onSelect={onSelectUser}
        excludeIds={excludedUserIds}
        placeholder={t("publish.searchUsers")}
      />
      {selectedUsers.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selectedUsers.map((user) => (
            <span
              key={user.id}
              data-testid="publish-user-chip"
              className="inline-flex max-w-full items-center gap-1 rounded-md border border-[#d8d1c1] bg-[#ffffff] px-2 py-1 text-xs text-[#2f332f] dark:border-white/15 dark:bg-[#25254d] dark:text-white"
            >
              <span className="max-w-[9rem] truncate">{user.display_name}</span>
              {user.email_masked && (
                <span className="max-w-[8rem] truncate text-[#777166] dark:text-gray-300">{user.email_masked}</span>
              )}
              <button
                type="button"
                aria-label={t("publish.removeUser", { name: user.display_name })}
                onClick={() => onRemoveUser(user.id)}
                className="ml-0.5 text-[#777166] hover:text-[#b5483b] dark:text-gray-300 dark:hover:text-red-300"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function visibilityLabelKey(mode: PublishVisibilityMode): string {
  if (mode === "registered") return "publish.visibility.registered";
  if (mode === "allowlist") return "publish.visibility.allowlist";
  return "publish.visibility.public";
}

function visibilityDescriptionKey(mode: PublishVisibilityMode): string {
  if (mode === "registered") return "publish.visibility.registeredDesc";
  if (mode === "allowlist") return "publish.visibility.allowlistDesc";
  return "publish.visibility.publicDesc";
}
