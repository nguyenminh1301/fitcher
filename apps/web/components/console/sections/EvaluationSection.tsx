"use client";

// Evaluation (DECISIONS §12, §15): the latest eval report of the active pack with its per-layer rates,
// the execution-match threshold, the required question set and failed cases, plus earlier reports.
// An admin can start a run of the eval set, which uses paid AI.

import { useCallback, useState, type ReactNode } from "react";

import { useConsole } from "@/components/console/ConsoleLayout";
import { DetailPage } from "@/components/console/DetailPage";
import { ListPage, RecordTable } from "@/components/console/ListPage";
import { PaidAiConfirm } from "@/components/console/PaidAiConfirm";
import { Button } from "@/components/ui/controls";
import { StatusPill, WarningBanner } from "@/components/ui/feedback";
import type { EvalReport } from "@/lib/api/provisional";
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

function Meter({ label, value, threshold }: { label: string; value: number | null; threshold?: number }) {
  const { t } = useI18n();
  const percent = value === null ? null : Math.round(value * 100);
  const thresholdLabel = threshold ? t("ui.threshold", { n: `${Math.round(threshold * 100)}%` }) : "";
  return (
    <div className="fc-meter-row">
      <span className="fc-meter-label">{label}</span>
      {value === null ? <span className="fc-muted">{t("ui.notScored")}</span> : (
        <>
          <span className="fc-meter" role="img" aria-label={`${label} ${percent}%${threshold ? ` · ${thresholdLabel}` : ""}`}>
            <span className={cx("fc-meter-fill", threshold !== undefined && value < threshold && "fc-meter-low")} style={{ width: `${value * 100}%` }} />
            {threshold ? <span className="fc-meter-mark" style={{ left: `${threshold * 100}%` }} title={thresholdLabel} /> : null}
          </span>
          <span className="fc-meter-val fc-num">{percent}%</span>
        </>
      )}
    </div>
  );
}

/** One report: the headline numbers, per-layer rates, the required question set and failed cases. */
function ReportBody({ report }: { report: EvalReport }) {
  const { t, formatDate, formatNumber } = useI18n();
  const execution = rate(report.layers.execution);
  const passed = report.layers.execution?.passed ?? 0;
  const scored = passed + (report.layers.execution?.failed ?? 0);
  const stat = (label: string, value: string, badge?: ReactNode) => (
    <div className="fc-card fc-stat"><span className="fc-stat-label">{label}{badge}</span><span className="fc-stat-value">{value}</span></div>
  );
  return (
    <>
      <div className="fc-stat-grid">
        {stat(t("ui.execMatch"), execution === null ? "—" : `${formatNumber(execution * 100, { maximumFractionDigits: 0 })}%`, <StatusPill status={report.passed ? "packEnabled" : "belowThreshold"} />)}
        {stat(t("ui.cases"), `${passed} / ${scored}`, <span className="fc-muted">{t("ui.passed")}</span>)}
        {stat(t("ui.lastRun"), formatDate(report.ts, { dateStyle: "medium", timeStyle: "short" }))}
      </div>
      <section className="fc-card">
        <div className="fc-card-head">
          <h2 className="fc-card-title">{t("ui.byLayer")}</h2>
          <span className="fc-muted" style={{ fontSize: 12, marginRight: "var(--base-size-8)" }}>{t("ui.threshold", { n: `${Math.round(report.threshold * 100)}%` })}</span>
        </div>
        <div className="fc-card-body fc-stack" style={{ gap: "var(--base-size-12)" }}>
          {LAYERS.map(([key, label]) => (
            <Meter key={key} label={t(label)} value={rate(report.layers[key])} threshold={key === "execution" ? report.threshold : undefined} />
          ))}
        </div>
      </section>
      <RecordTable
        label={t("ui.requiredSet")}
        title={t("ui.requiredSet")}
        rows={CATEGORIES.map(([key, label]) => ({ key, label: t(label), score: report.categories[key] }))}
        rowKey={(row) => row.key}
        columns={[
          { key: "label", label: t("ui.category") },
          { key: "score", label: t("ui.passed"), numeric: true, render: (row) => row.score ?? <span className="fc-muted">{t("ui.notScored")}</span> },
        ]}
      />
      <RecordTable
        label={t("ui.failedCases")}
        title={t("ui.failedCases")}
        rows={report.failed_cases}
        rowKey={(row) => row.case_id}
        columns={[
          { key: "case_id", label: t("ui.question"), mono: true },
          { key: "category", label: t("ui.category"), render: (row) => {
            const label = CATEGORIES.find(([key]) => key === row.category)?.[1];
            return label ? t(label) : row.category;
          } },
          { key: "reason", label: t("ui.reason") },
        ]}
      />
    </>
  );
}

function useReports() {
  const { api } = useChat();
  return useLoad(useCallback(async () => [...(await api.evaluation.reports())].sort((a, b) => b.ts.localeCompare(a.ts)), [api]));
}

export function EvaluationSection() {
  const { t, formatDate } = useI18n();
  const { api, identity } = useChat();
  const { navigate, toast } = useConsole();
  const { data, failed, reload } = useReports();
  const [confirming, setConfirming] = useState(false);
  const [running, setRunning] = useState(false);
  const latest = data?.[0];
  const isAdmin = identity?.roles.includes("admin") ?? false;

  async function start() {
    setRunning(true);
    try {
      await api.evaluation.start();
      toast(t("ui.evalDone"));
      await reload();
    } finally {
      setRunning(false);
    }
  }

  return (
    <ListPage section="evaluation" loading={!data} failed={failed} skeleton="page"
      actions={isAdmin ? (
        <Button variant="primary" icon={running ? "loader" : "play"} meta={t("ui.paidAi")} disabled={running} onClick={() => setConfirming(true)}>{t("ui.runEval")}</Button>
      ) : null}>
      {running ? <WarningBanner tone="info" icon="loader">{t("ui.evalRunning")}</WarningBanner> : null}
      {latest ? <ReportBody report={latest} /> : null}
      {data && data.length ? (
        <RecordTable
          label={t("ui.reports")}
          title={t("ui.reports")}
          rows={data}
          rowKey={(report) => report.id}
          columns={[
            { key: "ts", label: t("ui.time"), nowrap: true, render: (report) => (
              <button type="button" className="fc-link" onClick={() => navigate(`/console/evaluation/${encodeURIComponent(report.id)}`)}>
                {formatDate(report.ts, { dateStyle: "medium", timeStyle: "short" })}
              </button>
            ) },
            { key: "execution", label: t("ui.execMatch"), numeric: true, render: (report) => {
              const value = rate(report.layers.execution);
              return value === null ? "—" : `${Math.round(value * 100)}%`;
            } },
            { key: "passed", label: t("ui.status"), render: (report) => <StatusPill status={report.passed ? "packEnabled" : "belowThreshold"} /> },
          ]}
        />
      ) : null}
      <PaidAiConfirm open={confirming} text={t("ui.evalConfirmText")} onClose={() => setConfirming(false)} onConfirm={() => void start()} />
    </ListPage>
  );
}

export function EvaluationReport({ id }: { id: string }) {
  const { t, formatDate } = useI18n();
  const { navigate } = useConsole();
  const { data } = useReports();
  const report = data?.find((item) => item.id === id);
  return (
    <DetailPage title={report ? formatDate(report.ts, { dateStyle: "medium", timeStyle: "short" }) : ""} status={report ? (report.passed ? "packEnabled" : "belowThreshold") : undefined}
      onBack={() => navigate("/console/evaluation")} backLabel={t("ui.back")} loading={!data} missing={!report}>
      {report ? <div className="fc-page"><ReportBody report={report} /></div> : null}
    </DetailPage>
  );
}
