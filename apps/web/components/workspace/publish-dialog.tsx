"use client";

import { useState } from "react";
import { Check, Copy, ExternalLink, Globe } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { resolvePublicUrl, type PublicationState } from "@/lib/workspace/publish";
import { copyTextToClipboard } from "@/lib/clipboard";
import { useI18n } from "@/lib/i18n/context";

type Props = {
  publication: PublicationState | null;
  onPublish: () => void;
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

  return (
    <div
      data-testid="publish-panel"
      className="absolute right-0 top-full z-50 mt-1.5 w-80 rounded-lg border border-[#d8d1c1] bg-white shadow-lg"
    >
      <div className="border-b border-[#d8d1c1] px-4 py-3">
        <p className="flex items-center gap-2 text-sm font-semibold text-[#2f332f]">
          <Globe className="h-4 w-4 text-[#996b35]" />
          {t("publish.title")}
        </p>
        <p className="mt-0.5 text-xs text-[#777166]">{t("publish.anyoneWithLink")}</p>
        {modeLabel && <p className="mt-1 text-xs font-medium text-[#996b35]">{modeLabel}</p>}
      </div>

      {!isActive ? (
        <div className="space-y-3 p-4">
          <p className="text-xs text-[#777166]">{t("publish.snapshotNote")}</p>
          <Button
            size="sm"
            className="w-full"
            onClick={onPublish}
            disabled={isPublishing}
            data-testid="publish-confirm"
          >
            {isPublishing ? t("publish.publishing") : t("publish.createLink")}
          </Button>
        </div>
      ) : (
        <div className="space-y-3 p-4">
          <div className="flex items-center gap-2 rounded-md border border-[#e2dccf] bg-[#fbf8f1] px-2 py-1.5">
            <span className="flex-1 truncate text-xs text-[#2f332f]" data-testid="publish-link">
              {publicUrl}
            </span>
            <button
              type="button"
              onClick={handleCopy}
              className="shrink-0 text-[#777166] hover:text-[#996b35]"
              aria-label={t("publish.copyLink")}
              data-testid="publish-copy"
            >
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            </button>
          </div>

          <p className="text-xs text-[#777166]">
            {t("publish.snapshotTakenAt", {
              time: new Date(active!.published_at).toLocaleString(),
            })}
          </p>
          <p className="text-xs text-[#b3792e]">{t("publish.sensitiveWarning")}</p>

          <div className="flex flex-wrap gap-2">
            <a
              href={publicUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-md border border-[#d8d1c1] px-2.5 py-1 text-xs font-medium text-[#2f332f] hover:bg-[#f7f4eb]"
              data-testid="publish-preview"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              {t("publish.openPreview")}
            </a>
            <Button
              size="sm"
              variant="outline"
              onClick={onPublish}
              disabled={isPublishing}
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
