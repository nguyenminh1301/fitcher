"use client";

import { Icon } from "@/components/brand/Icon";
import { useI18n } from "@/lib/i18n/react";
import { useTheme, type Theme } from "@/lib/theme";

import { Segmented } from "./controls";

/** The interface language and theme switches, kept per browser; ``languageOnly`` leaves the theme out. */
export function Preferences({ languageOnly = false }: { languageOnly?: boolean }) {
  const { locale, setLocale, t } = useI18n();
  const { theme, setTheme } = useTheme();
  return (
    <div className="fc-row">
      <Segmented size="sm" label={t("language.label")} value={locale} onChange={(value) => setLocale(value as "en" | "vi")}
        options={[["vi", "VI"], ["en", "EN"]]} />
      {languageOnly ? null : (
        <Segmented size="sm" iconOnly label={t("theme.label")} value={theme} onChange={(value) => setTheme(value as Theme)}
          options={[["system", <Icon key="system" name="monitor" />, t("theme.system")], ["light", <Icon key="light" name="sun" />, t("theme.light")],
            ["dark", <Icon key="dark" name="moon" />, t("theme.dark")]]} />
      )}
    </div>
  );
}
