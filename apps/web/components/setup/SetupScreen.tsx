"use client";

// First-run setup (DECISIONS §15) in three steps: Model, Data and Start. A bar per step sits at the top; an
// answered step is a button that opens it again, and leaving it keeps its answer. Only the owner can answer a
// step (the sample-data demo cannot). The Models step adds a provider and checks it at once (ModelStep);
// adding the provider answers the step. The Data step connects a database or a file and chooses its tables;
// it can be skipped and repeated later on the Sources page. Company documents are not a step: they are off
// until the owner turns them on on the Documents page.

import { useCallback, useEffect, useState } from "react";

import { InstantPack } from "@/components/setup/InstantPack";
import { ModelStep } from "@/components/setup/ModelStep";
import { SetupShell, type ShellStep } from "@/components/setup/SetupShell";
import { SourceConnect } from "@/components/sources/SourceConnect";
import { Button } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import type { FitcherApi } from "@/lib/api/client";
import type { SetupStatus } from "@/lib/contracts";
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
  // The bars: the api's steps, then Start, which is current once every step is answered.
  const finishing = Boolean(status && (status.complete || !current));
  const shellSteps: ShellStep[] = status ? [
    ...status.steps.map((step): ShellStep => ({
      id: step.id,
      state: step.id === current?.id && !finishing ? "current" : step.state === "pending" ? "todo" : "done",
      onOpen: step.id !== current?.id && canOpen(step.state) ? () => setOpen(step.id) : undefined,
    })),
    { id: "start", state: finishing ? "current" : "todo" },
  ] : [];
  const meta = (n: number) => <p className="ob-meta">{t("onboarding.stepOf", { n, total: shellSteps.length })}</p>;
  return (
    <SetupShell steps={shellSteps} wide={current?.id === "data"}>
      {error === "load" ? <WarningBanner tone="danger">{t("setup.loadFailed")}</WarningBanner> : null}
      {!isAdmin ? <WarningBanner tone="info">{t("setup.adminOnly")}</WarningBanner> : null}
      {error === "save" ? <WarningBanner tone="danger">{t("setup.failed")}</WarningBanner> : null}
      {status ? (
        <div key={finishing ? "finish" : current?.id} className="fc-enter fc-stack" style={{ gap: "var(--base-size-24)" }}>
          {finishing ? (
            <section className="fc-card" aria-label={t("setup.finish")}>
              <div className="fc-card-body fc-stack">
                {status.complete ? <p style={{ margin: 0 }}>{t("setup.finished")}</p> : <p className="fc-muted" style={{ margin: 0 }}>{t("setup.backupNote")}</p>}
                <div>
                  {status.complete ? <Button variant="primary" onClick={() => onOpenChat()}>{t("setup.openChat")}</Button> : (
                    <Button variant="primary" disabled={!isAdmin || busy} onClick={() => void run(() => setup.complete())}>{t("setup.finish")}</Button>
                  )}
                </div>
              </div>
            </section>
          ) : current?.id === "models" ? (
            <ModelStep models={models} disabled={!isAdmin || busy} meta={meta(1)} onNext={close} onSkip={() => skip("models")} />
          ) : current?.id === "data" ? (
            <>
              {previous && isAdmin ? (
                <div>
                  <Button variant="ghost" size="sm" icon="arrowLeft" disabled={busy} onClick={() => setOpen(previous.id)}>
                    {t("setup.back", { step: t(`onboarding.step_${previous.id}`) })}
                  </Button>
                </div>
              ) : null}
              <DataStep sources={sources} disabled={!isAdmin || busy} answered={answered}
                onAsk={(question) => {
                  setOpen(null);
                  void run(() => setup.complete()).then(() => onOpenChat(question));
                }}
                onDone={close} onSkip={() => skip("data")} />
            </>
          ) : null}
        </div>
      ) : null}
    </SetupShell>
  );
}
