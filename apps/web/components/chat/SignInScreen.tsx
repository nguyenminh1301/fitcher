"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import { SampleDataBadge } from "@/components/ui/SampleDataBadge";
import { Preferences } from "@/components/ui/Preferences";
import { api } from "@/lib/api";
import { isSample } from "@/lib/api/sources";
import { useI18n } from "@/lib/i18n/react";

/** Sign-in with the company account through Keycloak; on sample data the demo identities stand in. */
export function SignInScreen({ failed = false }: { failed?: boolean }) {
  const { t } = useI18n();
  const [pack, setPack] = useState("");
  useEffect(() => {
    void api.auth.pack().then((info) => setPack(info.name)).catch(() => undefined);
  }, []);
  const sample = isSample("auth");
  return (
    <div className="fc-app" style={{ flexDirection: "column", minHeight: "100vh" }}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "var(--base-size-16)", padding: "var(--base-size-24) var(--base-size-24) 0" }}>
        <Logo height={24} />
        <Preferences />
      </header>
      <main style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "var(--base-size-48) var(--base-size-16)" }}>
        <div style={{ width: "min(400px, 100%)", display: "flex", flexDirection: "column", gap: "var(--base-size-24)" }}>
          <div style={{ textAlign: "center" }}>
            <h1 style={{ margin: 0, fontSize: 32, lineHeight: "44px", fontWeight: 600, letterSpacing: "-.01em" }}>{t("ui.welcomeBack")}</h1>
            <p style={{ margin: "var(--base-size-8) 0 0", color: "var(--fgColor-muted)", fontSize: 16, lineHeight: "24px" }}>{t("ui.signInSub", { pack })}</p>
          </div>
          <div className="fc-stack" style={{ gap: "var(--base-size-12)" }}>
            {failed ? <WarningBanner tone="danger">{t("ui.signInFailed")}</WarningBanner> : null}
            <Button variant="primary" size="xl" block icon="building" disabled={sample} onClick={() => window.location.assign("/auth/sign-in")}>{t("ui.continueSso")}</Button>
            {sample ? (
              <div className="fc-row" style={{ justifyContent: "center" }}>
                <SampleDataBadge feature="auth" />
                <Link className="fc-link" href="/">{t("sample.continue")}</Link>
              </div>
            ) : (
              <p style={{ margin: 0, textAlign: "center", fontSize: 12, lineHeight: "18px", color: "var(--fgColor-muted)" }}>{t("ui.ssoNote")}</p>
            )}
          </div>
          <div style={{ display: "flex", gap: "var(--base-size-12)", alignItems: "flex-start", padding: "var(--base-size-16)", borderRadius: "var(--borderRadius-large)", background: "var(--bgColor-muted)" }}>
            <Icon name="shieldCheck" size="lg" />
            <p style={{ margin: 0, fontSize: 14, lineHeight: "20px", color: "var(--fgColor-muted)" }}>{t("ui.signInTrust")}</p>
          </div>
        </div>
      </main>
      <footer style={{ display: "flex", justifyContent: "center", gap: "var(--base-size-8)", alignItems: "center", padding: "0 var(--base-size-16) var(--base-size-24)", fontSize: 12, color: "var(--fgColor-muted)" }}>
        {t("ui.activePack")} <code className="fc-code" style={{ color: "var(--fgColor-default)" }}>{pack}</code>
      </footer>
    </div>
  );
}
