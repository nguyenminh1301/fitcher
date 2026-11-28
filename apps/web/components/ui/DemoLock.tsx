"use client";

// The public demo (NEXT_PUBLIC_FITCHER_DEMO=1) runs on sample data with no api, so nothing can be connected or
// changed in it: key, password and connection fields are locked and say why. The installed app never shows these.

import type { ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { DEMO } from "@/lib/api/sources";
import { useI18n } from "@/lib/i18n/react";

/** The line under a locked key field. */
export function DemoKeyNotice({ id }: { id?: string }) {
  const { t } = useI18n();
  return <span className="fc-field-help demo-key-note" id={id} role="note"><Icon name="lock" />{t("sample.keyLocked")}</span>;
}

/** Why nothing can be connected or changed in the demo. */
export function DemoLockedBanner() {
  const { t } = useI18n();
  return <div className="fc-banner fc-banner-attention" role="note"><Icon name="lock" /><div>{t("sample.locked")}</div></div>;
}

/**
 * In the demo, disables every control of the form, after the banner unless ``banner`` is false (a page that
 * already shows it once); elsewhere renders the form as is.
 */
export function DemoLocked({ children, banner = true, demo = DEMO }: { children: ReactNode; banner?: boolean; demo?: boolean }) {
  if (!demo) return <>{children}</>;
  return (
    <>
      {banner ? <DemoLockedBanner /> : null}
      <fieldset disabled className="demo-locked">{children}</fieldset>
    </>
  );
}
