"use client";

// The console's list pages (docs/design/web-app.md, Workspace console): a page head with the section's
// title, description and Sample data badge, a page skeleton while loading, list rows that open a detail
// page, and tables of 20 rows a page that become cards on phones.

import { useState, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { Empty } from "@/components/console/kit";
import { Skeleton } from "@/components/ui/feedback";
import { SampleDataBadge } from "@/components/ui/SampleDataBadge";
import { useChat } from "@/lib/chat/ChatContext";
import { SECTIONS } from "@/lib/console/sections";
import { cx } from "@/lib/cx";
import { useI18n } from "@/lib/i18n/react";

export const PAGE_SIZE = 20;

type ListPageProps = {
  /** The section key, which gives the title, description and the feature behind the Sample data badge. */
  section: string;
  actions?: ReactNode;
  loading: boolean;
  failed?: boolean;
  skeleton?: "list" | "table" | "page";
  children?: ReactNode;
};

export function ListPage({ section, actions, loading, failed, skeleton = "list", children }: ListPageProps) {
  const { t } = useI18n();
  const { sources, pack, loaded } = useChat();
  const feature = SECTIONS.find((item) => item.key === section)?.feature;
  let body: ReactNode = children;
  // Most sections read the active pack; before the first pack is built they say so instead of failing.
  if (failed && loaded && !pack) {
    body = (
      <div className="box">
        <Empty icon="database" title={t("ui.noPackSection")} text={t("ui.noPackSectionText")}
          action={<a className="fc-btn fc-btn-primary" href="/console/sources">{t("ui.noPackAction")}</a>} />
      </div>
    );
  } else if (failed) {
    body = (
      <div className="box">
        <Empty icon="alert" title={t("ui.loadFailed")} text={t("ui.loadFailedText")}
          action={<button type="button" className="fc-btn" onClick={() => window.location.reload()}><Icon name="refresh" />{t("ui.retry")}</button>} />
      </div>
    );
  }
  else if (loading) body = <div className="box box-pad" aria-busy="true"><Skeleton variant={skeleton} rows={8} /></div>;
  return (
    <div className="cs-page">
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <div className="fc-row">
            <h1 className="page-title">{t(`ui.nav_${section}`)}</h1>
            {feature ? <SampleDataBadge feature={feature} sources={sources} /> : null}
          </div>
          {t(`ui.desc_${section}`) !== `ui.desc_${section}` ? <p className="page-desc">{t(`ui.desc_${section}`)}</p> : null}
        </div>
        {loading || failed ? null : actions ?? null}
      </div>
      {body}
    </div>
  );
}

/** One row of a list card; the whole row opens its detail page. */
export function ListRow({ title, sub, side, mono, titleLang, subLang, onOpen }: {
  title: ReactNode; sub?: ReactNode; side?: ReactNode; mono?: boolean; titleLang?: string; subLang?: string; onOpen: () => void;
}) {
  return (
    <li>
      <button type="button" className="fc-list-row" onClick={onOpen}>
        <span className="fc-list-main">
          <span className={cx("fc-list-title", mono && "fc-mono")} lang={titleLang}>{title}</span>
          {sub ? <span className="fc-list-sub" lang={subLang}>{sub}</span> : null}
        </span>
        {side ? <span className="fc-list-side">{side}</span> : null}
        <Icon name="chevronRight" />
      </button>
    </li>
  );
}

/** ``nowrap`` keeps short values such as times on one line. */
export type RecordColumn<T> = { key: string; label: string; render?: (row: T) => ReactNode; mono?: boolean; numeric?: boolean; nowrap?: boolean };

/** A console table: 20 rows a page, cards on a phone with each cell labelled, and an empty state. */
export function RecordTable<T>({ rows, columns, rowKey, title, label, empty }: {
  rows: T[]; columns: RecordColumn<T>[]; rowKey: (row: T) => string; title?: ReactNode; label: string; empty?: string;
}) {
  const { t, formatNumber } = useI18n();
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const shown = rows.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE);
  return (
    <section className="box" aria-label={label}>
      {title ? <div className="box-head"><h2 className="box-title">{title}</h2></div> : null}
      {rows.length ? (
        <div style={{ overflowX: "auto" }}>
          <table className="tbl tbl-cards">
            <thead>
              <tr>{columns.map((column) => <th key={column.key} scope="col" className={column.numeric ? "num" : undefined}>{column.label}</th>)}</tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr key={rowKey(row)}>
                  {columns.map((column) => (
                    <td key={column.key} data-label={column.label} className={cx(column.numeric && "num", column.mono && "fc-mono")} style={column.nowrap ? { whiteSpace: "nowrap" } : undefined}>
                      {column.render ? column.render(row) : String((row as Record<string, unknown>)[column.key] ?? "—")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <Empty title={empty ?? t("ui.noItems")} />}
      {rows.length ? (
        <div className="pager">
          <span>{t("ui.rowsN", { n: formatNumber(rows.length) })}</span>
          {pages > 1 ? (
            <div className="toolbar">
              <span>{t("ui.pageOf", { n: current + 1, m: pages })}</span>
              <button type="button" className="fc-btn fc-btn-sm" disabled={current === 0} onClick={() => setPage(current - 1)}><Icon name="arrowLeft" />{t("ui.prev")}</button>
              <button type="button" className="fc-btn fc-btn-sm" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>{t("ui.next")}</button>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
