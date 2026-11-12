"use client";

// One agent run as a timeline (docs/design/web-app.md, Runs and trace): each graph step with its
// duration bar, LLM calls by alias with tokens and estimated cost, SQL attempts with their error, and
// the access decision.

import { Icon } from "@/components/brand/Icon";
import { SqlView } from "@/components/chat/SqlView";
import { StatusPill } from "@/components/ui/feedback";
import type { TraceItem } from "@/lib/contracts";
import { cx } from "@/lib/cx";
import { useI18n } from "@/lib/i18n/react";

/** A duration for people: milliseconds below one second, then seconds with one decimal. */
export function useDuration(): (ms: number) => string {
  const { formatNumber } = useI18n();
  return (ms) => (ms < 1000 ? `${formatNumber(ms, { maximumFractionDigits: 0 })} ms` : `${formatNumber(ms / 1000, { maximumFractionDigits: 1, minimumFractionDigits: 1 })} s`);
}

function iconOf(item: TraceItem): string {
  if (item.status === "err") return "x";
  if (item.status === "deny") return "lock";
  const icons: Record<string, string> = { llm: "message", sql: "database", access: "shieldCheck", search: "search" };
  return (item.kind && icons[item.kind]) || "check";
}

export function TraceTimeline({ items }: { items: TraceItem[] }) {
  const { t } = useI18n();
  const duration = useDuration();
  const longest = Math.max(1, ...items.map((item) => item.ms ?? 0));
  return (
    <ol className="fc-trace" aria-label={t("ui.trace")}>
      {items.map((item, index) => (
        <li key={index} className={cx("fc-trace-item", `fc-trace-${item.status ?? "ok"}`)}>
          <span className="fc-trace-dot"><Icon name={iconOf(item)} /></span>
          <div style={{ minWidth: 0 }}>
            <div className="fc-trace-top">
              <span className="fc-trace-name fc-mono">{item.name}</span>
              {item.status === "err" ? <StatusPill status="failed" /> : item.status === "deny" ? <StatusPill status="deny" /> : null}
              <span className="fc-trace-dur">{item.ms != null ? duration(item.ms) : ""}</span>
            </div>
            {item.ms ? <div className="fc-trace-bar" aria-hidden><span style={{ width: `${Math.max(2, (item.ms / longest) * 100)}%` }} /></div> : null}
            {item.meta?.length ? <div className="fc-trace-meta">{item.meta.map((entry, position) => <span key={position}>{entry}</span>)}</div> : null}
            {item.sql ? <div className="fc-trace-detail"><SqlView sql={item.sql} badge={false} /></div> : null}
            {item.error ? <pre className="fc-dberr fc-trace-detail">{item.error}</pre> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
