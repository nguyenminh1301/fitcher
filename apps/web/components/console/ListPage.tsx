"use client";

// The console's list pages (docs/design/web-app.md, Workspace console): a page head with the section's
// title, description and Sample data badge, a page skeleton while loading, list rows that open a detail
// page, and tables of 20 rows a page that become cards on phones.

import { useState, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { Button } from "@/components/ui/controls";
import { EmptyState, Skeleton } from "@/components/ui/feedback";
import { SampleDataBadge } from "@/components/ui/SampleDataBadge";
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
  const feature = SECTIONS.find((item) => item.key === section)?.feature;
  let body: ReactNode = children;
  if (failed) body = <div className="fc-card"><EmptyState icon="alert" title={t("ui.loadFailed")} /></div>;
  else if (loading) body = <Skeleton variant={skeleton} rows={8} />;
  return (
    <div className="fc-page">
      <div className="fc-page-head">
        <div className="fc-row">
          <h1>{t(`ui.nav_${section}`)}</h1>
          {feature ? <SampleDataBadge feature={feature} /> : null}
        </div>
        {actions ?? null}
      </div>
      <p className="fc-page-desc">{t(`ui.desc_${section}`)}</p>
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

/** A console table: 20 rows a page, cards below 640px, each cell labelled for the card view. */
export function RecordTable<T>({ rows, columns, rowKey, title, label }: {
  rows: T[]; columns: RecordColumn<T>[]; rowKey: (row: T) => string; title?: ReactNode; label: string;
}) {
  const { t, formatNumber } = useI18n();
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const shown = rows.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE);
  return (
    <section className="fc-card" style={{ overflow: "hidden" }} aria-label={label}>
      {title ? <div className="fc-card-head"><h2 className="fc-card-title">{title}</h2></div> : null}
      <div className="fc-table-wrap">
        <div className="fc-table-scroll">
          <table className="fc-table fc-stackable">
            <thead>
              <tr>
                {columns.map((column) => <th key={column.key} scope="col" className={column.numeric ? "fc-r" : undefined}>{column.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr key={rowKey(row)}>
                  {columns.map((column) => (
                    <td key={column.key} data-label={column.label} className={cx(column.numeric && "fc-r fc-num", column.mono && "fc-mono")} style={column.nowrap ? { whiteSpace: "nowrap" } : undefined}>
                      {column.render ? column.render(row) : String((row as Record<string, unknown>)[column.key] ?? "—")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {rows.length === 0 ? <EmptyState title={t("ui.noItems")} /> : null}
      <div className="fc-table-foot">
        <span>{t("ui.rowsN", { n: formatNumber(rows.length) })}</span>
        {pages > 1 ? (
          <div className="fc-row">
            <span>{t("ui.pageOf", { n: current + 1, m: pages })}</span>
            <Button size="sm" variant="ghost" iconOnly icon="chevronLeft" label={t("ui.prev")} disabled={current === 0} onClick={() => setPage(current - 1)} />
            <Button size="sm" variant="ghost" iconOnly icon="chevronRight" label={t("ui.next")} disabled={current >= pages - 1} onClick={() => setPage(current + 1)} />
          </div>
        ) : null}
      </div>
    </section>
  );
}
