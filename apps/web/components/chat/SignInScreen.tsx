"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { Logo } from "@/components/brand/Logo";
import { Button, TextField } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import { SampleDataBadge } from "@/components/ui/SampleDataBadge";
import { Preferences } from "@/components/ui/Preferences";
import { api } from "@/lib/api";
import type { FitcherApi } from "@/lib/api/client";
import { SignInError } from "@/lib/api/provisional";
import { isSample } from "@/lib/api/sources";
import { useI18n } from "@/lib/i18n/react";

type Props = {
  /** A sign-in through the OpenID Connect provider came back failed. */
  failed?: boolean;
  auth?: FitcherApi["auth"];
  onSignedIn?: () => void;
};

/**
 * Sign-in with an account of this instance, and with the company's provider when an admin set one up.
 * In individual mode nobody signs in, so the app opens at once; on sample data the demo identities
 * stand in.
 */
export function SignInScreen({ failed = false, auth = api.auth, onSignedIn = () => window.location.assign("/") }: Props) {
  const { t } = useI18n();
  const [pack, setPack] = useState("");
  const [oidc, setOidc] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const sample = isSample("auth");
  useEffect(() => {
    void auth.pack().then((info) => setPack(info.name)).catch(() => undefined);
    void auth.oidcEnabled().then(setOidc).catch(() => undefined);
    if (!sample) void auth.current().then((identity) => identity?.mode === "individual" && onSignedIn()).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- read once when the page opens
  }, [auth]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setRefusal(null);
    try {
      await auth.signIn(email.trim(), password);
      onSignedIn();
    } catch (error) {
      const reason = error instanceof SignInError ? error.reason : "unavailable";
      setRefusal(t(reason === "invalid" ? "ui.signInInvalid" : reason === "throttled" ? "ui.signInThrottled" : "ui.signInUnavailable"));
    } finally {
      setBusy(false);
    }
  }

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
            {refusal ? <WarningBanner tone="danger">{refusal}</WarningBanner> : null}
            <form className="fc-stack" style={{ gap: "var(--base-size-12)" }} onSubmit={(event) => void submit(event)}>
              <TextField label={t("ui.email")} type="email" autoComplete="username" required disabled={sample}
                value={email} onChange={(event) => setEmail(event.target.value)} />
              <TextField label={t("ui.password")} type="password" autoComplete="current-password" required disabled={sample}
                value={password} onChange={(event) => setPassword(event.target.value)} />
              <Button type="submit" variant="primary" size="xl" block disabled={sample || busy}>{t("ui.signIn")}</Button>
            </form>
            {oidc ? (
              <Button variant="secondary" size="xl" block icon="building" disabled={sample} onClick={() => window.location.assign("/auth/oidc/start")}>{t("ui.continueSso")}</Button>
            ) : null}
            {sample ? (
              <div className="fc-row" style={{ justifyContent: "center" }}>
                <SampleDataBadge feature="auth" />
                <Link className="fc-link" href="/">{t("sample.continue")}</Link>
              </div>
            ) : null}
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
