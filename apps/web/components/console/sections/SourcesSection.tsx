"use client";

// Sources (DECISIONS §4, §15): the databases and files fitcher reads, one row each with the tables in use, the
// last sync and its status. A row syncs now, cancels a running sync or retries a failed one; its menu edits the
// connection, builds or rebuilds the pack, or deletes the source after its name is typed. A source whose pack no
// longer matches its tables is named above the list with what changed. A saved password is never shown again, and
// a failure is one fixed message, never the database's own text. Adding a source and building a pack open their
// own pages, which reuse the setup's Data and Start steps.

import { useCallback, useEffect, useState, type MouseEvent } from "react";

import { Icon } from "@/components/brand/Icon";
import { useConsole } from "@/components/console/ConsoleLayout";
import { ListPage } from "@/components/console/ListPage";
import { DatabaseFields } from "@/components/setup/DataStep";
import { connectionBody, useFailure, type ConnectionValues } from "@/components/sources/connection";
import { TablesDialog } from "@/components/sources/TablesDialog";
import { Dialog, Menu } from "@/components/ui/overlay";
import type { FitcherApi } from "@/lib/api/client";
import { SourceError } from "@/lib/api/http/sources";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import type { SourceDrift, SourcePatch, SourceView, TableDrift } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

const POLL_MS = 3000;
const TONE: Record<string, string> = { succeeded: "fc-label-success", failed: "fc-label-danger", running: "fc-label-accent", cancelled: "" };

function EditDialog({ sources, source, onClose, onSaved }: { sources: FitcherApi["sources"]; source: SourceView; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const failure = useFailure();
  const [values, setValues] = useState<ConnectionValues>({
    kind: source.kind === "file" ? "postgres" : source.kind, name: source.id, host: source.host ?? "", port: source.port ? String(source.port) : "",
    database: source.database ?? "", schema_name: source.schema_name ?? "", user: source.user ?? "", password: "", tls_mode: source.tls_mode, ca_certificate: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const body = connectionBody(values);
      const patch: SourcePatch = { host: body.host, database: body.database, user: body.user, tls_mode: body.tls_mode };
      if (body.port) patch.port = body.port;
      if (body.schema_name) patch.schema_name = body.schema_name;
      if (values.password) patch.password = values.password;
      if (values.ca_certificate.trim()) patch.ca_certificate = values.ca_certificate;
      await sources.update(source.id, patch);
      onSaved();
      onClose();
    } catch (cause) {
      setError(failure(cause));
      setBusy(false);
    }
  }

  return (
    <Dialog open title={t("sourcesPage.editTitle", { name: source.id })} closeLabel={t("common.close")} onClose={onClose}
      actions={<>
        <button type="button" className="fc-btn" onClick={onClose}>{t("common.cancel")}</button>
        <button type="button" className="fc-btn fc-btn-primary" disabled={busy} onClick={() => void save()}>{t("sources.save")}</button>
      </>}>
      <p className="fc-muted" style={{ margin: 0 }}>{t("onboarding.dbSub")}</p>
      <DatabaseFields editing values={values} onChange={(patch) => setValues({ ...values, ...patch })} name={source.id} disabled={busy} invalid={Boolean(error)} />
      {error ? <div className="fc-field-error" id="db-error" role="alert"><Icon name="alert" />{error}</div> : null}
    </Dialog>
  );
}

function DeleteDialog({ sources, source, onClose, onDeleted }: { sources: FitcherApi["sources"]; source: SourceView; onClose: () => void; onDeleted: () => void }) {
  const { t } = useI18n();
  const failure = useFailure();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await sources.remove(source.id, typed);
      onDeleted();
      onClose();
    } catch (cause) {
      setError(cause instanceof SourceError && cause.marts?.length ? t("sourcesPage.inUse", { marts: cause.marts.join(", ") }) : failure(cause));
      setBusy(false);
    }
  }

  return (
    <Dialog open tone="danger" title={t("sources.deleteTitle", { name: source.id })} closeLabel={t("common.close")} onClose={onClose}
      actions={<>
        <button type="button" className="fc-btn" onClick={onClose}>{t("common.cancel")}</button>
        <button type="button" className="fc-btn fc-btn-danger" disabled={busy || typed !== source.id} onClick={() => void remove()}>{t("sources.delete")}</button>
      </>}>
      <p style={{ margin: 0 }}>{t("sourcesPage.deleteText")}</p>
      <div className="fc-field">
        <label className="fc-field-label" htmlFor="delete-name">{t("sources.sourceName")}</label>
        <input id="delete-name" className="fc-input" autoComplete="off" value={typed} onChange={(event) => setTyped(event.target.value)} />
      </div>
      {error ? <div className="fc-banner fc-banner-danger" role="alert"><Icon name="alert" /><div>{error}</div></div> : null}
    </Dialog>
  );
}

function LastSync({ source }: { source: SourceView }) {
  const { t, formatDate, formatNumber } = useI18n();
  const sync = source.last_sync;
  if (!sync) return <span className="fc-muted">{t("sources.never")}</span>;
  if (sync.status === "running") return <span>{t("sourcesPage.syncRunning")}</span>;
  const rows = sync.results.reduce((total, result) => total + (typeof result.rows === "number" ? result.rows : 0), 0);
  return (
    <span>
      {formatDate(sync.finished_at ?? sync.started_at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
      {sync.status === "succeeded" ? ` · ${t("sources.rowsLoaded", { rows: formatNumber(rows) })}` : null}
    </span>
  );
}

/** Whether questions can be asked about the source: its pack is ready, being built, failed or not built yet. */
function Answers({ source, onBuild, onAsk }: { source: SourceView; onBuild: () => void; onAsk: () => void }) {
  const { t } = useI18n();
  const state = source.pack?.status ?? "none";
  if (state === "ready") {
    return (
      <span className="src-answers">
        <span className="fc-label fc-label-success">{t("sourcesPage.answer_ready")}</span>
        <button type="button" className="fc-btn fc-btn-sm" aria-label={t("sourcesPage.askOf", { name: source.id })} onClick={onAsk}>
          <Icon name="message" />{t("sourcesPage.ask")}
        </button>
      </span>
    );
  }
  if (state === "building") {
    return <span className="fc-label"><span className="fc-spin fc-spinning" aria-hidden="true" />{t("sourcesPage.answer_building")}</span>;
  }
  const ready = source.last_sync?.status === "succeeded" && source.selected_count > 0;
  return (
    <span className="src-answers">
      {state === "failed" ? <span className="fc-label fc-label-danger" title={source.pack?.error ?? undefined}>{t("sourcesPage.answer_failed")}</span>
        : <span className="fc-label fc-label-attention">{t("sourcesPage.answer_none")}</span>}
      <button type="button" className="fc-btn fc-btn-primary fc-btn-sm" disabled={!ready} title={ready ? undefined : t("sourcesPage.syncFirst")}
        aria-label={t("sourcesPage.buildOf", { name: source.id })} onClick={onBuild}>
        <Icon name="sparkles" />{state === "failed" ? t("sourcesPage.buildAgain") : t("sourcesPage.buildToAsk")}
      </button>
      {state === "failed" && source.pack?.error ? <span className="fc-field-error src-answers-error">{source.pack.error}</span> : null}
    </span>
  );
}

export function SourcesSection() {
  const { t } = useI18n();
  const { api, pack, loaded, choosePack } = useChat();
  const { navigate } = useConsole();
  const sources = api.sources;
  const failure = useFailure();
  const { data, failed, reload } = useLoad(useCallback(() => sources.list(), [sources]));
  const [drifts, setDrifts] = useState<Record<string, SourceDrift>>({});
  const [menu, setMenu] = useState<{ anchor: HTMLElement; source: SourceView } | null>(null);
  const [dialog, setDialog] = useState<{ kind: "tables" | "edit" | "delete"; source: SourceView } | null>(null);
  const [adding, setAdding] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Columns that changed since a source's pack was built (DECISIONS §11 step 0).
  const syncIds = (data ?? []).map((source) => `${source.id}:${source.last_sync?.id ?? ""}`).join(",");
  useEffect(() => {
    let live = true;
    void Promise.all((data ?? []).map((source) => sources.drift(source.id).then((drift) => [source.id, drift] as const).catch(() => null)))
      .then((pairs) => { if (live) setDrifts(Object.fromEntries(pairs.filter((pair): pair is readonly [string, SourceDrift] => Boolean(pair)))); });
    return () => { live = false; };
    // Read again when a sync finishes or the list changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sources, syncIds]);

  // A running sync or pack build is read again until it ends, so its outcome shows without reloading the page.
  const running = (data ?? []).some((source) => source.last_sync?.status === "running" || source.pack?.status === "building");
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => void reload(), POLL_MS);
    return () => clearInterval(timer);
  }, [running, reload]);

  async function act(source: SourceView, action: () => Promise<unknown>) {
    setErrors((current) => ({ ...current, [source.id]: "" }));
    try {
      await action();
      await reload();
    } catch (cause) {
      setErrors((current) => ({ ...current, [source.id]: failure(cause) }));
    }
  }

  const changeLine = (change: TableDrift) => {
    if (change.missing) return t("sourcesPage.driftMissing");
    return [
      change.added.length ? t("sourcesPage.driftAdded", { columns: change.added.join(", ") }) : "",
      change.removed.length ? t("sourcesPage.driftRemoved", { columns: change.removed.join(", ") }) : "",
      ...change.retyped.map((item) => t("sourcesPage.driftRetyped", { column: item.column, before: item.before, after: item.after })),
    ].filter(Boolean).join(", ");
  };
  const build = (source: SourceView) => navigate(`/console/sources/${encodeURIComponent(source.id)}/pack`);
  // A new conversation answered from this source's pack.
  const askFrom = (source: SourceView) => {
    choosePack(source.pack?.name ?? source.id);
    window.location.assign("/");
  };
  const drifted = (data ?? []).filter((source) => drifts[source.id]?.pack && drifts[source.id].changes.length);
  const add = <button type="button" className="fc-btn fc-btn-primary" onClick={() => setAdding(true)}><Icon name="plus" />{t("sources.add")}</button>;

  // Without an active pack the other pages have nothing to read: say so here, where the pack is built.
  const buildable = loaded && !pack ? (data ?? []).find((source) => source.last_sync?.status === "succeeded" && source.selected_count > 0) : undefined;

  return (
    <ListPage section="sources" loading={!data} failed={failed} actions={data?.length ? add : undefined}>
      {buildable ? (
        <div className="fc-banner fc-banner-attention" role="status">
          <Icon name="alert" />
          <div style={{ flex: 1 }}><b>{t("sourcesPage.noPackTitle")}</b><div>{t("sourcesPage.noPackText")}</div></div>
          <button type="button" className="fc-btn fc-btn-sm fc-btn-primary" onClick={() => build(buildable)}>{t("sources.build")}</button>
        </div>
      ) : null}
      {drifted.map((source) => (
        <div key={source.id} className="fc-banner fc-banner-attention" role="status">
          <Icon name="alert" />
          <div style={{ flex: 1 }}>
            <b>{t("sourcesPage.driftTitle", { pack: drifts[source.id].pack ?? "", name: source.id })}</b>
            <ul className="drift-list">
              {drifts[source.id].changes.map((change) => <li key={change.table}><span className="fc-mono">{change.table}</span>: {changeLine(change)}</li>)}
            </ul>
          </div>
          <button type="button" className="fc-btn fc-btn-sm" aria-label={t("sources.rebuildOf", { name: source.id })} onClick={() => build(source)}>{t("sources.rebuild")}</button>
        </div>
      ))}
      {data && !data.length ? (
        <div className="box">
          <div className="empty">
            <div className="empty-icon"><Icon name="database" size="lg" /></div>
            <p className="empty-title">{t("sourcesPage.emptyTitle")}</p>
            <p className="empty-text">{t("sourcesPage.emptyText")}</p>
            {add}
          </div>
        </div>
      ) : null}
      {data?.length ? (
        <section className="box" aria-labelledby="sources-title">
          <div className="box-head"><h2 id="sources-title" className="box-title">{t("sourcesPage.listTitle")}</h2></div>
          <div style={{ overflowX: "auto" }}>
            <table className="tbl tbl-cards">
              <thead>
                <tr>
                  <th>{t("sourcesPage.source")}</th><th>{t("sourcesPage.tablesUsedHead")}</th><th>{t("sourcesPage.lastSync")}</th>
                  <th>{t("ui.status")}</th><th>{t("sourcesPage.answersHead")}</th><th><span className="fc-sr">{t("ui.actions")}</span></th>
                </tr>
              </thead>
              <tbody>
                {data.map((source) => {
                  const status = source.last_sync?.status;
                  const syncError = source.last_sync?.error ? t(`sources.reason_${source.last_sync.error}`) : null;
                  const rowError = errors[source.id] || null;
                  return (
                    <tr key={source.id} aria-label={source.id}>
                      <td>
                        <div className="src-cell">
                          <Icon name={source.kind === "file" ? "fileText" : "database"} />
                          <div style={{ minWidth: 0 }}>
                            {source.kind === "file" ? <span className="fc-mono src-name">{source.id}</span> : (
                              <button type="button" className="fc-mono src-name src-link" aria-label={t("sources.editOf", { name: source.id })}
                                onClick={() => setDialog({ kind: "edit", source })}>{source.id}</button>
                            )}
                            <div className="fc-muted src-kind">{t(`sources.kind_${source.kind}`)}</div>
                            {status === "failed" && syncError ? <div className="fc-field-error"><Icon name="alert" />{syncError}</div> : null}
                            {rowError ? <div className="fc-field-error" role="alert"><Icon name="alert" />{rowError}</div> : null}
                          </div>
                        </div>
                      </td>
                      <td data-label={t("sourcesPage.tablesUsedHead")}>
                        {source.kind === "file" ? t("sourcesPage.tableCount", { used: source.selected_count, total: source.table_count }) : (
                          <button type="button" className="fc-link" aria-label={t("sources.tablesButton", { name: source.id })}
                            onClick={() => setDialog({ kind: "tables", source })}>{t("sourcesPage.tableCount", { used: source.selected_count, total: source.table_count })}</button>
                        )}
                      </td>
                      <td data-label={t("sourcesPage.lastSync")}><LastSync source={source} /></td>
                      <td data-label={t("ui.status")}>
                        {status ? (
                          <span className={`fc-label ${TONE[status] ?? ""}`}>
                            {status === "running" ? <span className="fc-spin fc-spinning" aria-hidden="true" /> : null}{t(`sources.status_${status}`)}
                          </span>
                        ) : <span className="fc-muted">{t("sources.never")}</span>}
                      </td>
                      <td data-label={t("sourcesPage.answersHead")}>
                        <Answers source={source} onBuild={() => build(source)} onAsk={() => askFrom(source)} />
                      </td>
                      <td className="row-actions">
                        {status === "running" ? (
                          <button type="button" className="fc-btn fc-btn-sm" aria-label={t("sources.cancelOf", { name: source.id })}
                            onClick={() => void act(source, () => sources.cancel(source.id))}>{t("sources.cancel")}</button>
                        ) : (
                          <button type="button" className={status === "failed" ? "fc-btn fc-btn-sm" : "fc-btn fc-btn-ghost fc-btn-sm"} aria-label={t("sources.syncOf", { name: source.id })}
                            disabled={source.selected_count === 0} onClick={() => void act(source, () => sources.sync(source.id))}>
                            <Icon name="refresh" />{status === "failed" ? t("sourcesPage.retry") : t("sourcesPage.sync")}
                          </button>
                        )}
                        <button type="button" className="fc-btn fc-btn-ghost fc-btn-icon fc-btn-sm" aria-label={t("sourcesPage.optionsOf", { name: source.id })} aria-haspopup="menu"
                          onClick={(event: MouseEvent<HTMLButtonElement>) => setMenu({ anchor: event.currentTarget, source })}><Icon name="more" /></button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
      {menu ? (
        <Menu anchor={menu.anchor} align="end" width={200} label={t("sourcesPage.optionsOf", { name: menu.source.id })} onClose={() => setMenu(null)} items={[
          ...(menu.source.kind === "file" ? [] : [{ icon: "pencil", label: t("sources.edit"), onSelect: () => setDialog({ kind: "edit", source: menu.source }) }]),
          { icon: "refresh", label: drifts[menu.source.id]?.pack ? t("sources.rebuild") : t("sources.build"), disabled: menu.source.selected_count === 0, onSelect: () => build(menu.source) },
          { separator: true },
          { icon: "trash", label: t("sources.delete"), danger: true, onSelect: () => setDialog({ kind: "delete", source: menu.source }) },
        ]} />
      ) : null}
      {adding ? (
        <Dialog open title={t("sourcesPage.addTitle")} closeLabel={t("common.close")} onClose={() => setAdding(false)}
          actions={<button type="button" className="fc-btn" onClick={() => setAdding(false)}>{t("common.cancel")}</button>}>
          <p className="fc-muted" style={{ margin: 0 }}>{t("sourcesPage.readOnly")}</p>
          <div className="opt-list">
            {(["file", "database"] as const).map((kind) => (
              <button key={kind} type="button" className="opt" onClick={() => navigate(`/console/sources/new?kind=${kind}`)}>
                <span className="opt-icon"><Icon name={kind === "file" ? "upload" : "database"} /></span>
                <span className="opt-body">
                  <span className="opt-title">{t(kind === "file" ? "onboarding.fileCard" : "onboarding.dbCard")}</span>
                  <span className="opt-desc">{t(kind === "file" ? "onboarding.fileDesc" : "onboarding.dbDesc")}</span>
                </span>
                <Icon name="chevronRight" />
              </button>
            ))}
          </div>
        </Dialog>
      ) : null}
      {dialog?.kind === "tables" ? <TablesDialog sources={sources} source={dialog.source} onClose={() => setDialog(null)} onSaved={() => void reload()} /> : null}
      {dialog?.kind === "edit" ? <EditDialog sources={sources} source={dialog.source} onClose={() => setDialog(null)} onSaved={() => void reload()} /> : null}
      {dialog?.kind === "delete" ? <DeleteDialog sources={sources} source={dialog.source} onClose={() => setDialog(null)} onDeleted={() => void reload()} /> : null}
    </ListPage>
  );
}
