"use client";

// Runs and trace (DECISIONS §10, §15): every question asked, filtered by dates and status, and one run's trace:
// its steps with their durations, the model calls with tokens and estimated cost, the SQL attempts with their
// error, and the access decision. While a run is still running, the list and its trace are read again every few
// seconds and its duration counts up, so a finished or failed run shows its outcome without reloading the page.

import { useCallback, useEffect, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { useConsole } from "@/components/console/ConsoleLayout";
import { DetailPage } from "@/components/console/DetailPage";
import { StatusLabel } from "@/components/console/kit";
import { ListPage, RecordTable } from "@/components/console/ListPage";
import { TraceTimeline, useDuration } from "@/components/console/TraceTimeline";
import { useChat } from "@/lib/chat/ChatContext";
import type { RunRow } from "@/lib/contracts";
import { useLoad } from "@/lib/console/useLoad";
import { useI18n } from "@/lib/i18n/react";
import { langOf } from "@/lib/text";

const STATUSES = ["all", "running", "succeeded", "clarified", "cancelled", "failed", "error", "denied", "rejected", "blocked"];
/** How often a page with a running run reads it again. */
export const REFRESH_MS = 2000;

/** Calls ``reload`` every REFRESH_MS while ``active``, and returns the current time, which ticks meanwhile. */
export function useWhileRunning(active: boolean, reload: () => Promise<void>): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setInterval(() => {
      setNow(Date.now());
      void reload();
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [active, reload]);
  return now;
}

/** A run's duration: its recorded latency, or the time since it started while it is running. */
export function runDuration(run: { status: string; ts: string; latency_ms: number }, now: number): number {
  return run.status === "running" ? Math.max(0, now - Date.parse(run.ts)) : run.latency_ms;
}

/** An estimated cost in US dollars, to four decimals as model calls cost fractions of a cent. */
export function useUsd(): (value: number, decimals?: number) => string {
  const { formatNumber } = useI18n();
  return (value, decimals = 4) => formatNumber(value, { style: "currency", currency: "USD", minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/** A run's cost: unknown when a call that answered had no price, or a lower bound when the others had one. */
export function useRunCost(): (run: { cost_usd: number; cost_unknown?: boolean }) => string {
  const { t } = useI18n();
  const usd = useUsd();
  return (run) => (!run.cost_unknown ? usd(run.cost_usd) : run.cost_usd > 0 ? t("runsPage.costAtLeast", { cost: usd(run.cost_usd) }) : t("runsPage.costUnknown"));
}

export function RunsSection() {
  const { t, formatDate } = useI18n();
  const { api } = useChat();
  const { navigate } = useConsole();
  const duration = useDuration();
  const cost = useRunCost();
  // Every source's runs, so a conversation on one source and one on another show in one list.
  const { data, failed, reload } = useLoad(useCallback(() => api.runs.list({ all: true }), [api]));
  const [source, setSource] = useState("");
  const sources = [...new Set((data ?? []).map((run) => run.pack).filter(Boolean))].sort();
  const now = useWhileRunning(!!data?.some((run) => run.status === "running"), reload);
  const [status, setStatus] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const rows = (data ?? []).filter((run) =>
    (!source || run.pack === source)
    && (status === "all" || run.status === status)
    && (!from || run.ts.slice(0, 10) >= from)
    && (!to || run.ts.slice(0, 10) <= to));

  return (
    <ListPage section="runs" loading={!data} failed={failed} skeleton="table">
      <div className="toolbar filters" role="group" aria-label={t("runsPage.filters")}>
        {sources.length > 1 ? (
          <div className="fc-field">
            <label className="fc-field-label" htmlFor="runs-source">{t("runsPage.source")}</label>
            <div className="sel">
              <select id="runs-source" className="fc-input fc-input-sm" value={source} onChange={(event) => setSource(event.target.value)}>
                <option value="">{t("runsPage.allSources")}</option>
                {sources.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
              <Icon name="chevronDown" />
            </div>
          </div>
        ) : null}
        <div className="fc-field">
          <label className="fc-field-label" htmlFor="runs-from">{t("ui.from")}</label>
          <input id="runs-from" className="fc-input fc-input-sm" type="date" value={from} onChange={(event) => setFrom(event.target.value)} />
        </div>
        <div className="fc-field">
          <label className="fc-field-label" htmlFor="runs-to">{t("ui.to")}</label>
          <input id="runs-to" className="fc-input fc-input-sm" type="date" value={to} onChange={(event) => setTo(event.target.value)} />
        </div>
        <div className="fc-field">
          <label className="fc-field-label" htmlFor="runs-status">{t("ui.status")}</label>
          <div className="sel">
            <select id="runs-status" className="fc-input fc-input-sm" value={status} onChange={(event) => setStatus(event.target.value)}>
              {STATUSES.map((value) => <option key={value} value={value}>{t(`ui.${value}`)}</option>)}
            </select>
            <Icon name="chevronDown" />
          </div>
        </div>
      </div>
      <RecordTable
        key={`${source}|${status}|${from}|${to}`}
        label={t("ui.nav_runs")}
        empty={t("runsPage.empty")}
        rows={rows}
        rowKey={(run) => run.trace_id}
        columns={[
          { key: "ts", label: t("ui.time"), nowrap: true, render: (run) => formatDate(run.ts, { dateStyle: "medium", timeStyle: "short" }) },
          { key: "question", label: t("ui.question"), render: (run) => (
            <>
              <button type="button" className="row-title link-button" lang={langOf(run.question)} onClick={() => navigate(`/console/runs/${encodeURIComponent(run.trace_id)}`)}>{run.question}</button>
              {run.answer_to ? (
                <div className="fc-muted row-sub">{t("runsPage.answerTo")} <span lang={langOf(run.answer_to)}>{run.answer_to}</span></div>
              ) : null}
            </>
          ) },
          ...(sources.length > 1 ? [{ key: "pack", label: t("runsPage.source"), nowrap: true, render: (run: RunRow) => <span className="fc-mono">{run.pack}</span> }] : []),
          { key: "status", label: t("ui.status"), render: (run) => <StatusLabel status={run.status}>{t(`ui.${run.status}`)}</StatusLabel> },
          { key: "latency_ms", label: t("ui.duration"), numeric: true, nowrap: true, render: (run) => duration(runDuration(run, now)) },
          { key: "cost_usd", label: t("ui.cost"), numeric: true, render: (run) => cost(run) },
        ]}
      />
    </ListPage>
  );
}

export function RunDetail({ traceId }: { traceId: string }) {
  const { t, formatDate } = useI18n();
  const { api, pack } = useChat();
  const { navigate } = useConsole();
  const duration = useDuration();
  const cost = useRunCost();
  const { data, failed, reload } = useLoad(useCallback(async () => ({ trace: await api.runs.trace(traceId) }), [api, traceId]));
  const run = data?.trace?.run;
  const now = useWhileRunning(run?.status === "running", reload);
  return (
    <DetailPage feature="runs" title={run?.question} titleLang={run ? langOf(run.question) : undefined} status={run?.status} backLabel={t("ui.nav_runs")}
      onBack={() => navigate("/console/runs")} loading={!data && !failed} missing={!run}>
      {run ? (
        <div className="split">
          <div className="split-main">
            <section className="box" aria-labelledby="steps-title">
              <div className="box-head"><h2 id="steps-title" className="box-title">{t("runsPage.steps")}</h2></div>
              <div className="box-pad"><TraceTimeline items={data?.trace?.items ?? []} /></div>
            </section>
          </div>
          <div className="split-side">
            <section className="box" aria-labelledby="summary-title">
              <div className="box-head"><h2 id="summary-title" className="box-title">{t("runsPage.summary")}</h2></div>
              <div className="box-body">
                <dl className="kv">
                  <dt>{t("ui.time")}</dt><dd>{formatDate(run.ts, { dateStyle: "medium", timeStyle: "medium" })}</dd>
                  <dt>{t("ui.duration")}</dt><dd>{duration(runDuration(run, now))}</dd>
                  <dt>{t("ui.cost")}</dt><dd>{cost(run)}</dd>
                  {run.answer_to ? <><dt>{t("runsPage.answerToLabel")}</dt><dd lang={langOf(run.answer_to)}>{run.answer_to}</dd></> : null}
                  {/* Why the run got no answer: what it asked back for, or the error it ended with. */}
                  {run.error ? <><dt>{t("ui.reason")}</dt><dd lang="en">{run.error}</dd></> : null}
                  {pack ? <><dt>{t("runsPage.pack")}</dt><dd>{pack.display_name || pack.name}</dd></> : null}
                  <dt>{t("runsPage.trace")}</dt><dd className="fc-mono trace-id">{run.trace_id}</dd>
                </dl>
              </div>
            </section>
          </div>
        </div>
      ) : null}
    </DetailPage>
  );
}
