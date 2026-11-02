"use client";

// Feedback (DECISIONS §11 step 8, §15): likes and dislikes from the chat with their question, note and
// trace; a reviewer proposes an example from one disliked or failed run, which then waits in Review.

import { useCallback, useState } from "react";

import { useConsole } from "@/components/console/ConsoleLayout";
import { ListPage, RecordTable } from "@/components/console/ListPage";
import { Button, Segmented } from "@/components/ui/controls";
import { StatusPill } from "@/components/ui/feedback";
import type { FeedbackRow } from "@/lib/api/provisional";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import { useI18n } from "@/lib/i18n/react";
import { langOf } from "@/lib/text";

const proposable = (row: FeedbackRow) => !row.proposal && (row.rating === "dislike" || row.run_status === "failed");

export function FeedbackSection() {
  const { t, formatDate } = useI18n();
  const { api } = useChat();
  const { toast } = useConsole();
  const { data, failed, reload } = useLoad(useCallback(() => api.feedbackReview.list(), [api]));
  const [filter, setFilter] = useState("dislike");
  const rows = (data ?? []).filter((row) => filter === "all" || row.rating === filter);

  return (
    <ListPage section="feedback" loading={!data} failed={failed} skeleton="table">
      <div className="fc-toolbar">
        <Segmented label={t("ui.rating")} value={filter} onChange={setFilter}
          options={[["dislike", t("ui.disliked")], ["like", t("ui.liked")], ["all", t("ui.all")]]} />
      </div>
      <RecordTable
        key={filter}
        label={t("ui.nav_feedback")}
        rows={rows}
        rowKey={(row) => row.trace_id}
        columns={[
          { key: "ts", label: t("ui.time"), nowrap: true, render: (row) => formatDate(row.ts, { dateStyle: "medium", timeStyle: "short" }) },
          { key: "user_id", label: t("ui.user"), mono: true },
          { key: "question", label: t("ui.question"), render: (row) => <span lang={langOf(row.question)}>{row.question}</span> },
          { key: "rating", label: t("ui.rating"), render: (row) => <StatusPill status={row.rating === "like" ? "liked" : "disliked"} /> },
          { key: "note", label: t("ui.note"), render: (row) => (row.note ? <span lang={langOf(row.note)}>{row.note}</span> : <span className="fc-muted">—</span>) },
          { key: "trace_id", label: t("ui.trace"), mono: true, render: (row) => <code className="fc-code" title={row.trace_id}>{row.trace_id.slice(0, 8)}</code> },
          { key: "status", label: t("ui.status"), render: (row) => <StatusPill status={row.proposal ?? "fb_new"} /> },
          {
            key: "actions", label: t("ui.actions"), render: (row) => (proposable(row) ? (
              <Button size="sm" icon="clipboardCheck" onClick={async () => {
                await api.feedbackReview.propose(row.trace_id);
                toast(t("ui.proposedName", { question: row.question }));
                await reload();
              }}>{t("ui.proposeExample")}</Button>
            ) : <span className="fc-muted">—</span>),
          },
        ]}
      />
    </ListPage>
  );
}
