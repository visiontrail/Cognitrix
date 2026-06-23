"use client";

import { useState } from "react";
import { Check, Globe, Lock, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { UserSearchInput, type UserSearchResult } from "@/components/sharing/user-search-input";
import { useI18n } from "@/lib/i18n/context";
import { cn } from "@/lib/utils";

export type VisibilityMode = "private" | "registered" | "allowlist";

export type PublishDialogResult = {
  visibility_mode: VisibilityMode;
  visibility_user_ids: string[];
  selected_users: UserSearchResult[];
};

type Props = {
  onPublish: (result: PublishDialogResult) => void;
  isPublishing?: boolean;
  initialVisibilityMode?: VisibilityMode;
  initialSelectedUsers?: UserSearchResult[];
};

const VISIBILITY_OPTIONS: {
  mode: VisibilityMode;
  icon: React.ElementType;
  labelKey: string;
  descKey: string;
}[] = [
  { mode: "private", icon: Lock, labelKey: "visibility.private", descKey: "visibility.private.desc" },
  { mode: "registered", icon: Globe, labelKey: "visibility.registered", descKey: "visibility.registered.desc" },
  { mode: "allowlist", icon: Users, labelKey: "visibility.allowlist", descKey: "visibility.allowlist.desc" },
];

export function PublishPanel({ onPublish, isPublishing, initialVisibilityMode, initialSelectedUsers }: Props) {
  const { t } = useI18n();
  const [visibilityMode, setVisibilityMode] = useState<VisibilityMode>(initialVisibilityMode ?? "private");
  const [selectedUsers, setSelectedUsers] = useState<UserSearchResult[]>(initialSelectedUsers ?? []);

  function handlePublish() {
    const users = visibilityMode === "allowlist" ? selectedUsers : [];
    onPublish({
      visibility_mode: visibilityMode,
      visibility_user_ids: users.map((u) => u.id),
      selected_users: users,
    });
  }

  function addUser(user: UserSearchResult) {
    setSelectedUsers((prev) => {
      if (prev.some((u) => u.id === user.id)) return prev;
      return [...prev, user];
    });
  }

  function removeUser(userId: string) {
    setSelectedUsers((prev) => prev.filter((u) => u.id !== userId));
  }

  const canPublish = visibilityMode !== "allowlist" || selectedUsers.length > 0;

  return (
    <div className="absolute right-0 top-full z-50 mt-1.5 w-80 rounded-lg border border-[#d8d1c1] bg-white shadow-lg">
      <div className="border-b border-[#d8d1c1] px-4 py-3">
        <p className="text-sm font-semibold text-[#2f332f]">{t("workspace.webDesign.publishSettings")}</p>
        <p className="mt-0.5 text-xs text-[#777166]">{t("workspace.webDesign.publishSettingsDescription")}</p>
      </div>

      <div className="p-3 space-y-1">
        {VISIBILITY_OPTIONS.map(({ mode, icon: Icon, labelKey, descKey }) => (
          <button
            key={mode}
            type="button"
            onClick={() => {
              setVisibilityMode(mode);
              if (mode !== "allowlist") setSelectedUsers([]);
            }}
            className={cn(
              "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left transition-colors",
              visibilityMode === mode
                ? "bg-[#fff7ed] text-[#996b35]"
                : "text-[#2f332f] hover:bg-[#f7f4eb]"
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium leading-tight">{t(labelKey)}</p>
              <p className="text-xs text-[#777166] leading-tight mt-0.5">{t(descKey)}</p>
            </div>
            {visibilityMode === mode && (
              <Check className="h-4 w-4 shrink-0 text-[#996b35]" />
            )}
          </button>
        ))}
      </div>

      {visibilityMode === "allowlist" && (
        <div className="border-t border-[#d8d1c1] px-4 py-3 space-y-2">
          <p className="text-xs font-medium text-[#2f332f]">{t("workspace.webDesign.publishUserSearch")}</p>
          <UserSearchInput
            onSelect={addUser}
            excludeIds={selectedUsers.map((u) => u.id)}
            placeholder={t("workspace.webDesign.publishUserSearchPlaceholder")}
          />
          {selectedUsers.length === 0 && (
            <p className="text-xs text-red-500">{t("workspace.webDesign.publishAllowlistRequired")}</p>
          )}
          {selectedUsers.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {selectedUsers.map((u) => (
                <span
                  key={u.id}
                  className="inline-flex items-center gap-1 rounded-full bg-[#f7f4eb] px-2 py-0.5 text-xs text-[#2f332f]"
                >
                  {u.display_name}
                  <button
                    type="button"
                    onClick={() => removeUser(u.id)}
                    className="text-[#777166] hover:text-red-500"
                    aria-label={t("workspace.webDesign.removePublishUser", { name: u.display_name })}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="border-t border-[#d8d1c1] px-4 py-3">
        <Button
          size="sm"
          className="w-full"
          onClick={handlePublish}
          disabled={!canPublish || isPublishing}
        >
          {isPublishing ? t("workspace.webDesign.publishing") : t("workspace.webDesign.confirmPublish")}
        </Button>
      </div>
    </div>
  );
}

/** @deprecated Use PublishPanel instead */
export function PublishDialog(_props: {
  open: boolean;
  onClose: () => void;
  onPublish: (result: PublishDialogResult) => void;
  isPublishing?: boolean;
}) {
  return null;
}
