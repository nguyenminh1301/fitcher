"use client";

// First-run setup (DECISIONS §15): the steps as a list with the current one open. A step that has no
// implementation yet is not listed (the api lists the steps it knows). Only an admin can answer a step.
// The Models step adds a provider, tests it and shows the models proposed for each tier; adding the
// provider answers the step, and the setup can be left after it.

import { useCallback, useEffect, useState } from "react";

import { Logo } from "@/components/brand/Logo";
import { ProviderForm, ProviderTestButton, TestOutcome } from "@/components/models/ProviderForm";
import { Button, TextField } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import { Preferences } from "@/components/ui/Preferences";
import type { FitcherApi } from "@/lib/api/client";
import type { ModelTiersView, ProviderTestResult, ProviderView, SetupStatus } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

type Mode = NonNullable<SetupStatus["mode"]>;
const MODES: Mode[] = ["individual", "team"];

export type SetupScreenProps = {
  setup: FitcherApi["setup"];
  models: FitcherApi["models"];
  /** Whether the signed-in user may answer the steps. */
  isAdmin: boolean;
  onSignedOut: () => void;
  onOpenChat: () => void;
};

function ModelsStep({ models, disabled, onDone, onSkip }: {
  models: FitcherApi["models"];
  disabled: boolean;
  onDone: () => void;
  onSkip: () => void;
}) {
  const { t } = useI18n();
  const [provider, setProvider] = useState<ProviderView | null>(null);
  const [tiers, setTiers] = useState<ModelTiersView | null>(null);
  const [test, setTest] = useState<{ result: ProviderTestResult | null; error?: string } | null>(null);

  const added = async (next: ProviderView) => {
    setProvider(next);
    setTiers(await models.tiers().catch(() => null));
  };
  return (
    <section className="fc-card" aria-label={t("setup.step_models")}>
      <div className="fc-card-head"><h2 className="fc-card-title">{t("setup.modelsQuestion")}</h2></div>
      <div className="fc-card-body fc-stack">
        <p className="fc-muted" style={{ margin: 0 }}>{t("setup.modelsHint")}</p>
        {provider ? (
          <>
            <p style={{ margin: 0 }}>{t("models.added", { name: provider.name })}</p>
            <ProviderTestButton models={models} provider={provider} onResult={(result, error) => setTest({ result, error })} />
            {test?.result ? <TestOutcome result={test.result} /> : null}
            {test?.error ? <WarningBanner tone="danger">{t("models.testFailed", { reason: test.error })}</WarningBanner> : null}
            {tiers ? (
              <dl className="fc-kv" aria-label={t("models.proposed")}>
                {tiers.tiers.map((tier) => (
                  <div key={tier.tier} style={{ display: "contents" }}>
                    <dt className="fc-mono">{tier.tier}</dt>
                    <dd>{tier.model ?? t("models.notMapped")}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
            <div><Button variant="primary" onClick={onDone}>{t("setup.continue")}</Button></div>
          </>
        ) : disabled ? null : (
          <>
            <ProviderForm models={models} onAdded={(next) => void added(next)} />
            <div><Button onClick={onSkip}>{t("setup.skip")}</Button></div>
          </>
        )}
      </div>
    </section>
  );
}

export function SetupScreen({ setup, models, isAdmin, onSignedOut, onOpenChat }: SetupScreenProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [error, setError] = useState<"load" | "save" | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<Mode>("individual");
  // The first admin, asked for when the instance moves to team mode (DECISIONS §9); it keeps the owner's
  // conversations, and the api signs this browser in as that admin.
  const [admin, setAdmin] = useState({ email: "", display_name: "", password: "" });

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

  const [modelsOpen, setModelsOpen] = useState(false);
  const pending = status?.steps.find((step) => step.state === "pending");
  // The Models step stays open after a provider is added, until the admin has seen the test and the tiers.
  const current = modelsOpen ? { id: "models", state: "pending" as const } : pending;
  useEffect(() => {
    if (pending?.id === "models") setModelsOpen(true);
  }, [pending?.id]);
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
              ) : current?.id === "models" ? (
                <ModelsStep models={models} disabled={!isAdmin || busy}
                  onDone={() => { setModelsOpen(false); void run(() => setup.status()); }}
                  onSkip={() => { setModelsOpen(false); void run(() => setup.skip("models")); }} />
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
                    {mode === "team" && status?.mode !== "team" ? (
                      <fieldset disabled={!isAdmin || busy} style={{ border: 0, padding: 0, margin: 0 }} className="fc-stack">
                        <legend className="fc-muted" style={{ padding: 0 }}>{t("setup.firstAdmin")}</legend>
                        <TextField label={t("setup.adminEmail")} type="email" autoComplete="username" value={admin.email}
                          onChange={(event) => setAdmin({ ...admin, email: event.target.value })} />
                        <TextField label={t("setup.adminName")} autoComplete="name" value={admin.display_name}
                          onChange={(event) => setAdmin({ ...admin, display_name: event.target.value })} />
                        <TextField label={t("setup.adminPassword")} type="password" autoComplete="new-password" help={t("ui.passwordRule")}
                          value={admin.password} onChange={(event) => setAdmin({ ...admin, password: event.target.value })} />
                      </fieldset>
                    ) : null}
                    <div>
                      <Button variant="primary" disabled={!isAdmin || busy}
                        onClick={() => void run(() => (mode === "team" && status?.mode !== "team" ? setup.setMode(mode, admin) : setup.setMode(mode)))}>
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
