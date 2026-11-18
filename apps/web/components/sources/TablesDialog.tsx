"use client";

// The tables of a saved source (DECISIONS §4, §14): which ones to use, read live or copied, how often a copy
// refreshes and which column an incremental copy follows. Each table says what fitcher proposes and why, a live
// table joined with another live table is flagged slow, and columns read as text are named. Saving starts
// preparing the chosen tables, and the dialog says when they are ready.

import { useEffect, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { formatBytes } from "@/components/sources/format";
import { useFailure } from "@/components/sources/connection";
import { Dialog } from "@/components/ui/overlay";
import type { FitcherApi } from "@/lib/api/client";
import type { SourceView, TableView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

export const INTERVALS = [900, 3600, 21_600, 86_400, 604_800];

type Choice = { selected: boolean; mode: "live" | "copy"; interval: number; cursor: string };

function Select({ label, value, onChange, children, disabled }: {
  label: string; value: string | number; onChange: (value: string) => void; children: React.ReactNode; disabled?: boolean;
}) {
  return (
    <div className="sel">
      <select className="fc-input fc-input-sm" aria-label={label} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>{children}</select>
      <Icon name="chevronDown" />
    </div>
  );
}

export function TablesDialog({ sources, source, onClose, onSaved, pollMs = 3000 }: {
  sources: FitcherApi["sources"];
  source: SourceView;
  onClose: () => void;
  /** The selection was saved; the page reloads its list. */
  onSaved: () => void;
  pollMs?: number;
}) {
  const { t, formatNumber } = useI18n();
  const failure = useFailure();
  const [tables, setTables] = useState<TableView[] | null>(null);
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [state, setState] = useState<"edit" | "saving" | "preparing" | "ready">("edit");
  const [error, setError] = useState<string | null>(null);
  const copyOnly = source.kind === "sqlserver";

  useEffect(() => {
    sources.tables(source.id).then((list) => {
      setTables(list);
      setChoices(Object.fromEntries(list.map((table) => [table.name, {
        selected: table.selected, mode: table.mode, interval: table.interval_seconds, cursor: table.cursor_column ?? "",
      }])));
    }).catch((cause) => setError(failure(cause)));
    // The dialog reads the tables once when it opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sources, source.id]);

  // After a save the chosen tables are prepared; the dialog follows the sync until it ends.
  useEffect(() => {
    if (state !== "preparing") return;
    const timer = setInterval(() => {
      sources.syncs(source.id).then(([latest]) => { if (latest && latest.status !== "running") setState("ready"); }).catch(() => undefined);
    }, pollMs);
    return () => clearInterval(timer);
  }, [state, sources, source.id, pollMs]);

  const change = (name: string, patch: Partial<Choice>) => setChoices((current) => ({ ...current, [name]: { ...current[name], ...patch } }));

  async function save() {
    if (!tables) return;
    setState("saving");
    setError(null);
    try {
      const saved = await sources.changeTables(source.id, {
        tables: tables.map((table) => ({
          name: table.name, selected: choices[table.name].selected, mode: choices[table.name].mode,
          interval_seconds: choices[table.name].interval, cursor_column: choices[table.name].cursor || null,
        })),
      });
      setTables(saved);
      onSaved();
      if (saved.some((table) => table.selected)) {
        await sources.sync(source.id);
        setState("preparing");
      } else setState("ready");
    } catch (cause) {
      setError(failure(cause));
      setState("edit");
    }
  }

  const used = tables ? tables.filter((table) => choices[table.name]?.selected).length : 0;
  const unknown = <span className="fc-muted">{t("onboarding.unknown")}</span>;
  const notApplicable = <span className="fc-muted">{t("sourcesPage.notApplicable")}</span>;
  const done = state === "preparing" || state === "ready";
  return (
    <Dialog open wide title={t("sourcesPage.tablesOf", { name: source.id })} closeLabel={t("common.close")} onClose={onClose}
      actions={done ? (
        <>
          <span role="status" className="fc-muted dlg-status">
            {state === "preparing" ? <><span className="fc-spin fc-spinning" aria-hidden="true" />{t("sourcesPage.preparing")}</> : t("sourcesPage.prepared")}
          </span>
          <button type="button" className="fc-btn" onClick={onClose}>{t("common.close")}</button>
        </>
      ) : (
        <>
          <button type="button" className="fc-btn" onClick={onClose}>{t("common.cancel")}</button>
          <button type="button" className="fc-btn fc-btn-primary" disabled={!tables || state === "saving"} onClick={() => void save()}>
            {state === "saving" ? <span className="fc-spin fc-spinning" aria-hidden="true" /> : null}{t("sourcesPage.saveTables")}
          </button>
        </>
      )}>
      {tables ? <p className="fc-muted" style={{ margin: 0 }}>{t("sourcesPage.tablesUsed", { used, total: tables.length })}</p> : null}
      {error ? <div className="fc-banner fc-banner-danger" role="alert"><Icon name="alert" /><div>{error}</div></div> : null}
      {tables ? (
        <div className="box tables-scroll">
          <table className="tbl tables-edit">
            <thead>
              <tr>
                <th><span className="fc-sr">{t("sourcesPage.use")}</span></th><th>{t("onboarding.table")}</th>
                <th className="num">{t("onboarding.rows")}</th><th className="num">{t("onboarding.size")}</th>
                <th>{t("onboarding.readMode")}</th><th>{t("sourcesPage.refresh")}</th><th>{t("sourcesPage.newRowsOnly")}</th>
              </tr>
            </thead>
            <tbody>
              {tables.map((table) => {
                const choice = choices[table.name];
                if (!choice) return null;
                const copy = choice.mode === "copy";
                return (
                  <tr key={table.name}>
                    <td style={{ width: 40, paddingRight: 0 }}>
                      <input type="checkbox" aria-label={t("sourcesPage.useTable", { name: table.name })} checked={choice.selected} disabled={done}
                        onChange={(event) => change(table.name, { selected: event.target.checked })} />
                    </td>
                    <td>
                      <span className="fc-mono">{table.name}</span>
                      {table.kind === "view" ? <> <span className="fc-label">view</span></> : null}
                      {table.slow ? <div className="fc-field-help">{t("sources.slow")}</div> : null}
                      {table.unusual_columns.length ? (
                        <div className="fc-field-help">{t("sourcesPage.readAsText")} <span className="fc-mono">{table.unusual_columns.join(", ")}</span></div>
                      ) : null}
                    </td>
                    <td className="num">{table.rows === null ? unknown : formatNumber(table.rows)}</td>
                    <td className="num">{table.size_bytes === null ? unknown : formatBytes(table.size_bytes)}</td>
                    <td>
                      <Select label={t("sourcesPage.modeOf", { name: table.name })} value={choice.mode} disabled={done}
                        onChange={(value) => change(table.name, { mode: value as Choice["mode"] })}>
                        {copyOnly ? null : <option value="live">{t("sources.live")}</option>}
                        <option value="copy">{t("sources.copy")}</option>
                      </Select>
                      <span className="fc-field-help">{t("sourcesPage.proposed", { mode: t(`sources.${table.proposed_mode}`), why: t(`sources.why_${table.reason}`) })}</span>
                    </td>
                    <td>
                      {copy ? (
                        <Select label={t("sourcesPage.refreshOf", { name: table.name })} value={choice.interval} disabled={done}
                          onChange={(value) => change(table.name, { interval: Number(value) })}>
                          {(INTERVALS.includes(choice.interval) ? INTERVALS : [choice.interval, ...INTERVALS]).map((seconds) => (
                            <option key={seconds} value={seconds}>{t(`sources.every_${seconds}`)}</option>
                          ))}
                        </Select>
                      ) : notApplicable}
                    </td>
                    <td>
                      {copy ? (
                        <Select label={t("sourcesPage.cursorOf", { name: table.name })} value={choice.cursor} disabled={done}
                          onChange={(value) => change(table.name, { cursor: value })}>
                          <option value="">{t("sourcesPage.reloadAll")}</option>
                          {table.cursor_candidates.map((column) => <option key={column} value={column}>{column}</option>)}
                        </Select>
                      ) : notApplicable}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : error ? null : <p className="fc-muted" role="status"><span className="fc-spin fc-spinning" aria-hidden="true" /> {t("sourcesPage.loadingTables")}</p>}
      <p className="fc-field-help" style={{ margin: 0 }}>{t("sourcesPage.tablesNote")}</p>
    </Dialog>
  );
}
