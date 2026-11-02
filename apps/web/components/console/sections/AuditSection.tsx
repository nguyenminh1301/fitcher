"use client";

// Audit (DECISIONS §9, §15): every access decision, newest first, with the role, dataset and the
// tables a denial blocked.

import { useCallback } from "react";

import { ListPage, RecordTable } from "@/components/console/ListPage";
import { StatusPill } from "@/components/ui/feedback";
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
        rows={data ?? []}
        rowKey={(row) => `${row.trace_id}|${row.ts}|${row.dataset}`}
        columns={[
          { key: "ts", label: t("ui.time"), nowrap: true, render: (row) => formatDate(row.ts, { dateStyle: "medium", timeStyle: "medium" }) },
          { key: "user_id", label: t("ui.user"), mono: true },
          { key: "role", label: t("ui.role"), mono: true },
          { key: "decision", label: t("ui.decision"), render: (row) => <StatusPill status={row.decision === "DENY" ? "deny" : "allow"} /> },
          { key: "dataset", label: t("ui.tables"), mono: true },
          { key: "blocked_tables", label: t("ui.blockedTables"), render: (row) => (row.blocked_tables.length
            ? <span className="fc-row" style={{ gap: "var(--base-size-4)" }}>{row.blocked_tables.map((table) => <code key={table} className="fc-code">{table}</code>)}</span>
            : <span className="fc-muted">—</span>) },
          { key: "reason", label: t("ui.reason") },
        ]}
      />
    </ListPage>
  );
}
