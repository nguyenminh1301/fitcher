"use client";

// The setup's Start step (DECISIONS §11 step 0). With tables chosen it builds the first pack: it waits for the
// copy of the chosen tables, says what the one paid model call sends and roughly how large it is, and starts
// only when the owner confirms. The seven build steps of the api show as five lines; a failure says which one
// and can be retried; the end offers the pack's example questions. Without a model, data or a pack, the step
// lists what is still missing instead.

import { useEffect, useState, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import type { Chosen } from "@/components/setup/DataStep";
import { StepHead } from "@/components/setup/SetupShell";
import type { FitcherApi } from "@/lib/api/client";
import { errorText } from "@/lib/api/errorText";
import type { InstantEstimate, InstantJobView, SyncView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

// The api's build steps under the five lines the page shows.
const GROUPS: [string, string[]][] = [
  ["marts", ["marts"]], ["profile", ["profile"]], ["draft", ["files", "draft", "approve"]], ["compile", ["compile"]], ["activate", ["activate"]],
];
type DotState = "done" | "running" | "failed" | "pending";

function groupState(job: InstantJobView, ids: string[]): DotState {
  const states = job.steps.filter((step) => ids.includes(step.id)).map((step) => step.state);
  if (states.includes("failed")) return "failed";
  if (states.length && states.every((state) => state === "done")) return "done";
  if (states.includes("running") || states.includes("done")) return "running";
  return "pending";
}

function Dot({ state }: { state: DotState }) {
  return (
    <span className="prog-dot" data-state={state === "pending" ? undefined : state}>
      {state === "done" ? <Icon name="check" /> : state === "failed" ? <Icon name="x" /> : null}
    </span>
  );
}

function Spinner() {
  return <span className="fc-spin fc-spinning" aria-hidden="true" />;
}

type Props = {
  sources: FitcherApi["sources"];
  chosen: Chosen;
  meta: ReactNode;
  /** Finish the setup and open the chat, asking ``question`` when one was picked. */
  onAsk: (question?: string) => void;
  /** Finish the setup and open the console, optionally on one of its pages. */
  onConsole: (path?: string) => void;
  onModel: () => void;
  /** How often the copy and the build are read again. */
  pollMs?: number;
};

export function StartStep({ sources, chosen, meta, onAsk, onConsole, onModel, pollMs = 2000 }: Props) {
  const { t, formatNumber } = useI18n();
  const sourceId = chosen.source.id;
  const names = chosen.tables.map((table) => table.name);
  const copies = chosen.tables.some((table) => table.mode === "copy");
  const [sync, setSync] = useState<SyncView | null>(null);
  const [estimate, setEstimate] = useState<InstantEstimate | null>(null);
  const [job, setJob] = useState<InstantJobView | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const copyState: "waiting" | "done" | "failed" = !sync || sync.status === "running" ? "waiting" : sync.status === "succeeded" ? "done" : "failed";

  // The analysis tables read the copies, so the pack is built only once the latest sync has finished.
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const check = async () => {
      try {
        const [latest] = await sources.syncs(sourceId);
        if (stopped) return;
        setSync(latest ?? null);
        if (latest?.status === "running") timer = setTimeout(() => void check(), pollMs);
        else if (!latest || latest.status === "succeeded") setEstimate(await sources.instantEstimate({ source_id: sourceId, tables: names }));
      } catch (cause) {
        if (!stopped) setError(errorText(cause));
      }
    };
    void check();
    return () => { stopped = true; clearTimeout(timer); };
    // The chosen tables do not change while the step is open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sources, sourceId, pollMs]);

  const jobId = job?.id;
  const running = job?.status === "running";
  useEffect(() => {
    if (!jobId || !running) return;
    const timer = setInterval(() => {
      sources.instantJob(jobId).then((reply) => setJob({ ...reply.job })).catch((cause) => setError(errorText(cause)));
    }, pollMs);
    return () => clearInterval(timer);
  }, [sources, jobId, running, pollMs]);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      setJob((await sources.instantStart({ source_id: sourceId, tables: names, confirm_billable: true })).job);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setStarting(false);
    }
  }

  const errorLine = error ? <span className="fc-field-error" role="alert"><Icon name="alert" />{error}</span> : null;

  if (job?.status === "succeeded") {
    const result = job.result;
    return (
      <>
        <StepHead icon={<Icon name="check" size="xl" />} tone="success" title={t("onboarding.ready")}>{t("onboarding.readySub")}</StepHead>
        {result?.suggested_questions?.length ? (
          <div className="fc-field">
            <span className="fc-field-label" id="try-asking">{t("onboarding.tryAsking")}</span>
            <div className="chips" role="group" aria-labelledby="try-asking">
              {result.suggested_questions.map((question) => (
                <button key={question} type="button" className="chip" onClick={() => onAsk(question)}><Icon name="message" />{question}</button>
              ))}
            </div>
            <span className="fc-field-help">{t("onboarding.tryHelp")}</span>
          </div>
        ) : null}
        {result?.slow?.length ? (
          <div className="fc-banner fc-banner-attention" role="status"><Icon name="alert" />
            <div>{t("onboarding.slow", { views: result.slow.join(", ") })}</div>
          </div>
        ) : null}
        <div className="ob-foot">
          <button type="button" className="fc-btn fc-btn-primary fc-btn-xl fc-btn-block" onClick={() => onAsk()}>{t("onboarding.openChat")}</button>
          <p className="ob-meta">{t("onboarding.backup")}</p>
          {meta}
        </div>
      </>
    );
  }

  if (job) {
    const failed = job.status === "failed";
    const failedGroup = GROUPS.find(([, ids]) => groupState(job, ids) === "failed")?.[0] ?? "marts";
    return (
      <>
        <StepHead icon={<Icon name={failed ? "alert" : "loader"} size="xl" />} title={failed ? t("onboarding.buildFailed") : t("onboarding.building")} />
        <ol className="prog" aria-label={t("onboarding.buildProgress")} aria-live="polite">
          {GROUPS.map(([group, ids]) => {
            const state = groupState(job, ids);
            return (
              <li key={group} aria-current={state === "running" ? "step" : undefined}>
                <Dot state={state} />
                <span className={state === "pending" ? "fc-muted" : undefined} style={{ flex: 1 }}>{t(`onboarding.group_${group}`)}</span>
                {state === "running" ? <span className="fc-muted">{t("onboarding.running")}</span> : null}
                {state === "failed" ? <span className="prog-failed">{t("onboarding.failedLabel")}</span> : null}
              </li>
            );
          })}
        </ol>
        {failed ? (
          <div className="fc-banner fc-banner-danger" role="alert"><Icon name="alert" />
            <div>{t("onboarding.buildFailedText", { step: t(`onboarding.group_${failedGroup}`), error: job.error ?? "" })}</div>
          </div>
        ) : null}
        {errorLine}
        <div className="ob-foot">
          {failed ? (
            <>
              <button type="button" className="fc-btn fc-btn-primary fc-btn-xl fc-btn-block" disabled={starting} onClick={() => void start()}>
                {starting ? <Spinner /> : <Icon name="refresh" />}{t("onboarding.retry")}
              </button>
              <button type="button" className="fc-textlink" onClick={() => onConsole()}>{t("onboarding.openConsole")}</button>
            </>
          ) : <button type="button" className="fc-textlink" onClick={() => onConsole()}>{t("onboarding.background")}</button>}
          {meta}
        </div>
      </>
    );
  }

  const line = (name: string, mode: string): [DotState, string] => {
    if (mode === "live") return ["done", t("onboarding.readLive")];
    if (copyState === "waiting") return ["running", t("onboarding.copying")];
    const result = sync?.results.find((row) => row.table === name);
    if (copyState === "failed" && !(result && typeof result.rows === "number")) return ["failed", t("onboarding.copyFailed")];
    return ["done", typeof result?.rows === "number" ? t("onboarding.copied", { rows: formatNumber(result.rows) }) : t("onboarding.copied", { rows: "?" })];
  };
  const missing = estimate?.model_missing;
  return (
    <>
      <StepHead icon={<Icon name="sparkles" size="xl" />} title={t("onboarding.startTitle", { count: names.length })} />
      {estimate && !missing ? (
        <p style={{ margin: 0 }}>{t("onboarding.startText", { count: formatNumber(estimate.datasets), tokens: formatNumber(estimate.prompt_tokens) })}</p>
      ) : null}
      <ol className="prog" aria-label={t("onboarding.chosenTables")}>
        {chosen.tables.map((table) => {
          const [state, text] = line(table.name, table.mode);
          return (
            <li key={table.name}>
              <Dot state={state} /><span className="fc-mono" style={{ flex: 1 }}>{table.name}</span><span className="fc-muted">{text}</span>
            </li>
          );
        })}
      </ol>
      {copyState === "failed" && copies ? (
        <div className="fc-banner fc-banner-danger" role="alert"><Icon name="alert" /><div>{t("onboarding.copyFailedBanner")}</div></div>
      ) : null}
      {missing ? (
        <div className="fc-banner fc-banner-attention" role="status"><Icon name="alert" />
          <div>{t("onboarding.modelMissing", { reason: missing })} <button type="button" className="fc-link" onClick={onModel}>{t("onboarding.toModel")}</button></div>
        </div>
      ) : null}
      {errorLine}
      <div className="ob-foot">
        {copyState === "failed" && copies ? (
          <button type="button" className="fc-btn fc-btn-xl fc-btn-block" onClick={() => onConsole("/console/sources")}>{t("onboarding.openSources")}</button>
        ) : (
          <>
            <button type="button" className="fc-btn fc-btn-primary fc-btn-xl fc-btn-block" aria-busy={starting || undefined}
              disabled={starting || !estimate || Boolean(missing)} aria-describedby={copyState === "waiting" ? "start-why" : undefined} onClick={() => void start()}>
              {starting ? <Spinner /> : null}{t("onboarding.build")}
            </button>
            {copyState === "waiting" ? <p className="ob-meta" id="start-why" role="status">{t("onboarding.waitingCopy")}</p> : null}
          </>
        )}
        <div className="ob-links"><button type="button" className="fc-textlink" onClick={() => onConsole()}>{t("onboarding.later")}</button></div>
        {meta}
      </div>
    </>
  );
}

/** What is still missing before a first question, each with the console page that adds it. */
export function LeftScreen({ missing, meta, onConsole }: { missing: ("model" | "data" | "pack")[]; meta: ReactNode; onConsole: (path?: string) => void }) {
  const { t } = useI18n();
  const PATH = { model: "/console/models", data: "/console/sources", pack: "/console/sources" };
  if (!missing.length) {
    return (
      <>
        <StepHead icon={<Icon name="check" size="xl" />} tone="success" title={t("onboarding.allSet")} />
        <div className="ob-foot">
          <button type="button" className="fc-btn fc-btn-primary fc-btn-xl fc-btn-block" onClick={() => onConsole()}>{t("onboarding.done")}</button>
          <p className="ob-meta">{t("onboarding.backup")}</p>
          {meta}
        </div>
      </>
    );
  }
  return (
    <>
      <StepHead icon={<Icon name="clipboardCheck" size="xl" />}
        title={missing.length === 1 ? t("onboarding.leftTitleOne") : t("onboarding.leftTitle", { n: missing.length })}>
        {t("onboarding.leftSub")}
      </StepHead>
      <div className="box">
        {missing.map((item) => (
          <a key={item} className="row-link" href={PATH[item]} onClick={(event) => { event.preventDefault(); onConsole(PATH[item]); }}>
            <span className="dot" style={{ background: "var(--fgColor-attention)" }} />
            <span style={{ flex: 1 }}>{t(`onboarding.missing_${item}`)}</span>
            <span className="fc-muted">{t(`onboarding.open_${item}`)}</span>
            <Icon name="chevronRight" />
          </a>
        ))}
      </div>
      <div className="ob-foot">
        <button type="button" className="fc-btn fc-btn-primary fc-btn-xl fc-btn-block" onClick={() => onConsole()}>{t("onboarding.done")}</button>
        <p className="ob-meta">{t("onboarding.backup")}</p>
        {meta}
      </div>
    </>
  );
}
