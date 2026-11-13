"use client";

import { WarningBanner } from "@/components/ui/feedback";
import type { Identity } from "@/lib/api/provisional";
import { useI18n } from "@/lib/i18n/react";

/**
 * The standing warning of DECISIONS §9: an individual instance without sign-in that answers on a name
 * other than localhost is controlled by anyone who can reach that name. It cannot be dismissed.
 */
export function ExposureBanner({ identity }: { identity: Identity | null }) {
  const { t } = useI18n();
  if (!identity || identity.mode !== "individual" || !identity.exposed) return null;
  return <WarningBanner tone="danger" title={t("ui.exposedTitle")}>{t("ui.exposedText")}</WarningBanner>;
}
