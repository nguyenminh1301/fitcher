"use client";

// First-run setup (DECISIONS §15): the steps as a list with the current one open; an answered step can be
// opened again from the list or with Back, and leaving it keeps its answer. A step that has no
// implementation yet is not listed (the api lists the steps it knows). Only an admin can answer a step.
// The Models step adds a provider, tests it and shows the models proposed for each tier, or lets the admin
// choose one among the provider's models when it proposes none; adding the provider answers the step, and the
// setup can be left after it. The Data step connects a database or a
// file and chooses its tables; it can be skipped and repeated later on the Sources page. Company documents are
// not a step: they are off until the owner turns them on on the Documents page.

import { useCallback, useEffect, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { Logo } from "@/components/brand/Logo";
import { ModelChooser } from "@/components/models/ModelChooser";
import { ProviderForm, ProviderTestButton, TestOutcome } from "@/components/models/ProviderForm";
import { InstantPack } from "@/components/setup/InstantPack";
import { SourceConnect } from "@/components/sources/SourceConnect";
import { Button } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import { Preferences } from "@/components/ui/Preferences";
import type { FitcherApi } from "@/lib/api/client";
import type { ModelTiersView, ProviderTestResult, ProviderView, SetupStatus } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

export type SetupScreenProps = {
  setup: FitcherApi["setup"];
  models: FitcherApi["models"];
  sources: FitcherApi["sources"];
  /** Whether the owner may answer the steps; false only on the sample-data demo. */
  isAdmin: boolean;
  /** Open the chat, asking `question` there when one was picked. */
  onOpenChat: (question?: string) => void;
};

function ModelsStep({ models, disabled, answered, onDone, onSkip }: {
  models: FitcherApi["models"];
  disabled: boolean;
  /** The step was answered before and is open again: leaving it keeps that answer. */
  answered: boolean;
  onDone: () => void;
  onSkip: () => void;
}) {
  const { t } = useI18n();
  const [provider, setProvider] = useState<ProviderView | null>(null);
  const [tiers, setTiers] = useState<ModelTiersView | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [test, setTest] = useState<{ result: ProviderTestResult | null; error?: string } | null>(null);

  const added = async (next: ProviderView) => {
    setProvider(next);
    setTiers(await models.tiers().catch(() => null));
  };
  // An OpenAI-compatible provider proposes no model, so its model is chosen from the ones it lists.
  const proposed = tiers?.tiers.some((tier) => tier.provider_id === provider?.id && tier.model) ?? false;
  const choosing = Boolean(provider && tiers && !proposed && !chosen);
  return (
    <section className="fc-card" aria-label={t("setup.step_models")}>
      <div className="fc-card-head"><h2 className="fc-card-title">{t("setup.modelsQuestion")}</h2></div>
      <div className="fc-card-body fc-stack">
        <p className="fc-muted" style={{ margin: 0 }}>{t("setup.modelsHint")}</p>
        {provider ? (
          <>
            <p style={{ margin: 0 }}>{t("models.added", { name: provider.name })}</p>
            {choosing && tiers ? (
              <ModelChooser models={models} provider={provider} tiers={tiers.tiers.map((tier) => tier.tier)}
                onChosen={(model) => { setChosen(model); void models.tiers().then(setTiers).catch(() => undefined); }} />
            ) : (
              <>
                <ProviderTestButton models={models} provider={provider} model={chosen ?? undefined}
                  onResult={(result, error) => setTest({ result, error })} />
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
              </>
            )}
            <div className="fc-row" style={{ gap: "var(--base-size-8)" }}>
              <Button variant={choosing ? "secondary" : "primary"} onClick={onDone}>{choosing ? t("setup.chooseLater") : t("setup.continue")}</Button>
            </div>
          </>
        ) : disabled ? null : (
          <>
            <ProviderForm models={models} onAdded={(next) => void added(next)} />
            <div><Button onClick={onSkip}>{answered ? t("setup.keepAnswer") : t("setup.skip")}</Button></div>
          </>
        )}
      </div>
    </section>
  );
}

function DataStep({ sources, disabled, answered, onDone, onSkip, onAsk }: {
  sources: FitcherApi["sources"]; disabled: boolean; answered: boolean; onDone: () => void; onSkip: () => void;
  /** The pack is ready: finish the setup and open the chat, asking `question` when one was picked. */
  onAsk: (question?: string) => void;
}) {
  const { t } = useI18n();
  const [connected, setConnected] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [synced, setSynced] = useState(false);
  return (
    <>
      <section className="fc-card" aria-label={t("setup.step_data")}>
        <div className="fc-card-head"><h2 className="fc-card-title">{t("setup.dataQuestion")}</h2></div>
        <div className="fc-card-body fc-stack">
          <p className="fc-muted" style={{ margin: 0 }}>{t("setup.dataHint")}</p>
          {disabled ? null : (
            <SourceConnect sources={sources} preselect onConnected={(source) => setConnected(source.id)}
              onChosen={(tables) => { setChosen(tables.filter((table) => table.selected).map((table) => table.name)); setSynced(false); }}
              onSynced={() => setSynced(true)} />
          )}
          <div className="fc-row" style={{ gap: "var(--base-size-8)" }}>
            {connected ? <Button onClick={onDone}>{t("setup.continueWithoutPack")}</Button> : null}
            {connected || disabled ? null : <Button onClick={onSkip}>{answered ? t("setup.keepAnswer") : t("setup.skip")}</Button>}
          </div>
        </div>
      </section>
      {/* The instant pack (DECISIONS §11 step 0): once the chosen tables are copied, the first question is minutes away. */}
      {connected && synced && chosen.length && !disabled ? (
        <InstantPack sources={sources} sourceId={connected} tables={chosen} onAsk={onAsk} />
      ) : null}
    </>
  );
}

export function SetupScreen({ setup, models, sources, isAdmin, onOpenChat }: SetupScreenProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [error, setError] = useState<"load" | "save" | null>(null);
  const [busy, setBusy] = useState(false);
  const fail = useCallback((kind: "load" | "save") => setError(kind), []);

  useEffect(() => {
    setup.status().then(setStatus).catch(() => fail("load"));
  }, [setup, fail]);

  const run = async (action: () => Promise<SetupStatus>) => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await action());
    } catch {
      fail("save");
    } finally {
      setBusy(false);
    }
  };

  // The open step: the first one to answer, or one opened again from the step list or with Back. The Models
  // step stays open after a provider is added, and the Data step after a source is connected, until the admin
  // has seen the test, the tiers or the tables.
  const [open, setOpen] = useState<string | null>(null);
  const pending = status?.steps.find((step) => step.state === "pending");
  const currentId = open ?? pending?.id;
  const current = status?.steps.find((step) => step.id === currentId);
  const answered = current ? current.state !== "pending" : false;
  const position = status && current ? status.steps.indexOf(current) : -1;
  const previous = position > 0 ? status?.steps[position - 1] : undefined;
  useEffect(() => {
    if (pending?.id === "models" || pending?.id === "data") setOpen(pending.id);
  }, [pending?.id]);
  const close = () => { setOpen(null); void run(() => setup.status()); };
  // Leaving a step that was answered before keeps its answer; leaving a new one skips it.
  const skip = (id: string) => {
    if (answered) return close();
    setOpen(null);
    void run(() => setup.skip(id));
  };
  const canOpen = (state: string) => isAdmin && !busy && !status?.complete && state !== "pending";
  return (
    <div className="fc-app fc-flow">
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
              <ol aria-label={t("setup.steps")} className="fc-setup-steps">
                {status.steps.map((step, index) => {
                  const here = step.id === current?.id && !status.complete;
                  const body = (
                    <>
                      <span className="fc-setup-num" data-state={step.state}>
                        {step.state === "done" ? <Icon name="check" /> : index + 1}
                      </span>
                      <span className="fc-setup-name">{t(`setup.step_${step.id}`)}</span>
                      <span className="fc-muted">{t(`setup.state_${step.state}`)}</span>
                    </>
                  );
                  return (
                    <li key={step.id} aria-current={here ? "step" : undefined}>
                      {!here && canOpen(step.state) ? (
                        <button type="button" className="fc-setup-step" aria-label={t("setup.reopen", { step: t(`setup.step_${step.id}`) })}
                          onClick={() => setOpen(step.id)}>{body}</button>
                      ) : <span className="fc-setup-step">{body}</span>}
                    </li>
                  );
                })}
              </ol>
              {previous && !status.complete && isAdmin ? (
                <div>
                  <Button variant="ghost" size="sm" icon="arrowLeft" disabled={busy} onClick={() => setOpen(previous.id)}>
                    {t("setup.back", { step: t(`setup.step_${previous.id}`) })}
                  </Button>
                </div>
              ) : null}
              {error === "save" ? <WarningBanner tone="danger">{t("setup.failed")}</WarningBanner> : null}
              <div key={status.complete ? "complete" : current?.id ?? "finish"} className="fc-enter fc-stack" style={{ gap: "var(--base-size-24)" }}>
              {status.complete ? (
                <section className="fc-card" aria-label={t("setup.finished")}>
                  <div className="fc-card-body fc-stack">
                    <p style={{ margin: 0 }}>{t("setup.finished")}</p>
                    <div><Button variant="primary" onClick={() => onOpenChat()}>{t("setup.openChat")}</Button></div>
                  </div>
                </section>
              ) : current?.id === "models" ? (
                <ModelsStep models={models} disabled={!isAdmin || busy} answered={answered}
                  onDone={close} onSkip={() => skip("models")} />
              ) : current?.id === "data" ? (
                <DataStep sources={sources} disabled={!isAdmin || busy} answered={answered}
                  onAsk={(question) => {
                    setOpen(null);
                    void run(() => setup.complete()).then(() => onOpenChat(question));
                  }}
                  onDone={close} onSkip={() => skip("data")} />
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
              </div>
            </>
          ) : null}
        </div>
      </main>
    </div>
  );
}
