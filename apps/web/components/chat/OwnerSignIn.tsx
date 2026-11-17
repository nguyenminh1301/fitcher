"use client";

// Signing in with the owner password (DECISIONS §9). Shown only when the owner has set a password; without one
// the page opens the app at once.

import { type FormEvent, useEffect, useState } from "react";

import { Logo } from "@/components/brand/Logo";
import { Button, TextField } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import { Preferences } from "@/components/ui/Preferences";
import type { FitcherApi } from "@/lib/api/client";
import { OwnerSignInError } from "@/lib/api/http/owner";
import { useI18n } from "@/lib/i18n/react";

export function OwnerSignIn({ owner, onSignedIn }: { owner: FitcherApi["owner"]; onSignedIn: () => void }) {
  const { t } = useI18n();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  useEffect(() => {
    void owner.status().then((status) => {
      if (!status.password_set || status.signed_in) onSignedIn();
    }).catch(() => undefined);
  }, [owner, onSignedIn]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setRefusal(null);
    try {
      await owner.signIn(password);
      onSignedIn();
    } catch (cause) {
      const reason = cause instanceof OwnerSignInError ? cause.reason : "unavailable";
      setRefusal(t(`owner.signIn_${reason}`));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fc-app fc-flow">
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "var(--base-size-16)", padding: "var(--base-size-24) var(--base-size-24) 0" }}>
        <Logo height={24} />
        <Preferences />
      </header>
      <main style={{ flex: 1, display: "flex", justifyContent: "center", alignItems: "center", padding: "var(--base-size-32) var(--base-size-16)" }}>
        <form className="fc-card" style={{ width: "min(400px, 100%)" }} onSubmit={(event) => void submit(event)}>
          <div className="fc-card-body fc-stack" style={{ gap: "var(--base-size-16)" }}>
            <div>
              <h1 style={{ margin: 0, fontSize: 24, lineHeight: "32px", fontWeight: 600 }}>{t("owner.signInTitle")}</h1>
              <p className="fc-muted" style={{ margin: "var(--base-size-4) 0 0" }}>{t("owner.signInHint")}</p>
            </div>
            {refusal ? <WarningBanner tone="danger">{refusal}</WarningBanner> : null}
            <TextField label={t("owner.password")} type="password" autoComplete="current-password" autoFocus value={password}
              disabled={busy} onChange={(event) => setPassword(event.target.value)} />
            <Button type="submit" variant="primary" block disabled={busy || !password}>{t("owner.signIn")}</Button>
          </div>
        </form>
      </main>
    </div>
  );
}
