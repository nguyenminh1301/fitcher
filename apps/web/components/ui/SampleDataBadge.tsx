"use client";

import type { Feature } from "@/lib/api/client";
import { isSample, sources as currentSources, type Sources } from "@/lib/api/sources";
import { useI18n } from "@/lib/i18n/react";

import { StatusPill } from "./feedback";
import { Tooltip } from "./feedback";

/** Marks a surface whose feature still runs on sample data, so a demo is never taken for real data. */
export function SampleDataBadge({ feature, sources = currentSources }: { feature: Feature; sources?: Partial<Sources> }) {
  const { t } = useI18n();
  if (!isSample(feature, sources)) return null;
  return (
    <Tooltip label={t("sample.tooltip")}>
      <span tabIndex={0}>
        <StatusPill status="estimate">{t("sample.badge")}</StatusPill>
      </span>
    </Tooltip>
  );
}
