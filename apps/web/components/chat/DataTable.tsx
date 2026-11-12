"use client";

// The result rows (DECISIONS §2: TanStack Table): sortable columns formatted by type and format, 20 rows a
// page, a notice when the result was cut; below 640px of container width rows become cards (fc-stackable).

import { flexRender, getCoreRowModel, getPaginationRowModel, getSortedRowModel, useReactTable, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { useMemo, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { Button } from "@/components/ui/controls";
import { formatCell, download, toCsv } from "@/lib/chart/toEChartsOption";
import type { Cell, Result } from "@/lib/contracts";
import { cx } from "@/lib/cx";
import { useI18n } from "@/lib/i18n/react";

const PAGE_SIZE = 20;

export function DataTable({ result, title, fileName = "fitcher-result" }: { result: Result; title?: string | false; fileName?: string }) {
  const { t, locale, formatNumber } = useI18n();
  const [sorting, setSorting] = useState<SortingState>([]);
  const columns = useMemo<ColumnDef<Cell[]>[]>(
    () => result.columns.map((column, index) => ({ id: column.name, accessorFn: (row) => row[index], header: column.name, cell: (info) => formatCell(info.getValue(), column, locale) })),
    [result.columns, locale],
  );
  const table = useReactTable({
    data: result.rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: PAGE_SIZE } },
  });
  const numeric = (name: string) => result.columns.find((column) => column.name === name)?.type === "number";
  const pages = table.getPageCount();
  const page = table.getState().pagination.pageIndex;

  return (
    <section className="fc-card" style={{ overflow: "hidden" }}>
      {title === false ? null : (
        <div className="fc-card-head">
          <h3 className="fc-card-title">{title ?? t("ui.data")}</h3>
          <Button variant="ghost" size="sm" icon="download" onClick={() => download(new Blob([toCsv(result)], { type: "text/csv" }), `${fileName}.csv`)}>{t("ui.exportCsv")}</Button>
        </div>
      )}
      <div className="fc-table-wrap">
        <div className="fc-table-scroll" tabIndex={0} role="region" aria-label={t("ui.data")}>
          <table className="fc-table fc-stackable">
            <thead>
              {table.getHeaderGroups().map((group) => (
                <tr key={group.id}>
                  {group.headers.map((header) => {
                    const sorted = header.column.getIsSorted();
                    return (
                      <th key={header.id} scope="col" className={numeric(header.id) ? "fc-r" : undefined} aria-sort={sorted ? (sorted === "asc" ? "ascending" : "descending") : "none"}>
                        <button type="button" className="fc-th-btn fc-mono" title={t("ui.sortBy", { col: header.id })} onClick={header.column.getToggleSortingHandler()}>
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          <Icon name={sorted === "asc" ? "chevronUp" : sorted === "desc" ? "chevronDown" : "arrowUpDown"} />
                        </button>
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} data-label={cell.column.id} className={cx(numeric(cell.column.id) && "fc-r fc-num")}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="fc-table-foot">
        {result.truncated ? (
          <span className="fc-row" style={{ gap: "var(--base-size-4)" }}>
            <Icon name="info" />
            {t("ui.showingFirst", { n: formatNumber(result.rows.length), total: formatNumber(result.row_count) })}
          </span>
        ) : (
          <span>{t("ui.rowsN", { n: formatNumber(result.row_count) })}</span>
        )}
        {pages > 1 ? (
          <div className="fc-row">
            <span>{t("ui.pageOf", { n: page + 1, m: pages })}</span>
            <Button size="sm" variant="ghost" iconOnly icon="chevronLeft" label={t("ui.prev")} disabled={!table.getCanPreviousPage()} onClick={() => table.previousPage()} />
            <Button size="sm" variant="ghost" iconOnly icon="chevronRight" label={t("ui.next")} disabled={!table.getCanNextPage()} onClick={() => table.nextPage()} />
          </div>
        ) : null}
      </div>
    </section>
  );
}
