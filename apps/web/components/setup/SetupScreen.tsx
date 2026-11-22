"use client";

// First-run setup (DECISIONS §15) in three steps: Model, Data and Start. A bar per step sits at the top; an
// answered step is a button that opens it again, and leaving it keeps its answer. The Model step adds a provider
// and checks it at once (ModelStep); adding a provider answers the step. The Data step connects a file or a
// database and chooses its tables (DataStep); saving a source answers it. Start builds the first pack from the
// tables chosen here (StartStep), or lists what is still missing when a step was left for later. Leaving the
// setup for the chat or the console completes it. Company documents are not a step: they are off until the
// owner turns them on on the Documents page.

import { useCallback, useEffect, useState } from "react";

import { DataStep, type Chosen } from "@/components/setup/DataStep";
import { ModelStep } from "@/components/setup/ModelStep";
import { SetupShell, type ShellStep } from "@/components/setup/SetupShell";
import { LeftScreen, StartStep } from "@/components/setup/StartStep";
import type { FitcherApi } from "@/lib/api/client";
import type { SetupStatus } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

type Missing = "model" | "data" | "pack";

export type SetupScreenProps = {
  setup: FitcherApi["setup"];
  models: FitcherApi["models"];
  sources: FitcherApi["sources"];
  /** Whether a pack is active, for the list of what is still missing. */
  hasPack: () => Promise<boolean>;
  /** Open the chat, asking ``question`` there when one was picked. */
  onOpenChat: (question?: string) => void;
  /** Open the console, on ``path`` when given. */
  onOpenConsole: (path?: string) => void;
};

export function SetupScreen({ setup, models, sources, hasPack, onOpenChat, onOpenConsole }: SetupScreenProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [error, setError] = useState<"load" | "save" | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Chosen | null>(null);
  const [missing, setMissing] = useState<Missing[] | null>(null);

  useEffect(() => {
    setup.status().then(setStatus).catch(() => setError("load"));
  }, [setup]);

  const run = useCallback(async (action: () => Promise<SetupStatus>) => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await action());
      return true;
    } catch {
      setError("save");
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  // The open step: one opened again from its bar, else the first one to answer, else Start.
  const pending = status?.steps.find((step) => step.state === "pending");
  const currentId = open ?? pending?.id ?? "start";
  const current = status?.steps.find((step) => step.id === currentId);
  const answered = current ? current.state !== "pending" : false;
  const position = status && current ? status.steps.indexOf(current) : -1;
  const previous = position > 0 ? status?.steps[position - 1] : undefined;
  // The Models step stays open after a provider is added, and the Data step after a source is saved, until the
  // owner moves on from the check or the tables.
  useEffect(() => {
    if (pending?.id === "models" || pending?.id === "data") setOpen(pending.id);
  }, [pending?.id]);

  // Without tables chosen in this visit, Start lists what is still missing.
  useEffect(() => {
    if (currentId !== "start" || chosen || !status) return;
    let live = true;
    void Promise.all([
      models.providers().then((list) => list.length > 0).catch(() => true),
      sources.list().then((list) => list.length > 0).catch(() => true),
      hasPack().catch(() => true),
    ]).then(([model, data, pack]) => {
      if (live) setMissing([...(model ? [] : ["model" as const]), ...(data ? [] : ["data" as const]), ...(pack ? [] : ["pack" as const])]);
    });
    return () => { live = false; };
  }, [currentId, chosen, status, models, sources, hasPack]);

  const next = () => { setOpen(null); void run(() => setup.status()); };
  // Leaving a step that was answered before keeps its answer; leaving a new one skips it.
  const skip = (id: string) => {
    if (answered) return next();
    setOpen(null);
    void run(() => setup.skip(id));
  };
  // Leaving the setup completes it; a step left pending is skipped first.
  const leave = async (go: () => void) => {
    if (!status?.complete) {
      const ok = await run(async () => {
        for (const step of status?.steps ?? []) if (step.state === "pending") await setup.skip(step.id);
        return setup.complete();
      });
      if (!ok) return;
    }
    go();
  };

  const shellSteps: ShellStep[] = status ? [
    ...status.steps.map((step): ShellStep => ({
      id: step.id,
      state: step.id === currentId ? "current" : step.state === "pending" ? "todo" : "done",
      onOpen: step.id !== currentId && step.state !== "pending" && !busy ? () => setOpen(step.id) : undefined,
    })),
    { id: "start", state: currentId === "start" ? "current" : "todo" },
  ] : [];
  const backTo = previous ? () => setOpen(previous.id) : undefined;

  let body = null;
  if (status && currentId === "models") {
    body = <ModelStep models={models} disabled={busy} meta={null} onNext={next} onSkip={() => skip("models")} />;
  } else if (status && currentId === "data") {
    body = (
      <DataStep sources={sources} disabled={busy} meta={null} onBack={backTo} onSkip={() => skip("data")}
        onChosen={(tables) => { setChosen(tables); setOpen("start"); void run(() => setup.status()); }} />
    );
  } else if (status && chosen) {
    body = (
      <StartStep sources={sources} chosen={chosen} meta={null} onModel={() => setOpen("models")}
        onAsk={(question) => void leave(() => onOpenChat(question))} onConsole={(path) => void leave(() => onOpenConsole(path))} />
    );
  } else if (status && missing) {
    body = <LeftScreen missing={missing} meta={null} onStep={setOpen} onDone={() => void leave(() => onOpenChat())} />;
  }
  return (
    <SetupShell steps={shellSteps}>
      {error === "load" ? <div className="fc-banner fc-banner-danger" role="alert"><div>{t("setup.loadFailed")}</div></div> : null}
      {error === "save" ? <div className="fc-banner fc-banner-danger" role="alert"><div>{t("setup.failed")}</div></div> : null}
      {body ? <div key={currentId} className="fc-enter ob-step-body">{body}</div> : null}
    </SetupShell>
  );
}
