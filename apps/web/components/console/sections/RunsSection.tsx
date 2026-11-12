"use client";

// Runs and trace (DECISIONS §10, §15): every question asked, filtered by user, dates and status, and
// one run's trace with its steps, LLM calls, SQL attempts and access decision.

import { useCallback, useState } from "react";

import { useConsole } from "@/components/console/ConsoleLayout";
import { DetailPage } from "@/components/console/DetailPage";
import { ListPage, RecordTable } from "@/components/console/ListPage";
import { TraceTimeline, useDuration } from "@/components/console/TraceTimeline";
import { Segmented, TextField } from "@/components/ui/controls";
import { StatusPill } from "@/components/ui/feedback";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import { useI18n } from "@/lib/i18n/react";
import { langOf } from "@/lib/text";

const STATUSES = ["all", "succeeded", "failed", "denied", "rejected"];

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
  const [user, setUser] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const needle = user.trim().toLowerCase();
  const rows = (data ?? []).filter((run) =>
    (status === "all" || run.status === status)
    && (!needle || run.user_id.toLowerCase().includes(needle))
    && (!from || run.ts.slice(0, 10) >= from)
    && (!to || run.ts.slice(0, 10) <= to));

  return (
    <ListPage section="runs" loading={!data} failed={failed} skeleton="table">
      <div className="fc-toolbar">
        <TextField label={t("ui.user")} icon="search" value={user} onChange={(event) => setUser(event.target.value)} className="fc-tool-field" />
        <TextField label={t("ui.from")} type="date" value={from} onChange={(event) => setFrom(event.target.value)} className="fc-tool-field" />
        <TextField label={t("ui.to")} type="date" value={to} onChange={(event) => setTo(event.target.value)} className="fc-tool-field" />
      </div>
      <div className="fc-toolbar fc-scroll-x">
        <Segmented label={t("ui.status")} value={status} onChange={setStatus} options={STATUSES.map((value) => [value, t(`ui.${value}`)])} />
      </div>
      <RecordTable
        key={`${status}|${needle}|${from}|${to}`}
        label={t("ui.nav_runs")}
        rows={rows}
        rowKey={(run) => run.trace_id}
        columns={[
          { key: "ts", label: t("ui.time"), nowrap: true, render: (run) => formatDate(run.ts, { dateStyle: "medium", timeStyle: "short" }) },
          { key: "user_id", label: t("ui.user"), mono: true },
          { key: "role", label: t("ui.role"), mono: true },
          { key: "question", label: t("ui.question"), render: (run) => (
            <button type="button" className="fc-link" lang={langOf(run.question)} onClick={() => navigate(`/console/runs/${encodeURIComponent(run.trace_id)}`)}>{run.question}</button>
          ) },
          { key: "status", label: t("ui.status"), render: (run) => <StatusPill status={run.status} /> },
          { key: "latency_ms", label: t("ui.duration"), numeric: true, nowrap: true, render: (run) => duration(run.latency_ms) },
          { key: "cost_usd", label: t("ui.cost"), numeric: true, render: (run) => usd(run.cost_usd) },
        ]}
      />
    </ListPage>
  );
}

export function RunDetail({ traceId }: { traceId: string }) {
  const { t, formatDate } = useI18n();
  const { api } = useChat();
  const { navigate } = useConsole();
  const duration = useDuration();
  const usd = useUsd();
  const { data, failed } = useLoad(useCallback(async () => ({ trace: await api.runs.trace(traceId) }), [api, traceId]));
  const run = data?.trace?.run;
  return (
    <DetailPage feature="runs" title={t("ui.runDetail")} status={run?.status} backLabel={t("ui.backToRuns")} onBack={() => navigate("/console/runs")}
      loading={!data && !failed} missing={!run}
      meta={run ? <code className="fc-code fc-hide-sm" title={run.trace_id}>{run.trace_id}</code> : null}>
      {run ? (
        <div className="fc-page">
          <dl className="fc-kv">
            <dt>{t("ui.question")}</dt>
            <dd lang={langOf(run.question)} style={{ fontWeight: 600 }}>{run.question}</dd>
            <dt>{t("ui.user")}</dt>
            <dd><code className="fc-code">{run.user_id}</code></dd>
            <dt>{t("ui.role")}</dt>
            <dd><code className="fc-code">{run.role}</code></dd>
            <dt>{t("ui.time")}</dt>
            <dd>{formatDate(run.ts, { dateStyle: "medium", timeStyle: "medium" })}</dd>
            <dt>{t("ui.duration")}</dt>
            <dd className="fc-num">{duration(run.latency_ms)}</dd>
            <dt>{t("ui.cost")}</dt>
            <dd className="fc-row"><span className="fc-num">{usd(run.cost_usd)}</span><StatusPill status="estimate" /></dd>
          </dl>
          <section className="fc-card" aria-label={t("ui.runDetail")}>
            <div className="fc-card-head"><h2 className="fc-card-title">{t("ui.trace")}</h2></div>
            <div className="fc-card-body"><TraceTimeline items={data?.trace?.items ?? []} /></div>
          </section>
        </div>
      ) : null}
    </DetailPage>
  );
}
