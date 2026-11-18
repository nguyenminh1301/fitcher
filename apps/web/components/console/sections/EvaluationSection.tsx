"use client";

// Evaluation (DECISIONS §12, §15): the latest eval report of the active pack with its per-layer rates,
// the execution-match threshold, the required question set and failed cases, plus earlier reports.
// The owner can start a run of the eval set, which uses paid AI and asks first.

import { useCallback, useState, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { useConsole } from "@/components/console/ConsoleLayout";
import { DetailPage } from "@/components/console/DetailPage";
import { StatusLabel } from "@/components/console/kit";
import { ListPage, RecordTable } from "@/components/console/ListPage";
import { Dialog } from "@/components/ui/overlay";
import type { EvalReport } from "@/lib/contracts";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import { cx } from "@/lib/cx";
import { useI18n } from "@/lib/i18n/react";

// The layers an eval report scores, in pipeline order, and their labels.
const LAYERS: [string, string][] = [["intent", "ui.layer_intent"], ["extraction", "ui.layer_extract"], ["retrieval", "ui.layer_retrieval"], ["execution", "ui.layer_exec"]];

// The question categories every pack's eval set must cover (packs/_schema/eval.schema.json).
const CATEGORIES: [string, string][] = [
  ["two_period_compare", "ui.cat_compare"], ["top_n", "ui.cat_topn"], ["string_filter", "ui.cat_filter"], ["monthly_trend", "ui.cat_trend"],
  ["ambiguous", "ui.cat_clarify"], ["unauthorized", "ui.cat_deny"], ["out_of_scope", "ui.cat_oos"],
];

/** Passed over scored cases, or null when the layer scored none. */
function rate(layer?: { passed: number; failed: number }): number | null {
  const scored = (layer?.passed ?? 0) + (layer?.failed ?? 0);
  return scored ? (layer?.passed ?? 0) / scored : null;
}

// Day, month and time: reports are recent, so the year adds nothing.
const SHORT_TIME: Intl.DateTimeFormatOptions = { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" };

const percent = (value: number) => `${Math.round(value * 100)}%`;

/** A category score is written "passed/cases" in the report. */
function categoryScore(value?: string): { passed: number; cases: number } | null {
  const match = value?.match(/^\s*(\d+)\s*\/\s*(\d+)\s*$/);
  return match ? { passed: Number(match[1]), cases: Number(match[2]) } : null;
}

function ResultLabel({ report }: { report: EvalReport }) {
  const { t } = useI18n();
  if (rate(report.layers.execution) === null) return <StatusLabel tone={null}>{t("ui.notScored")}</StatusLabel>;
  return report.passed
    ? <StatusLabel tone="success"><Icon name="check" />{t("ui.meetsThreshold")}</StatusLabel>
    : <StatusLabel tone="danger">{t("ui.belowThreshold")}</StatusLabel>;
}

function LayerRow({ label, value, threshold }: { label: string; value: number | null; threshold?: number }) {
  const { t } = useI18n();
  const name = value === null ? label : `${label} ${percent(value)}${threshold ? ` · ${t("ui.threshold", { n: percent(threshold) })}` : ""}`;
  return (
    <div className="ev-layer">
      <span>{label}</span>
      {value === null ? <span className="ev-layer-bar" /> : (
        <div className="ev-layer-bar stat-bar" role="img" aria-label={name}>
          <span className={cx(threshold !== undefined && value < threshold && "ev-low")} style={{ width: `${value * 100}%` }} />
          {threshold ? <i className="ev-mark" style={{ left: `${threshold * 100}%` }} /> : null}
        </div>
      )}
      <span className="fc-muted">{value === null ? t("ui.notScored") : percent(value)}</span>
    </div>
  );
}

/** One report: the execution match against the threshold, per-layer rates, the required set and failed cases. */
function ReportBody({ report, title, side }: { report: EvalReport; title: string; side?: ReactNode }) {
  const { t, formatDate } = useI18n();
  const execution = rate(report.layers.execution);
  const category = (key: string) => {
    const label = CATEGORIES.find(([item]) => item === key)?.[1];
    return label ? t(label) : key;
  };
  const main = (
    <>
      <RecordTable
        label={t("ui.requiredSet")}
        title={t("ui.requiredSet")}
        rows={CATEGORIES.map(([key, label]) => ({ key, label: t(label), score: categoryScore(report.categories[key]) }))}
        rowKey={(row) => row.key}
        columns={[
          { key: "label", label: t("ui.category") },
          { key: "cases", label: t("evaluationPage.cases"), numeric: true, render: (row) => row.score?.cases ?? "—" },
          { key: "passed", label: t("evaluationPage.passed"), numeric: true, render: (row) => row.score ? row.score.passed : <span className="fc-muted">{t("ui.notScored")}</span> },
        ]}
      />
      <RecordTable
        label={t("ui.failedCases")}
        title={t("ui.failedCases")}
        empty={t("evaluationPage.noFailed")}
        rows={report.failed_cases}
        rowKey={(row) => row.case_id}
        columns={[
          { key: "case_id", label: t("evaluationPage.case"), mono: true },
          { key: "category", label: t("ui.category"), render: (row) => category(row.category) },
          { key: "reason", label: t("ui.reason") },
        ]}
      />
    </>
  );
  return (
    <>
      <section className="box box-pad ev-report" aria-labelledby="ev-title">
        <div className="ev-head">
          <h2 id="ev-title" className="sect-title">{title} · {formatDate(report.ts, SHORT_TIME)}</h2>
          <ResultLabel report={report} />
        </div>
        <div className="ev-score">
          <span className="ev-score-value">{execution === null ? "—" : percent(execution)}</span>
          <span className="fc-muted">{t("evaluationPage.scoreLine", { n: percent(report.threshold) })}</span>
        </div>
        <div className="ev-layers">
          {LAYERS.map(([key, label]) => (
            <LayerRow key={key} label={t(label)} value={rate(report.layers[key])} threshold={key === "execution" ? report.threshold : undefined} />
          ))}
        </div>
      </section>
      {side ? <div className="split"><div className="split-main">{main}</div><div className="split-side">{side}</div></div> : main}
    </>
  );
}

function useReports() {
  const { api } = useChat();
  return useLoad(useCallback(async () => [...(await api.evaluation.reports())].sort((a, b) => b.ts.localeCompare(a.ts)), [api]));
}

function History({ reports }: { reports: EvalReport[] }) {
  const { t, formatDate } = useI18n();
  const { navigate } = useConsole();
  return (
    <RecordTable
      label={t("evaluationPage.history")}
      title={t("evaluationPage.history")}
      rows={reports}
      rowKey={(report) => report.id}
      columns={[
        { key: "ts", label: t("evaluationPage.when"), nowrap: true, render: (report) => (
          <button type="button" className="link-button" onClick={() => navigate(`/console/evaluation/${encodeURIComponent(report.id)}`)}>
            {formatDate(report.ts, SHORT_TIME)}
          </button>
        ) },
        { key: "execution", label: t("ui.execMatch"), render: (report) => {
          const value = rate(report.layers.execution);
          return value === null ? t("ui.notScored") : percent(value);
        } },
        { key: "passed", label: t("evaluationPage.result"), render: (report) => <ResultLabel report={report} /> },
      ]}
    />
  );
}

export function EvaluationSection() {
  const { t } = useI18n();
  const { api } = useChat();
  const { toast } = useConsole();
  const { data, failed, reload } = useReports();
  const [confirming, setConfirming] = useState(false);
  const [running, setRunning] = useState(false);
  const latest = data?.[0];

  async function start() {
    setConfirming(false);
    setRunning(true);
    try {
      await api.evaluation.start();
      toast(t("ui.evalDone"));
      await reload();
    } finally {
      setRunning(false);
    }
  }

  const history = data && data.length ? <History reports={data} /> : null;
  return (
    <ListPage section="evaluation" loading={!data} failed={failed} skeleton="page"
      actions={
        <div className="toolbar">
          <span className="fc-paid" id="eval-paid">{t("ui.paidAi")}</span>
          <button type="button" className="fc-btn fc-btn-primary" disabled={running} aria-busy={running || undefined}
            aria-describedby="eval-paid" onClick={() => setConfirming(true)}>
            {running ? <span className="fc-spin fc-spinning" aria-hidden="true" /> : <Icon name="play" />}
            {running ? t("evaluationPage.running") : t("ui.runEval")}
          </button>
        </div>
      }>
      {running ? (
        <>
          <section className="box box-pad ev-running" role="status">
            <span className="fc-spin fc-spinning" aria-hidden="true" />
            <div>
              <div>{t("ui.evalRunning")}</div>
              <div className="fc-muted">{t("evaluationPage.runningText")}</div>
            </div>
          </section>
          {history}
        </>
      ) : latest ? <ReportBody report={latest} title={t("evaluationPage.latest")} side={history} /> : (
        <section className="box"><div className="empty"><p className="empty-title">{t("evaluationPage.none")}</p><p className="empty-text">{t("evaluationPage.noneText")}</p></div></section>
      )}
      <Dialog open={confirming} title={t("evaluationPage.confirmTitle")} closeLabel={t("common.close")} onClose={() => setConfirming(false)}
        actions={<>
          <button type="button" className="fc-btn" onClick={() => setConfirming(false)}>{t("ui.cancel")}</button>
          <button type="button" className="fc-btn fc-btn-primary" onClick={() => void start()}>{t("ui.runEval")}</button>
        </>}>
        <p style={{ margin: 0 }}>{t("evaluationPage.confirmText")}</p>
      </Dialog>
    </ListPage>
  );
}

export function EvaluationReport({ id }: { id: string }) {
  const { t, formatDate } = useI18n();
  const { navigate } = useConsole();
  const { data } = useReports();
  const report = data?.find((item) => item.id === id);
  return (
    <DetailPage feature="evaluation" title={report ? formatDate(report.ts, { dateStyle: "medium", timeStyle: "short" }) : ""}
      onBack={() => navigate("/console/evaluation")} backLabel={t("ui.back")} loading={!data} missing={!report}>
      {report ? <ReportBody report={report} title={t("evaluationPage.report")} /> : null}
    </DetailPage>
  );
}
