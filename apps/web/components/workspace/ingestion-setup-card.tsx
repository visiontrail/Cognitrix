"use client";

import { FormEvent, useState } from "react";
import { Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/lib/i18n/context";
import type { IngestionCatalogSetupSeed, IngestionSetupQuestion } from "@/types/ingestion";

type IngestionSetupCardProps = {
  initialSeed: IngestionCatalogSetupSeed;
  setupQuestions?: IngestionSetupQuestion[];
  agentConfidence?: number;
  isSubmitting?: boolean;
  onConfirm: (seed: IngestionCatalogSetupSeed) => void | Promise<void>;
  onCancel?: () => void;
};

type BusinessType = "roster" | "project_progress" | "attendance" | "other";
type WriteMode = "new_table" | "update_existing" | "time_partitioned_new_table";
type TimeGrain = "none" | "month" | "quarter" | "year";

function normalizeTableName(raw: string, humanLabel: string): string {
  const source = raw.trim() || humanLabel.trim();
  const normalized = source
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!normalized) return "workspace_table";
  if (/^[0-9]/.test(normalized)) return `t_${normalized}`;
  return normalized;
}

type ChipOption<T extends string> = { value: T; labelKey: string };

const BUSINESS_TYPE_OPTIONS: ChipOption<BusinessType>[] = [
  { value: "roster", labelKey: "ingestion.setup.option.businessType.roster" },
  { value: "attendance", labelKey: "ingestion.setup.option.businessType.attendance" },
  { value: "project_progress", labelKey: "ingestion.setup.option.businessType.projectProgress" },
  { value: "other", labelKey: "ingestion.setup.option.businessType.other" },
];

const WRITE_MODE_OPTIONS: ChipOption<WriteMode>[] = [
  { value: "new_table", labelKey: "ingestion.setup.option.writeMode.newTable" },
  { value: "update_existing", labelKey: "ingestion.setup.option.writeMode.updateExisting" },
  { value: "time_partitioned_new_table", labelKey: "ingestion.setup.option.writeMode.timePartitionedNewTable" },
];

const TIME_GRAIN_OPTIONS: ChipOption<TimeGrain>[] = [
  { value: "month", labelKey: "ingestion.setup.option.timeGrain.month" },
  { value: "quarter", labelKey: "ingestion.setup.option.timeGrain.quarter" },
  { value: "year", labelKey: "ingestion.setup.option.timeGrain.year" },
];

function OptionChips<T extends string>({
  options,
  value,
  aiValue,
  onChange,
}: {
  options: ChipOption<T>[];
  value: T;
  aiValue: T;
  onChange: (v: T) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((opt) => {
        const isSelected = opt.value === value;
        const isAiRecommended = opt.value === aiValue;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={[
              "inline-flex items-center gap-1 rounded-full border px-3 py-1 text-[11px] font-medium transition-colors",
              isSelected
                ? "border-amber-500 bg-amber-50 text-amber-800"
                : "border-border-cream bg-parchment/60 text-stone-gray hover:border-amber-300 hover:bg-amber-50/50",
            ].join(" ")}
          >
            {isAiRecommended && (
              <Sparkles className="h-2.5 w-2.5 shrink-0 text-amber-500" />
            )}
            {t(opt.labelKey)}
          </button>
        );
      })}
    </div>
  );
}

export function IngestionSetupCard({
  initialSeed,
  setupQuestions: _setupQuestions,
  agentConfidence,
  isSubmitting = false,
  onConfirm,
  onCancel,
}: IngestionSetupCardProps) {
  const { t } = useI18n();
  const [seed, setSeed] = useState<IngestionCatalogSetupSeed>(initialSeed);
  const [validationError, setValidationError] = useState<string | null>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const humanLabel = seed.humanLabel.trim();
    if (!humanLabel) {
      setValidationError(t("ingestion.setup.validation.humanLabelRequired"));
      return;
    }
    setValidationError(null);
    onConfirm({
      ...seed,
      tableName: normalizeTableName(seed.tableName, humanLabel),
      humanLabel,
      description: seed.description.trim(),
    });
  }

  const showTimeGrain = seed.writeMode === "time_partitioned_new_table";
  const confidencePct = agentConfidence != null ? Math.round(agentConfidence * 100) : null;

  return (
    <Card
      className="flex max-h-[calc(100dvh-14rem)] flex-col overflow-hidden"
      data-testid="ingestion-setup-card"
    >
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-amber-500 shrink-0" />
          <CardTitle className="text-base">{t("ingestion.setup.title")}</CardTitle>
        </div>
        <CardDescription>{t("ingestion.setup.description")}</CardDescription>
        {confidencePct != null && (
          <p className="text-[11px] text-stone-gray">
            {t("ingestion.setup.aiConfidence", { confidence: String(confidencePct) })}
          </p>
        )}
      </CardHeader>

      <CardContent className="min-h-0 flex-1 overflow-y-auto pr-2 scrollbar-thin">
        <form className="space-y-4 pb-1" onSubmit={handleSubmit}>

          {/* Table name */}
          <div className="space-y-1">
            <p className="text-label text-stone-gray">{t("ingestion.setup.tableName")}</p>
            <div className="rounded-comfortable border border-border-cream bg-parchment/80 px-3 py-2">
              <p className="font-mono text-[12px] text-near-black">{seed.tableName}</p>
              <p className="text-[10px] text-stone-gray mt-0.5">{t("ingestion.setup.tableNameNote")}</p>
            </div>
          </div>

          {/* Display name */}
          <label className="block space-y-1 text-label text-stone-gray">
            <span>{t("ingestion.setup.humanLabel")}</span>
            <input
              type="text"
              value={seed.humanLabel}
              onChange={(e) => setSeed((prev) => ({ ...prev, humanLabel: e.target.value }))}
              placeholder={t("ingestion.setup.humanLabelPlaceholder")}
              className="w-full rounded border border-border-cream bg-white px-3 py-1.5 text-body-sm text-near-black outline-none focus:border-amber-400 focus:ring-1 focus:ring-amber-200"
            />
          </label>

          {/* Business type chips */}
          <div className="space-y-1.5">
            <p className="text-label text-stone-gray">{t("ingestion.setup.businessType")}</p>
            <OptionChips
              options={BUSINESS_TYPE_OPTIONS}
              value={seed.businessType as BusinessType}
              aiValue={initialSeed.businessType as BusinessType}
              onChange={(v) => setSeed((prev) => ({ ...prev, businessType: v }))}
            />
          </div>

          {/* Write mode chips */}
          <div className="space-y-1.5">
            <p className="text-label text-stone-gray">{t("ingestion.setup.writeMode")}</p>
            <OptionChips
              options={WRITE_MODE_OPTIONS}
              value={seed.writeMode as WriteMode}
              aiValue={initialSeed.writeMode as WriteMode}
              onChange={(v) => setSeed((prev) => ({ ...prev, writeMode: v, timeGrain: "none" }))}
            />
          </div>

          {/* Time grain chips — only for time-partitioned mode */}
          {showTimeGrain && (
            <div className="space-y-1.5">
              <p className="text-label text-stone-gray">{t("ingestion.setup.timeGrain")}</p>
              <OptionChips
                options={TIME_GRAIN_OPTIONS}
                value={(seed.timeGrain === "none" ? "month" : seed.timeGrain) as TimeGrain}
                aiValue={(initialSeed.timeGrain === "none" ? "month" : initialSeed.timeGrain) as TimeGrain}
                onChange={(v) => setSeed((prev) => ({ ...prev, timeGrain: v }))}
              />
            </div>
          )}

          {/* Description */}
          <label className="block space-y-1 text-label text-stone-gray">
            <span>{t("ingestion.setup.purpose")}</span>
            <Textarea
              value={seed.description}
              onChange={(e) => setSeed((prev) => ({ ...prev, description: e.target.value }))}
              rows={3}
              placeholder={t("ingestion.setup.purposePlaceholder")}
            />
          </label>

          {validationError ? (
            <p className="text-caption text-red-600" role="alert">
              {validationError}
            </p>
          ) : null}

          <div className="flex items-center gap-2 pt-1">
            <Button type="submit" size="sm" disabled={isSubmitting}>
              {isSubmitting ? t("ingestion.setup.applying") : t("ingestion.setup.apply")}
            </Button>
            {onCancel ? (
              <Button type="button" variant="ghost" size="sm" onClick={onCancel} disabled={isSubmitting}>
                {t("ingestion.setup.cancel")}
              </Button>
            ) : null}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
