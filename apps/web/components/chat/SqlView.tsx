"use client";

import { useId, useState, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { Button } from "@/components/ui/controls";
import { useI18n } from "@/lib/i18n/react";

const KEYWORDS = new Set(
  "SELECT FROM WHERE AND OR NOT IN AS WITH GROUP BY ORDER LIMIT HAVING JOIN LEFT RIGHT INNER OUTER ON DESC ASC CASE WHEN THEN ELSE END DISTINCT UNION ALL IS NULL BETWEEN LIKE OVER PARTITION INTERVAL".split(" "),
);

/** SQL with keywords, strings, numbers, functions and comments marked for the syntax colours. */
export function highlight(sql: string): ReactNode[] {
  const pattern = /(--[^\n]*)|('(?:[^']|'')*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_.]*)(\s*\()?|(\s+|[^\sA-Za-z0-9_'-]+|-)/g;
  const out: ReactNode[] = [];
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = pattern.exec(sql))) {
    key += 1;
    if (match[1]) out.push(<span key={key} className="fc-cm">{match[1]}</span>);
    else if (match[2]) out.push(<span key={key} className="fc-str">{match[2]}</span>);
    else if (match[3]) out.push(<span key={key} className="fc-n">{match[3]}</span>);
    else if (match[4]) {
      if (KEYWORDS.has(match[4].toUpperCase())) out.push(<span key={key} className="fc-k">{match[4]}</span>);
      else if (match[5]) out.push(<span key={key} className="fc-fn">{match[4]}</span>);
      else out.push(match[4]);
      if (match[5]) out.push(match[5]);
    } else out.push(match[0]);
  }
  return out;
}

/** The query behind an answer: collapsible, highlighted, read-only, with copy and the trust label. */
export function SqlView({ sql, title, badge = true, defaultOpen = false }: { sql: string; title?: string; badge?: boolean; defaultOpen?: boolean }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(defaultOpen);
  const [copied, setCopied] = useState(false);
  const id = useId();
  return (
    <section className="fc-sql">
      <div className="fc-sql-head">
        <button type="button" className="fc-sql-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
          <Icon name="chevronRight" /><Icon name="code" />{title ?? t("ui.sql")}
        </button>
        {badge ? <span className="fc-pill fc-pill-success"><Icon name="shieldCheck" />{t("ui.sqlBadge")}</span> : null}
        <span className="fc-spacer" />
        <Button
          variant="ghost"
          size="sm"
          icon={copied ? "check" : "copy"}
          aria-live="polite"
          onClick={() => {
            void navigator.clipboard?.writeText(sql).catch(() => undefined);
            setCopied(true);
            setTimeout(() => setCopied(false), 1600);
          }}
        >
          {copied ? t("ui.copied") : t("ui.copy")}
        </Button>
      </div>
      {open ? <pre id={id} tabIndex={0} aria-label={t("ui.sql")}><code>{highlight(sql)}</code></pre> : null}
    </section>
  );
}
