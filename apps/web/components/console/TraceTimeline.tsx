"use client";

// One agent run as a timeline: each step with its duration bar, model calls by task with tokens and estimated
// cost, SQL attempts with their error, and the access decision.

import { Icon } from "@/components/brand/Icon";
import { highlight } from "@/components/chat/SqlView";
import { StatusLabel } from "@/components/console/kit";
import type { TraceItem } from "@/lib/contracts";
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

const MARK: Record<string, string> = { err: "failed", deny: "failed", repair: "repair" };

export function TraceTimeline({ items }: { items: TraceItem[] }) {
  const { t } = useI18n();
  const duration = useDuration();
  const longest = Math.max(1, ...items.map((item) => item.ms ?? 0));
  return (
    <ol className="tl" aria-label={t("ui.trace")}>
      {items.map((item, index) => (
        <li key={index} className="tl-step">
          <span className="tl-mark" data-state={MARK[item.status ?? "ok"] ?? "ok"}><Icon name={iconOf(item)} /></span>
          <div style={{ minWidth: 0 }}>
            <div className="tl-head">
              <span className="tl-name">{item.name}</span>
              {item.status === "err" ? <StatusLabel status="failed">{t("ui.failed")}</StatusLabel> : item.status === "deny" ? <StatusLabel tone="danger">{t("ui.deny")}</StatusLabel> : null}
              {item.ms ? <div className="tl-bar" role="img" aria-label={duration(item.ms)}><span style={{ width: `${Math.max(2, (item.ms / longest) * 100)}%` }} /></div> : <span className="tl-fill" />}
              <span className="fc-muted tl-ms">{item.ms != null ? duration(item.ms) : ""}</span>
            </div>
            {item.meta?.length || item.sql || item.error ? (
              <div className="tl-call">
                {item.meta?.length ? <div className="tl-meta">{item.meta.map((entry, position) => <span key={position} className="fc-muted">{entry}</span>)}</div> : null}
                {item.sql ? <pre className="code" tabIndex={0} aria-label="SQL"><code>{highlight(item.sql)}</code></pre> : null}
                {item.error ? <span className="fc-field-error"><Icon name="alert" />{item.error}</span> : null}
              </div>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
