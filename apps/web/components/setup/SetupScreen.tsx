"use client";

// First-run setup (DECISIONS §15): the steps as a list with the current one open. A step that has no
// implementation yet is not listed (the api lists the steps it knows). Only an admin can answer a step.

import { useCallback, useEffect, useState } from "react";

import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import { Preferences } from "@/components/ui/Preferences";
import type { FitcherApi } from "@/lib/api/client";
import type { SetupStatus } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

type Mode = NonNullable<SetupStatus["mode"]>;
const MODES: Mode[] = ["individual", "team"];

export type SetupScreenProps = {
  setup: FitcherApi["setup"];
  /** Whether the signed-in user may answer the steps. */
  isAdmin: boolean;
  onSignedOut: () => void;
  onOpenChat: () => void;
};

export function SetupScreen({ setup, isAdmin, onSignedOut, onOpenChat }: SetupScreenProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [error, setError] = useState<"load" | "save" | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<Mode>("individual");

  const fail = useCallback((kind: "load" | "save", cause: unknown) => {
    if (cause instanceof Error && cause.message.includes("401")) onSignedOut();
    else setError(kind);
  }, [onSignedOut]);

  useEffect(() => {
    setup.status().then((next) => {
      setStatus(next);
      if (next.mode) setMode(next.mode);
    }).catch((cause) => fail("load", cause));
  }, [setup, fail]);

  const run = async (action: () => Promise<SetupStatus>) => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await action());
    } catch (cause) {
      fail("save", cause);
    } finally {
      setBusy(false);
    }
  };

  const current = status?.steps.find((step) => step.state === "pending");
  return (
    <div className="fc-app" style={{ flexDirection: "column", minHeight: "100vh" }}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "var(--base-size-16)", padding: "var(--base-size-24) var(--base-size-24) 0" }}>
        <Logo height={24} />
        <Preferences />
      </header>
      <main style={{ flex: 1, display: "flex", justifyContent: "center", padding: "var(--base-size-32) var(--base-size-16)" }}>
        <div className="fc-stack" style={{ width: "min(640px, 100%)", gap: "var(--base-size-24)" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 32, lineHeight: "44px", fontWeight: 600, letterSpacing: "-.01em" }}>{t("setup.title")}</h1>
            <p style={{ margin: "var(--base-size-8) 0 0", color: "var(--fgColor-muted)", fontSize: 16, lineHeight: "24px" }}>{t("setup.intro")}</p>
          </div>
          {error === "load" ? <WarningBanner tone="danger">{t("setup.loadFailed")}</WarningBanner> : null}
          {!isAdmin ? <WarningBanner tone="info">{t("setup.adminOnly")}</WarningBanner> : null}
          {status ? (
            <>
              <ol aria-label={t("setup.steps")} className="fc-stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: "var(--base-size-8)" }}>
                {status.steps.map((step) => (
                  <li key={step.id} className="fc-row" aria-current={step.id === current?.id ? "step" : undefined}
                    style={{ justifyContent: "space-between", fontWeight: step.id === current?.id ? 600 : 400 }}>
                    <span>{t(`setup.step_${step.id}`)}</span>
                    <span className="fc-muted">{t(`setup.state_${step.state}`)}</span>
                  </li>
                ))}
              </ol>
              {error === "save" ? <WarningBanner tone="danger">{t("setup.failed")}</WarningBanner> : null}
              {status.complete ? (
                <section className="fc-card" aria-label={t("setup.finished")}>
                  <div className="fc-card-body fc-stack">
                    <p style={{ margin: 0 }}>{t("setup.finished")}</p>
                    <div><Button variant="primary" onClick={onOpenChat}>{t("setup.openChat")}</Button></div>
                  </div>
                </section>
              ) : current?.id === "mode" ? (
                <section className="fc-card" aria-label={t("setup.step_mode")}>
                  <div className="fc-card-head"><h2 className="fc-card-title">{t("setup.modeQuestion")}</h2></div>
                  <div className="fc-card-body fc-stack">
                    <p className="fc-muted" style={{ margin: 0 }}>{t("setup.modeHint")}</p>
                    <fieldset disabled={!isAdmin || busy} style={{ border: 0, padding: 0, margin: 0 }} className="fc-stack">
                      <legend className="fc-muted" style={{ padding: 0 }}>{t("setup.modeQuestion")}</legend>
                      {MODES.map((option) => (
                        <label key={option} className="fc-row" style={{ alignItems: "flex-start", gap: "var(--base-size-12)" }}>
                          <input type="radio" name="mode" value={option} checked={mode === option} onChange={() => setMode(option)} />
                          <span>
                            <strong>{t(`setup.${option}`)}</strong>
                            <span className="fc-muted" style={{ display: "block" }}>{t(`setup.${option}Hint`)}</span>
                          </span>
                        </label>
                      ))}
                    </fieldset>
                    <div>
                      <Button variant="primary" disabled={!isAdmin || busy} onClick={() => void run(() => setup.setMode(mode))}>
                        {busy ? t("setup.saving") : t("setup.save")}
                      </Button>
                    </div>
                  </div>
                </section>
              ) : (
                <section className="fc-card" aria-label={t("setup.finish")}>
                  <div className="fc-card-body fc-stack">
                    <p className="fc-muted" style={{ margin: 0 }}>{t("setup.backupNote")}</p>
                    <div>
                      <Button variant="primary" disabled={!isAdmin || busy} onClick={() => void run(() => setup.complete())}>{t("setup.finish")}</Button>
                    </div>
                  </div>
                </section>
              )}
            </>
          ) : null}
        </div>
      </main>
    </div>
  );
}
