"use client";

import { useI18n } from "@/lib/i18n/react";
import { useTheme, type Theme } from "@/lib/theme";

import { Segmented } from "./controls";

/** The interface language and theme switches, kept per browser. */
export function Preferences() {
  const { locale, setLocale, t } = useI18n();
  const { theme, setTheme } = useTheme();
  return (
    <div className="fc-row">
      <Segmented size="sm" label={t("language.label")} value={locale} onChange={(value) => setLocale(value as "en" | "vi")}
        options={[["en", "EN"], ["vi", "VI"]]} />
      <Segmented size="sm" label={t("theme.label")} value={theme} onChange={(value) => setTheme(value as Theme)}
        options={[["system", t("theme.system")], ["light", t("theme.light")], ["dark", t("theme.dark")]]} />
    </div>
  );
}
