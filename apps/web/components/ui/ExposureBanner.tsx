"use client";

import { WarningBanner } from "@/components/ui/feedback";
import type { Identity } from "@/lib/api/provisional";
import { useI18n } from "@/lib/i18n/react";

/**
 * The standing warning of DECISIONS §9: an individual instance without sign-in that answers on a name
 * other than localhost is controlled by anyone who can reach that name. It cannot be dismissed. When the api
 * refused this browser outright, such as a request relayed by a reverse proxy that names a loopback host, the
 * banner gives the api's reason, which says what to change, instead of a page that never loads.
 */
export function ExposureBanner({ identity, refused = null }: { identity: Identity | null; refused?: string | null }) {
  const { t } = useI18n();
  if (refused !== null) {
    return <WarningBanner tone="danger" title={t("ui.accessRefusedTitle")}>{refused || t("ui.accessRefusedText")}</WarningBanner>;
  }
  if (!identity || !identity.exposed) return null;
  return <WarningBanner tone="danger" title={t("ui.exposedTitle")}>{t("ui.exposedText")}</WarningBanner>;
}
