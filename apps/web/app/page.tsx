"use client";

import { Logo } from "@/components/brand/Logo";
import { Preferences } from "@/components/ui/Preferences";
import { useI18n } from "@/lib/i18n/react";

// Until the chat shell lands, the home page shows the brand and the interface preferences.
export default function Home() {
  const { t } = useI18n();
  return (
    <main className="fc-stack" style={{ maxWidth: 768, margin: "15vh auto", padding: 24 }}>
      <Logo height={40} />
      <p className="fc-muted">{t("app.tagline")}</p>
      <Preferences />
    </main>
  );
}
