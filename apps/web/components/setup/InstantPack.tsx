"use client";

// Build the instant pack of a connected source (DECISIONS §11 step 0): wait for the copy of the chosen tables,
// show the paid draft's prompt size, start the job only when the admin confirms it, follow each step and end on
// three questions to ask. Without a model, it says what is missing instead of offering the paid call.

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/controls";
import { StatusPill, WarningBanner } from "@/components/ui/feedback";
import type { FitcherApi } from "@/lib/api/client";
import type { InstantEstimate, InstantJobView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

type Props = {
  sources: FitcherApi["sources"];
  sourceId: string;
  tables: string[];
  /** Open the chat on one of the suggested questions, or on none. */
  onAsk: (question?: string) => void;
  /** How often the copy and the job are read again. */
  pollMs?: number;
};

const PILL: Record<string, string> = { pending: "neutral", running: "running", done: "succeeded", failed: "error" };

function errorText(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

export function InstantPack({ sources, sourceId, tables, onAsk, pollMs = 2000 }: Props) {
  const { t, formatNumber } = useI18n();
  const [copy, setCopy] = useState<"waiting" | "done" | "failed">("waiting");
  const [estimate, setEstimate] = useState<InstantEstimate | null>(null);
  const [job, setJob] = useState<InstantJobView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  // The marts read the copies, so the pack is built only once the latest sync has finished.
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const check = async () => {
      try {
        const [latest] = await sources.syncs(sourceId);
        if (stopped) return;
        if (latest?.status === "running") {
          timer = setTimeout(() => void check(), pollMs);
        } else if (latest && latest.status !== "succeeded") {
          setCopy("failed");
        } else {
          setCopy("done");
          setEstimate(await sources.instantEstimate({ source_id: sourceId, tables }));
        }
      } catch (cause) {
        if (!stopped) setError(errorText(cause));
      }
    };
    void check();
    return () => { stopped = true; clearTimeout(timer); };
  }, [sources, sourceId, tables, pollMs]);

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
      setJob((await sources.instantStart({ source_id: sourceId, tables, confirm_billable: true })).job);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setStarting(false);
    }
  }

  const result = job?.status === "succeeded" ? job.result : null;
  return (
    <section className="fc-card" aria-label={t("instant.title")}>
      <div className="fc-card-head"><h2 className="fc-card-title">{t("instant.title")}</h2></div>
      <div className="fc-card-body fc-stack">
        {copy === "waiting" && !error ? <p className="fc-muted" style={{ margin: 0 }}>{t("instant.copying")}</p> : null}
        {copy === "failed" ? <WarningBanner tone="danger">{t("instant.syncFailed")}</WarningBanner> : null}
        {estimate && !job ? (
          estimate.model_missing ? (
            <WarningBanner tone="warning">{t("instant.modelMissing", { reason: estimate.model_missing })}</WarningBanner>
          ) : (
            <>
              <p style={{ margin: 0 }}>
                {t("instant.estimate", { datasets: formatNumber(estimate.datasets), tokens: formatNumber(estimate.prompt_tokens) })}
              </p>
              <div><Button variant="primary" disabled={starting} onClick={() => void start()}>{t("instant.build")}</Button></div>
            </>
          )
        ) : null}
        {job ? (
          <ol className="fc-stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: "var(--base-size-8)" }}>
            {job.steps.map((step) => (
              <li key={step.id} className="fc-row" style={{ justifyContent: "space-between" }}>
                <span>{t(`instant.step_${step.id}`)}</span>
                <StatusPill status={PILL[step.state]}>{t(`ui.${step.state === "done" ? "succeeded" : step.state === "failed" ? "error" : step.state}`)}</StatusPill>
              </li>
            ))}
          </ol>
        ) : null}
        {job?.status === "failed" ? (
          <WarningBanner tone="danger">
            {t("instant.failed", { step: t(`instant.step_${job.failed_step ?? "marts"}`), error: job.error ?? "" })}
          </WarningBanner>
        ) : null}
        {result ? (
          <>
            {result.slow?.length ? <WarningBanner tone="warning">{t("instant.slow", { views: result.slow.join(", ") })}</WarningBanner> : null}
            <p style={{ margin: 0 }}>{t("instant.ready")}</p>
            <ul className="fc-stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: "var(--base-size-8)" }}>
              {(result.suggested_questions ?? []).map((question) => (
                <li key={question}><Button onClick={() => onAsk(question)}>{question}</Button></li>
              ))}
            </ul>
            <div><Button variant="primary" onClick={() => onAsk()}>{t("instant.openChat")}</Button></div>
          </>
        ) : null}
        {error ? <WarningBanner tone="danger">{error}</WarningBanner> : null}
      </div>
    </section>
  );
}
