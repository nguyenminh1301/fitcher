"use client";

// Runs and trace (DECISIONS §10, §15): every question asked, filtered by dates and status, and one run's trace:
// its steps with their durations, the model calls with tokens and estimated cost, the SQL attempts with their
// error, and the access decision.

import { useCallback, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { useConsole } from "@/components/console/ConsoleLayout";
import { DetailPage } from "@/components/console/DetailPage";
import { StatusLabel } from "@/components/console/kit";
import { ListPage, RecordTable } from "@/components/console/ListPage";
import { TraceTimeline, useDuration } from "@/components/console/TraceTimeline";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import { useI18n } from "@/lib/i18n/react";
import { langOf } from "@/lib/text";

const STATUSES = ["all", "succeeded", "clarified", "failed", "error", "denied", "rejected", "blocked"];

/** An estimated cost in US dollars, to four decimals as model calls cost fractions of a cent. */
export function useUsd(): (value: number, decimals?: number) => string {
  const { formatNumber } = useI18n();
  return (value, decimals = 4) => formatNumber(value, { style: "currency", currency: "USD", minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export function RunsSection() {
  const { t, formatDate } = useI18n();
  const { api } = useChat();
  const { navigate } = useConsole();
  const duration = useDuration();
  const usd = useUsd();
  const { data, failed } = useLoad(useCallback(() => api.runs.list(), [api]));
  const [status, setStatus] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const rows = (data ?? []).filter((run) =>
    (status === "all" || run.status === status)
    && (!from || run.ts.slice(0, 10) >= from)
    && (!to || run.ts.slice(0, 10) <= to));

  return (
    <ListPage section="runs" loading={!data} failed={failed} skeleton="table">
      <div className="toolbar filters" role="group" aria-label={t("runsPage.filters")}>
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
        key={`${status}|${from}|${to}`}
        label={t("ui.nav_runs")}
        empty={t("runsPage.empty")}
        rows={rows}
        rowKey={(run) => run.trace_id}
        columns={[
          { key: "ts", label: t("ui.time"), nowrap: true, render: (run) => formatDate(run.ts, { dateStyle: "medium", timeStyle: "short" }) },
          { key: "question", label: t("ui.question"), render: (run) => (
            <button type="button" className="row-title link-button" lang={langOf(run.question)} onClick={() => navigate(`/console/runs/${encodeURIComponent(run.trace_id)}`)}>{run.question}</button>
          ) },
          { key: "status", label: t("ui.status"), render: (run) => <StatusLabel status={run.status}>{t(`ui.${run.status}`)}</StatusLabel> },
          { key: "latency_ms", label: t("ui.duration"), numeric: true, nowrap: true, render: (run) => duration(run.latency_ms) },
          { key: "cost_usd", label: t("ui.cost"), numeric: true, render: (run) => usd(run.cost_usd) },
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
  const usd = useUsd();
  const { data, failed } = useLoad(useCallback(async () => ({ trace: await api.runs.trace(traceId) }), [api, traceId]));
  const run = data?.trace?.run;
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
                  <dt>{t("ui.duration")}</dt><dd>{duration(run.latency_ms)}</dd>
                  <dt>{t("ui.cost")}</dt><dd>{usd(run.cost_usd)}</dd>
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
