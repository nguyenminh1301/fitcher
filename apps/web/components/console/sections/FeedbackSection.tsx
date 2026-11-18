"use client";

// Feedback (DECISIONS §11 step 8, §15): likes and dislikes from the chat with their question, note and
// trace; a reviewer proposes an example from one disliked or failed run, which then waits in Review.

import { useCallback, useState } from "react";

import { useConsole } from "@/components/console/ConsoleLayout";
import { ListPage, RecordTable } from "@/components/console/ListPage";
import { Icon } from "@/components/brand/Icon";
import { StatusLabel } from "@/components/console/kit";
import { Segmented } from "@/components/ui/controls";
import type { FeedbackRow } from "@/lib/contracts";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import { useI18n } from "@/lib/i18n/react";
import { langOf } from "@/lib/text";

const proposable = (row: FeedbackRow) => !row.proposal && (row.rating === "dislike" || row.run_status === "failed");

export function FeedbackSection() {
  const { t, formatDate } = useI18n();
  const { api } = useChat();
  const { toast, navigate } = useConsole();
  const { data, failed, reload } = useLoad(useCallback(() => api.feedbackReview.list(), [api]));
  const [filter, setFilter] = useState("all");
  const rows = (data ?? []).filter((row) => filter === "all" || row.rating === filter);

  return (
    <ListPage section="feedback" loading={!data} failed={failed} skeleton="table">
      <div className="toolbar">
        <Segmented label={t("feedbackPage.filter")} value={filter} onChange={setFilter}
          options={[["all", t("ui.all")], ["like", t("ui.liked")], ["dislike", t("ui.disliked")]]} />
      </div>
      <RecordTable
        key={filter}
        label={t("ui.nav_feedback")}
        empty={t("feedbackPage.empty")}
        rows={rows}
        rowKey={(row) => row.trace_id}
        columns={[
          { key: "ts", label: t("ui.time"), nowrap: true, render: (row) => formatDate(row.ts, { dateStyle: "medium", timeStyle: "short" }) },
          { key: "question", label: t("ui.question"), render: (row) => <span lang={langOf(row.question)}>{row.question}</span> },
          { key: "rating", label: t("ui.rating"), render: (row) => (
            <span className={row.rating === "like" ? "rating-up" : "rating-down"} role="img" aria-label={row.rating === "like" ? t("ui.liked") : t("ui.disliked")}>
              <Icon name={row.rating === "like" ? "thumbsUp" : "thumbsDown"} />
            </span>
          ) },
          { key: "note", label: t("ui.note"), render: (row) => (row.note ? <span className="fc-muted" lang={langOf(row.note)}>{row.note}</span> : <span className="fc-muted">—</span>) },
          { key: "run_status", label: t("feedbackPage.run"), render: (row) => <StatusLabel status={row.run_status}>{t(`ui.${row.run_status}`)}</StatusLabel> },
          {
            key: "actions", label: t("ui.actions"), render: (row) => (
              <span className="row-actions">
                {proposable(row) ? (
                  <button type="button" className="fc-btn fc-btn-sm" onClick={async () => {
                    await api.feedbackReview.propose(row.trace_id);
                    toast(t("ui.proposedName", { question: row.question }));
                    await reload();
                  }}>{t("ui.proposeExample")}</button>
                ) : row.proposal ? <StatusLabel tone={null}>{t("feedbackPage.proposed")}</StatusLabel> : null}
                <button type="button" className="fc-btn fc-btn-ghost fc-btn-sm" aria-label={t("feedbackPage.openRun")}
                  onClick={() => navigate(`/console/runs/${encodeURIComponent(row.trace_id)}`)}>{t("feedbackPage.open")}</button>
              </span>
            ),
          },
        ]}
      />
    </ListPage>
  );
}
