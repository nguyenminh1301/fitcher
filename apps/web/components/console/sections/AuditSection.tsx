"use client";

// Audit (DECISIONS §9, §15): every access decision, newest first, with the role, dataset and the
// tables a denial blocked.

import { useCallback } from "react";

import { ListPage, RecordTable } from "@/components/console/ListPage";
import { StatusLabel } from "@/components/console/kit";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import { useI18n } from "@/lib/i18n/react";

export function AuditSection() {
  const { t, formatDate } = useI18n();
  const { api } = useChat();
  const { data, failed } = useLoad(useCallback(async () => [...(await api.audit.list())].sort((a, b) => b.ts.localeCompare(a.ts)), [api]));
  return (
    <ListPage section="audit" loading={!data} failed={failed} skeleton="table">
      <RecordTable
        label={t("ui.nav_audit")}
        empty={t("auditPage.empty")}
        rows={data ?? []}
        rowKey={(row) => `${row.trace_id}|${row.ts}|${row.dataset}`}
        columns={[
          { key: "ts", label: t("ui.time"), nowrap: true, render: (row) => formatDate(row.ts, { dateStyle: "medium", timeStyle: "medium" }) },
          { key: "decision", label: t("ui.decision"), render: (row) => (row.decision === "DENY"
            ? <StatusLabel tone="danger">{t("ui.deny")}</StatusLabel> : <StatusLabel tone="success">{t("ui.allow")}</StatusLabel>) },
          { key: "dataset", label: t("auditPage.dataset"), mono: true },
          { key: "blocked_tables", label: t("ui.blockedTables"), render: (row) => (row.blocked_tables.length
            ? <span className="fc-mono">{row.blocked_tables.join(", ")}</span>
            : <span className="fc-muted">{t("auditPage.none")}</span>) },
          { key: "reason", label: t("ui.reason"), render: (row) => <span className="fc-muted">{row.reason}</span> },
        ]}
      />
    </ListPage>
  );
}
