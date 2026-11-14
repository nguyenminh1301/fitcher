"use client";

// The tables of a source: size, keys, the proposed mode and why, and the choices that make a source useful:
// which tables to use, live or copy, how often a copy refreshes and which column an incremental copy follows
// (DECISIONS §4, §14). Sizes and row counts are estimates from the source's own statistics. Live tables joined
// with another live table are flagged slow, and columns ClickHouse reads as text are marked.

import { useState } from "react";

import { formatBytes } from "@/components/sources/format";
import { Button } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import type { FitcherApi } from "@/lib/api/client";
import type { TableView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

export const INTERVALS = [900, 3600, 21_600, 86_400, 604_800];

function message(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

/** What the page tells about a table before it is chosen: estimates, the proposed mode and flags. */
export function TableFacts({ table }: { table: TableView }) {
  const { t, formatNumber } = useI18n();
  return (
    <>
      <td data-label={t("sources.rows")} className="fc-r fc-num">
        {table.rows === null ? "—" : `≈ ${formatNumber(table.rows)}`}
      </td>
      <td data-label={t("sources.size")} className="fc-r fc-num" style={{ whiteSpace: "nowrap" }}>
        {table.size_bytes === null ? "—" : `≈ ${formatBytes(table.size_bytes)}`}
      </td>
      <td data-label={t("sources.proposedMode")}>
        <strong>{t(`sources.${table.proposed_mode}`)}</strong>
        <span className="fc-muted" style={{ display: "block" }}>{t(`sources.why_${table.reason}`)}</span>
      </td>
    </>
  );
}

function Notes({ table }: { table: TableView }) {
  const { t } = useI18n();
  return (
    <>
      {table.kind === "view" ? <span className="fc-pill fc-pill-neutral">{t("sources.view")}</span> : null}
      {table.slow ? <span className="fc-muted" style={{ display: "block" }}>{t("sources.slow")}</span> : null}
      {table.unusual_columns.length ? (
        <span className="fc-muted" style={{ display: "block" }}>{t("sources.unusual", { columns: table.unusual_columns.join(", ") })}</span>
      ) : null}
    </>
  );
}

/** The tables found by a test, before anything is saved. */
export function TableList({ tables, copyOnly }: { tables: TableView[]; copyOnly?: boolean }) {
  const { t } = useI18n();
  return (
    <div className="fc-stack" style={{ gap: "var(--base-size-8)" }}>
      <div className="fc-table-scroll">
        <table className="fc-table" aria-label={t("sources.tables")}>
          <thead>
            <tr>
              <th scope="col">{t("sources.table")}</th><th scope="col" className="fc-r">{t("sources.rows")}</th>
              <th scope="col" className="fc-r">{t("sources.size")}</th><th scope="col">{t("sources.proposedMode")}</th>
            </tr>
          </thead>
          <tbody>
            {tables.map((table) => (
              <tr key={table.name} aria-label={table.name}>
                <td><span className="fc-mono">{table.name}</span><Notes table={table} /></td>
                <TableFacts table={table} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="fc-muted" style={{ margin: 0 }}>{t("sources.approx")}</p>
      {copyOnly ? <p className="fc-muted" style={{ margin: 0 }}>{t("sources.copyOnly")}</p> : null}
    </div>
  );
}

type Choice = { selected: boolean; mode: "live" | "copy"; interval: number; cursor: string };

export function TableChooser({ sources, id, tables, copyOnly, onSaved, onSynced }: {
  sources: FitcherApi["sources"];
  id: string;
  tables: TableView[];
  /** The source cannot be read live (SQL Server): every table is copied. */
  copyOnly?: boolean;
  onSaved?: (tables: TableView[]) => void;
  /** Called after a sync was started, so the page shows it running. */
  onSynced?: () => void;
}) {
  const { t } = useI18n();
  const [choices, setChoices] = useState<Record<string, Choice>>(() => Object.fromEntries(tables.map((table) => [table.name, {
    selected: table.selected, mode: table.mode, interval: table.interval_seconds, cursor: table.cursor_column ?? "",
  }])));
  const [shown, setShown] = useState(tables);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const change = (name: string, patch: Partial<Choice>) => {
    setSaved(false);
    setChoices((current) => ({ ...current, [name]: { ...current[name], ...patch } }));
  };

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const result = await sources.changeTables(id, {
        tables: shown.map((table) => ({
          name: table.name, selected: choices[table.name].selected, mode: choices[table.name].mode,
          interval_seconds: choices[table.name].interval, cursor_column: choices[table.name].cursor || null,
        })),
      });
      setShown(result);
      setSaved(true);
      onSaved?.(result);
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }

  async function syncNow() {
    setBusy(true);
    setError(null);
    try {
      await sources.sync(id);
      onSynced?.();
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }

  const chosen = shown.some((table) => choices[table.name]?.selected);
  return (
    <div className="fc-stack" style={{ gap: "var(--base-size-12)" }}>
      <div className="fc-table-scroll">
        <table className="fc-table" aria-label={t("sources.tables")}>
          <thead>
            <tr>
              <th scope="col">{t("sources.table")}</th><th scope="col" className="fc-r">{t("sources.rows")}</th>
              <th scope="col" className="fc-r">{t("sources.size")}</th><th scope="col">{t("sources.proposedMode")}</th>
              <th scope="col">{t("sources.mode")}</th><th scope="col">{t("sources.copySettings")}</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((table) => {
              const choice = choices[table.name];
              return (
                <tr key={table.name} aria-label={table.name}>
                  <td>
                    <label className="fc-row" style={{ gap: "var(--base-size-8)" }}>
                      <input type="checkbox" aria-label={t("sources.use", { name: table.name })} checked={choice.selected}
                        onChange={(event) => change(table.name, { selected: event.target.checked })} />
                      <span className="fc-mono">{table.name}</span>
                    </label>
                    <Notes table={table} />
                  </td>
                  <TableFacts table={table} />
                  <td data-label={t("sources.mode")}>
                    <select className="fc-input" aria-label={t("sources.modeOf", { name: table.name })} value={choice.mode}
                      onChange={(event) => change(table.name, { mode: event.target.value as "live" | "copy" })}>
                      {copyOnly ? null : <option value="live">{t("sources.live")}</option>}
                      <option value="copy">{t("sources.copy")}</option>
                    </select>
                  </td>
                  <td data-label={t("sources.copySettings")}>
                    {choice.mode === "copy" ? (
                      <span className="fc-stack" style={{ gap: "var(--base-size-4)" }}>
                        <select className="fc-input" aria-label={t("sources.intervalOf", { name: table.name })} value={choice.interval}
                          onChange={(event) => change(table.name, { interval: Number(event.target.value) })}>
                          {(INTERVALS.includes(choice.interval) ? INTERVALS : [choice.interval, ...INTERVALS]).map((seconds) => (
                            <option key={seconds} value={seconds}>{t(`sources.every_${seconds}`)}</option>
                          ))}
                        </select>
                        <select className="fc-input" aria-label={t("sources.cursorOf", { name: table.name })} value={choice.cursor}
                          onChange={(event) => change(table.name, { cursor: event.target.value })}>
                          <option value="">{t("sources.cursorNone")}</option>
                          {table.cursor_candidates.map((column) => <option key={column} value={column}>{column}</option>)}
                        </select>
                      </span>
                    ) : <span className="fc-muted">—</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="fc-muted" style={{ margin: 0 }}>{t("sources.approx")} {t("sources.cursorHelp")}</p>
      {copyOnly ? <p className="fc-muted" style={{ margin: 0 }}>{t("sources.copyOnly")}</p> : null}
      {error ? <WarningBanner tone="danger">{t("sources.failed", { reason: error })}</WarningBanner> : null}
      {saved ? <p style={{ margin: 0 }} role="status">{t("sources.saved")}</p> : null}
      <div className="fc-row" style={{ gap: "var(--base-size-8)" }}>
        <Button variant="primary" disabled={busy} onClick={() => void save()}>{t("sources.saveTables")}</Button>
        {onSynced ? <Button disabled={busy || !chosen} onClick={() => void syncNow()}>{t("sources.syncNow")}</Button> : null}
      </div>
    </div>
  );
}
