"use client";

// Query log (DECISIONS §9, §15): every access decision, newest first, with the dataset and the tables a denial
// blocked; then the screening verdict of every question, which says whether a question looked like an attempt to
// change fitcher's instructions and whether it was stopped.

import { useCallback } from "react";

import { ListPage, RecordTable } from "@/components/console/ListPage";
import { StatusLabel } from "@/components/console/kit";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import { useI18n } from "@/lib/i18n/react";

const VERDICT_TONE = { allow: "success", flag: "attention", block: "danger", unavailable: "attention" } as const;

export function AuditSection() {
  const { t, formatDate, formatNumber } = useI18n();
  const { api } = useChat();
  const { data, failed } = useLoad(useCallback(async () => {
    const [decisions, screening] = await Promise.all([api.audit.list(), api.audit.screening().catch(() => [])]);
    return {
      decisions: [...decisions].sort((a, b) => b.ts.localeCompare(a.ts)),
      screening: [...screening].sort((a, b) => b.ts.localeCompare(a.ts)),
    };
  }, [api]));
  const when = (ts: string) => formatDate(ts, { dateStyle: "medium", timeStyle: "medium" });
  return (
    <ListPage section="audit" loading={!data} failed={failed} skeleton="table">
      <RecordTable
        label={t("auditPage.decisions")}
        title={t("auditPage.decisions")}
        empty={t("auditPage.empty")}
        rows={data?.decisions ?? []}
        rowKey={(row) => `${row.trace_id}|${row.ts}|${row.dataset}`}
        columns={[
          { key: "ts", label: t("ui.time"), nowrap: true, render: (row) => when(row.ts) },
          { key: "decision", label: t("ui.decision"), render: (row) => (row.decision === "DENY"
            ? <StatusLabel tone="danger">{t("ui.deny")}</StatusLabel> : <StatusLabel tone="success">{t("ui.allow")}</StatusLabel>) },
          { key: "dataset", label: t("auditPage.dataset"), mono: true },
          { key: "blocked_tables", label: t("ui.blockedTables"), render: (row) => (row.blocked_tables.length
            ? <span className="fc-mono">{row.blocked_tables.join(", ")}</span>
            : <span className="fc-muted">{t("auditPage.none")}</span>) },
          { key: "reason", label: t("ui.reason"), render: (row) => <span className="fc-muted">{row.reason}</span> },
        ]}
      />
      <RecordTable
        label={t("auditPage.screening")}
        title={t("auditPage.screening")}
        empty={t("auditPage.screeningEmpty")}
        rows={data?.screening ?? []}
        rowKey={(row) => `${row.trace_id}|${row.ts}|${row.source}`}
        columns={[
          { key: "ts", label: t("ui.time"), nowrap: true, render: (row) => when(row.ts) },
          { key: "verdict", label: t("auditPage.verdict"), render: (row) => (
            <StatusLabel tone={VERDICT_TONE[row.verdict as keyof typeof VERDICT_TONE] ?? null}>
              {t(`auditPage.verdict_${row.verdict}`) !== `auditPage.verdict_${row.verdict}` ? t(`auditPage.verdict_${row.verdict}`) : row.verdict}
            </StatusLabel>
          ) },
          { key: "mode", label: t("auditPage.mode"), render: (row) => <span className="fc-muted">{t(row.mode === "enforce" ? "auditPage.mode_enforce" : "auditPage.mode_log")}</span> },
          { key: "rule_hits", label: t("auditPage.rules"), render: (row) => (row.rule_hits.length
            ? <span className="fc-mono">{row.rule_hits.join(", ")}</span>
            : <span className="fc-muted">{t("auditPage.none")}</span>) },
          { key: "score", label: t("auditPage.score"), numeric: true,
            render: (row) => (row.score === null ? <span className="fc-muted">—</span> : formatNumber(row.score, { maximumFractionDigits: 2 })) },
        ]}
      />
    </ListPage>
  );
}
