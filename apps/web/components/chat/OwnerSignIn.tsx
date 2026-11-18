"use client";

// Signing in with the owner password (DECISIONS §9). Shown only when the owner has set a password; without one
// the page opens the app at once. A refused password is said under the field and the field is cleared, except
// when the api could not be reached, where the typed password is kept for another try. A forgotten password
// cannot be recovered, and the page says so.

import { type FormEvent, useEffect, useRef, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { Logo } from "@/components/brand/Logo";
import { Preferences } from "@/components/ui/Preferences";
import type { FitcherApi } from "@/lib/api/client";
import { OwnerSignInError } from "@/lib/api/http/owner";
import { useI18n } from "@/lib/i18n/react";

export function OwnerSignIn({ owner, onSignedIn }: { owner: FitcherApi["owner"]; onSignedIn: () => void }) {
  const { t } = useI18n();
  const [password, setPassword] = useState("");
  const [shown, setShown] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const field = useRef<HTMLInputElement>(null);

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
      if (reason !== "unavailable") setPassword("");
    } finally {
      setBusy(false);
      field.current?.focus();
    }
  }

  return (
    <div className="fc-app signin">
      <header className="signin-top">
        <Logo height={20} />
        <Preferences />
      </header>
      <main className="signin-main">
        <form className="signin-form" onSubmit={(event) => void submit(event)}>
          <div className="signin-head">
            <div className="ob-tile"><Logo variant="symbol" height={26} /></div>
            <h1 className="signin-title">{t("owner.signInTitle")}</h1>
            <p className="fc-muted signin-sub">{t("owner.signInHint")}</p>
          </div>
          <div className="fc-field">
            <label className="fc-field-label" htmlFor="owner-password">{t("owner.ownerPassword")}</label>
            <div className="fc-input-wrap">
              <input ref={field} id="owner-password" className="fc-input fc-input-lg" type={shown ? "text" : "password"}
                autoComplete="current-password" autoFocus value={password} disabled={busy} style={{ paddingRight: 48 }}
                aria-invalid={refusal ? true : undefined} aria-describedby={refusal ? "owner-password-error" : undefined}
                onChange={(event) => setPassword(event.target.value)} />
              <button type="button" className="fc-btn fc-btn-ghost fc-btn-icon fc-input-action" aria-pressed={shown}
                aria-label={shown ? t("owner.hidePassword") : t("owner.showPassword")} onClick={() => setShown(!shown)}>
                <Icon name={shown ? "eyeOff" : "eye"} />
              </button>
            </div>
            {refusal ? (
              <span className="fc-field-error" id="owner-password-error" role="alert"><Icon name="alert" />{refusal}</span>
            ) : null}
          </div>
          <button type="submit" className="fc-btn fc-btn-primary fc-btn-xl fc-btn-block" disabled={busy || !password} aria-busy={busy || undefined}>
            {busy ? <><span className="fc-spin signin-spin" aria-hidden="true" />{t("owner.signingIn")}</> : t("owner.signIn")}
          </button>
          <p className="fc-muted signin-note">{t("owner.forgotten")}</p>
        </form>
      </main>
    </div>
  );
}
