"use client";

// The console's Overview: a "Get started" checklist until its five items are done (or hidden on this browser),
// four figures for the chosen period (runs, the share that returned a result, the estimated cost and the
// latest evaluation's execution match against its threshold), the latest runs, what waits for the owner and
// the data sources. Every figure comes from the console's own endpoints; a part that cannot load stays empty
// instead of failing the page.

import { useEffect, useMemo, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { useConsole } from "@/components/console/ConsoleLayout";
import { Segmented } from "@/components/ui/controls";
import type { FitcherApi } from "@/lib/api/client";
import type { CostRow, EvalReport, OwnerStatus, ProviderView, RunRow, SourceView } from "@/lib/contracts";
import { useChat } from "@/lib/chat/ChatContext";
import { useI18n } from "@/lib/i18n/react";
import { readStored, writeStored } from "@/lib/storage";

type Range = "24h" | "7d" | "30d";
const RANGE_HOURS: Record<Range, number> = { "24h": 24, "7d": 24 * 7, "30d": 24 * 30 };
const BUCKETS: Record<Range, number> = { "24h": 24, "7d": 7, "30d": 30 };
const HIDE_KEY = "fitcher.overview.hideStart";
// At most this many pages of 50 runs are read for the figures.
const RUN_PAGES = 20;

type Data = {
  runs: RunRow[] | null;
  costs: CostRow[] | null;
  report: EvalReport | null;
  providers: ProviderView[] | null;
  sources: SourceView[] | null;
  owner: OwnerStatus | null;
  drafts: number;
  dislikes: number;
  drifted: string[];
};

/** Every run since ``from`` (an ISO day), read 50 a page up to RUN_PAGES pages. */
export async function allRuns(api: FitcherApi, from: string): Promise<RunRow[]> {
  const rows: RunRow[] = [];
  for (let page = 1; page <= RUN_PAGES; page += 1) {
    const batch = await api.runs.list({ from, page, all: true });
    rows.push(...batch);
    if (batch.length < 50) break;
  }
  return rows;
}

function since(range: Range, now: number): Date {
  return new Date(now - RANGE_HOURS[range] * 3600 * 1000);
}

/** Values per bucket of the period, oldest first, for a sparkline. */
function series<T>(rows: T[], at: (row: T) => number, value: (row: T) => number, range: Range, now: number): number[] {
  const count = BUCKETS[range];
  const span = (RANGE_HOURS[range] * 3600 * 1000) / count;
  const start = now - RANGE_HOURS[range] * 3600 * 1000;
  const out = new Array<number>(count).fill(0);
  for (const row of rows) {
    const index = Math.floor((at(row) - start) / span);
    if (index >= 0 && index < count) out[index] += value(row);
  }
  return out;
}

function Spark({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2 || values.every((value) => value === 0)) return null;
  const max = Math.max(...values);
  const points = values.map((value, index) => `${((index / (values.length - 1)) * 260).toFixed(1)},${(36 - (value / max) * 32).toFixed(1)}`);
  const line = `M${points.join(" L")}`;
  return (
    <svg className="stat-spark" viewBox="0 0 260 40" preserveAspectRatio="none" aria-hidden="true">
      <path d={`${line} L260,40 L0,40 Z`} fill={color} opacity=".08" />
      <path d={line} fill="none" stroke={color} strokeWidth="1.75" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

const RUN_TONE: Record<string, string> = {
  succeeded: "success", failed: "danger", error: "danger", denied: "attention", rejected: "attention", blocked: "attention", clarified: "done",
};

export function OverviewSection() {
  const { t, formatNumber, formatDate } = useI18n();
  const { api, pack } = useChat();
  const { navigate } = useConsole();
  const [range, setRange] = useState<Range>("7d");
  const [hidden, setHidden] = useState(() => readStored(HIDE_KEY) === "1");
  const [now] = useState(() => Date.now());
  const [data, setData] = useState<Data | null>(null);

  useEffect(() => {
    let live = true;
    const from = since("30d", now).toISOString().slice(0, 10);
    const quiet = <T,>(promise: Promise<T>, fallback: T) => promise.catch(() => fallback);
    void (async () => {
      const [runs, costs, reports, providers, sources, owner, items, feedback] = await Promise.all([
        quiet(allRuns(api, from), null), quiet(api.costs.list(), null), quiet(api.evaluation.reports(), [] as EvalReport[]),
        quiet(api.models.providers(), null), quiet(api.sources.list(), null), quiet(api.owner.status(), null),
        quiet(api.review.items(), []), quiet(api.feedbackReview.list(), []),
      ]);
      const drifted = await Promise.all((sources ?? []).map((source) => quiet(
        api.sources.drift(source.id).then((drift) => (drift.pack && drift.changes.length ? source.id : null)), null,
      )));
      if (!live) return;
      setData({
        runs, costs, providers, sources, owner,
        report: [...reports].sort((a, b) => b.ts.localeCompare(a.ts))[0] ?? null,
        // A draft, or an item an instant pack approved without a person (shown as Unreviewed on Review).
        drafts: items.filter((item) => item.status === "draft" || item.reviewed === false).length,
        dislikes: feedback.filter((row) => row.rating === "dislike" && !row.proposal).length,
        drifted: drifted.filter((id): id is string => Boolean(id)),
      });
    })();
    return () => { live = false; };
  }, [api, now]);

  const start = since(range, now).getTime();
  const runs = useMemo(() => (data?.runs ?? []).filter((run) => Date.parse(run.ts) >= start), [data, start]);
  const costs = useMemo(() => (data?.costs ?? []).filter((row) => Date.parse(`${row.day}T23:59:59Z`) >= start), [data, start]);
  const answered = runs.filter((run) => run.status === "succeeded").length;
  // Questions of the last 24 hours that failed: the model did not answer, or the SQL kept failing.
  const unanswered = (data?.runs ?? []).filter((run) => Date.parse(run.ts) >= now - 86_400_000
    && (run.status === "failed" || run.status === "error")).length;
  const cost = costs.reduce((sum, row) => sum + row.cost_usd, 0);
  const exec = data?.report?.layers.execution;
  const execRate = exec && exec.passed + exec.failed ? exec.passed / (exec.passed + exec.failed) : null;

  const empty = <span className="stat-value fc-muted">{t("overview.noData")}</span>;
  const usd = (value: number) => formatNumber(value, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  const percent = (value: number) => formatNumber(value, { style: "percent", maximumFractionDigits: 1 });

  // Get started: model, data, pack, first question, owner password.
  const steps = data ? [
    { key: "model", done: Boolean(data.providers?.length), note: data.providers?.[0]?.name, action: ["overview.addProvider", "/console/models"] },
    { key: "data", done: Boolean(data.sources?.length), note: data.sources?.length ? t("overview.sourceCount", { n: data.sources.length }) : undefined, action: ["overview.addSource", "/console/sources"] },
    { key: "pack", done: Boolean(pack?.name), note: pack?.display_name || pack?.name, action: ["overview.buildPack", "/console/sources"] },
    { key: "ask", done: Boolean(data.runs?.length), note: undefined, action: ["overview.openChat", "/"] },
    { key: "password", done: Boolean(data.owner?.password_set), note: t("overview.passwordNote"), action: ["overview.setPassword", "/console/security"] },
  ] : [];
  const doneCount = steps.filter((step) => step.done).length;
  const next = steps.find((step) => !step.done)?.key;
  const showStart = data && !hidden && doneCount < steps.length;

  const go = (path: string) => (path === "/" ? window.location.assign("/") : navigate(path));
  const attention = data ? [
    data.drafts ? { key: "drafts", icon: "clipboardCheck", text: t("overview.drafts", { n: data.drafts }), path: "/console/review" } : null,
    data.dislikes ? { key: "dislikes", icon: "thumbsDown", text: t("overview.dislikes", { n: data.dislikes }), path: "/console/feedback" } : null,
    unanswered ? { key: "unanswered", icon: "alert", text: t("overview.unanswered", { n: unanswered }), path: "/console/runs" } : null,
    ...(data.sources ?? []).filter((source) => source.last_sync?.status === "failed").map((source) => (
      { key: `failed-${source.id}`, dot: "var(--fgColor-danger)", text: t("overview.syncFailed", { name: source.id }), path: "/console/sources" })),
    ...(data.sources ?? []).filter((source) => source.last_sync?.status === "partial").map((source) => (
      { key: `partial-${source.id}`, dot: "var(--fgColor-attention)", text: t("overview.syncPartial", { name: source.id }), path: "/console/sources" })),
    ...data.drifted.map((id) => ({ key: `drift-${id}`, dot: "var(--fgColor-attention)", text: t("overview.drifted", { name: id }), path: "/console/sources" })),
  ].filter(Boolean) as { key: string; icon?: string; dot?: string; text: string; path: string }[] : [];

  const when = (iso: string) => {
    const date = new Date(iso);
    const today = new Date(now);
    if (date.toDateString() === today.toDateString()) return formatDate(iso, { hour: "2-digit", minute: "2-digit" });
    if (date.toDateString() === new Date(now - 86_400_000).toDateString()) return t("overview.yesterday");
    return formatDate(iso, { day: "numeric", month: "short" });
  };

  return (
    <div className="cs-page">
      <div className="page-head">
        <h1 className="page-title">{t("ui.nav_overview")}</h1>
        <Segmented label={t("overview.period")} value={range} onChange={(value) => setRange(value as Range)}
          options={[["24h", t("overview.range_24h")], ["7d", t("overview.range_7d")], ["30d", t("overview.range_30d")]]} />
      </div>

      {data?.owner?.exposed && !data.owner.password_set ? (
        <div className="fc-banner fc-banner-danger" role="alert">
          <Icon name="alert" /><div style={{ flex: 1 }}>{t("overview.exposed")}</div>
          <button type="button" className="fc-btn fc-btn-sm" onClick={() => navigate("/console/security")}>{t("overview.openSecurity")}</button>
        </div>
      ) : null}

      {showStart ? (
        <section className="gs" aria-labelledby="gs-title">
          <div className="gs-head">
            <h2 id="gs-title" className="sect-title">{t("overview.getStarted")}</h2>
            <span className="fc-muted">{t("overview.doneOf", { done: doneCount, total: steps.length })}</span>
            <div className="prog-bar" role="progressbar" aria-valuenow={doneCount} aria-valuemin={0} aria-valuemax={steps.length} aria-label={t("overview.progress")}>
              <span style={{ width: `${(doneCount / steps.length) * 100}%` }} />
            </div>
            <button type="button" className="fc-btn fc-btn-ghost fc-btn-sm" aria-label={t("overview.hideStart")}
              onClick={() => { writeStored(HIDE_KEY, "1"); setHidden(true); }}><Icon name="x" />{t("overview.hide")}</button>
          </div>
          <ol className="gs-list">
            {steps.map((step, index) => (
              <li key={step.key} className="gs-item" data-state={step.key === next ? "next" : undefined}>
                <span className="gs-mark" data-state={step.done ? "done" : undefined}>
                  {step.done ? <><Icon name="check" /><span className="fc-sr">{t("overview.done")}</span></> : index + 1}
                </span>
                <span className="gs-name">{t(`overview.step_${step.key}`)}</span>
                {step.note && (step.done || step.key === "password") ? <span className="fc-muted gs-note">{step.note}</span> : null}
                {step.key === next ? (
                  <button type="button" className="fc-btn fc-btn-primary fc-btn-sm gs-action" onClick={() => go(step.action[1])}>{t(step.action[0])}</button>
                ) : null}
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <section className="stats" aria-label={t("overview.figures", { period: t(`overview.range_${range}`) })}>
        <a className="stat" href="/console/runs" onClick={(event) => { event.preventDefault(); navigate("/console/runs"); }}>
          <span className="stat-label">{t("overview.runs")}<Icon name="chevronRight" /></span>
          {data?.runs ? <span className="stat-value">{formatNumber(runs.length)}</span> : empty}
          <Spark values={series(runs, (run) => Date.parse(run.ts), () => 1, range, now)} color="var(--data-1)" />
        </a>
        <div className="stat">
          <span className="stat-label">{t("overview.answered")}</span>
          {runs.length ? <span className="stat-value">{percent(answered / runs.length)}</span> : empty}
          <span className="fc-muted stat-note">{t("overview.answeredNote")}</span>
        </div>
        <a className="stat" href="/console/costs" onClick={(event) => { event.preventDefault(); navigate("/console/costs"); }}>
          <span className="stat-label">{t("overview.cost")}<Icon name="chevronRight" /></span>
          {data?.costs ? <span className="stat-value">{usd(cost)}</span> : empty}
          <span className="fc-muted stat-note">{t("overview.costNote")}</span>
          <Spark values={series(costs, (row) => Date.parse(`${row.day}T12:00:00Z`), (row) => row.cost_usd, range, now)} color="var(--data-5)" />
        </a>
        <a className="stat" href="/console/evaluation" onClick={(event) => { event.preventDefault(); navigate("/console/evaluation"); }}>
          <span className="stat-label">{t("overview.exec")}<Icon name="chevronRight" /></span>
          {execRate === null || !data?.report ? empty : (
            <>
              <span className="stat-value">{percent(execRate)}</span>
              <div className="stat-bar" aria-hidden="true"><span style={{ width: `${execRate * 100}%` }} /></div>
              <span className="fc-muted stat-note" style={{ marginTop: 6 }}>
                {t("overview.execNote", { threshold: percent(data.report.threshold), result: data.report.passed ? t("overview.met") : t("overview.notMet") })}
              </span>
            </>
          )}
        </a>
      </section>

      <div className="split">
        <div className="split-main">
          <section className="box" aria-labelledby="recent-title">
            <div className="box-head">
              <h2 id="recent-title" className="box-title">{t("overview.recent")}</h2>
              {runs.length ? <button type="button" className="fc-btn fc-btn-ghost fc-btn-sm" onClick={() => navigate("/console/runs")}>{t("overview.seeAll")}</button> : null}
            </div>
            {runs.length ? (
              <div style={{ overflowX: "auto" }}>
                <table className="tbl">
                  <thead><tr><th>{t("ui.question")}</th><th>{t("ui.status")}</th><th className="num">{t("ui.duration")}</th><th className="num">{t("overview.at")}</th></tr></thead>
                  <tbody>
                    {runs.slice(0, 5).map((run) => (
                      <tr key={run.trace_id}>
                        <td>
                          <a className="row-title" href={`/console/runs/${encodeURIComponent(run.trace_id)}`}
                            onClick={(event) => { event.preventDefault(); navigate(`/console/runs/${encodeURIComponent(run.trace_id)}`); }}>{run.question}</a>
                        </td>
                        <td><span className={`fc-label fc-label-${RUN_TONE[run.status] ?? "accent"}`}>{t(`ui.${run.status}`)}</span></td>
                        <td className="num">{formatNumber(run.latency_ms / 1000, { maximumFractionDigits: 1 })} s</td>
                        <td className="num">{when(run.ts)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="box-empty fc-muted">{data ? t("overview.noRuns") : "…"}</p>}
          </section>
        </div>
        <div className="split-side">
          <section className="box" aria-labelledby="attention-title">
            <div className="box-head"><h2 id="attention-title" className="box-title">{t("overview.attention")}</h2></div>
            {attention.length ? attention.map((row) => (
              <a key={row.key} className="row-link" href={row.path} onClick={(event) => { event.preventDefault(); navigate(row.path); }}>
                {row.icon ? <Icon name={row.icon} /> : <span className="dot" style={{ background: row.dot }} />}
                <span style={{ flex: 1 }}>{row.text}</span>
                <Icon name="chevronRight" />
              </a>
            )) : <p className="box-empty fc-muted">{data ? t("overview.nothing") : "…"}</p>}
          </section>
          <section className="box" aria-labelledby="sources-title">
            <div className="box-head">
              <h2 id="sources-title" className="box-title">{t("ui.nav_sources")}</h2>
              {data?.sources?.length ? <button type="button" className="fc-btn fc-btn-ghost fc-btn-sm" onClick={() => navigate("/console/sources")}>{t("overview.manage")}</button> : null}
            </div>
            {data?.sources?.length ? data.sources.map((source) => {
              const status = source.last_sync?.status;
              return (
                <div key={source.id} className="row-link">
                  <Icon name={source.kind === "file" ? "fileText" : "database"} />
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span className="fc-mono">{source.id}</span>
                    <span className="fc-muted row-sub">
                      {t(`sources.kind_${source.kind}`)} · {t("overview.tables", { n: source.selected_count })}
                    </span>
                  </span>
                  {status ? <span className={`fc-label fc-label-${status === "succeeded" ? "success" : status === "failed" ? "danger" : status === "partial" ? "attention" : "accent"}`}>{t(`sources.status_${status}`)}</span> : null}
                </div>
              );
            }) : (
              <div className="box-empty">
                <span className="fc-muted">{data ? t("overview.noSources") : "…"}</span>
                {data ? <button type="button" className="fc-btn fc-btn-sm" onClick={() => navigate("/console/sources")}><Icon name="plus" />{t("overview.addSource")}</button> : null}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
