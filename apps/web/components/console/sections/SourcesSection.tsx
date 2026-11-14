"use client";

// Sources (DECISIONS §4, §15): the databases and files fitcher reads, with their kind, address, chosen tables
// and the result of the last sync. An admin connects a source (the connection is tested and its tables listed
// before it is saved), chooses tables and a mode for each, refreshes a source now or cancels a running sync,
// replaces a password and deletes a source after typing its name. A saved password is never shown again; a
// failure is shown as one fixed message, never as the database's own text.

import { useCallback, useEffect, useState } from "react";

import { ListPage } from "@/components/console/ListPage";
import { ConnectionFields, connectionBody, SourceConnect, useFailure, type ConnectionValues } from "@/components/sources/SourceConnect";
import { TableChooser } from "@/components/sources/TableChooser";
import { Button, TextField } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import { Dialog } from "@/components/ui/overlay";
import type { FitcherApi } from "@/lib/api/client";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import type { SourcePatch, SourceView, TableView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

const POLL_MS = 3000;

function LastSync({ source, syncing }: { source: SourceView; syncing: boolean }) {
  const { t, formatDate, formatNumber } = useI18n();
  const sync = source.last_sync;
  if (syncing || sync?.status === "running") return <span className="fc-muted">{t("sources.syncing")}</span>;
  if (!sync) return <span className="fc-muted">{t("sources.never")}</span>;
  const rows = sync.results.reduce((total, result) => total + (typeof result.rows === "number" ? result.rows : 0), 0);
  return (
    <span className="fc-muted">
      {t(`sources.status_${sync.status}`)} · {formatDate(sync.finished_at ?? sync.started_at)}
      {sync.status === "succeeded" ? ` · ${t("sources.rowsLoaded", { rows: formatNumber(rows) })}` : null}
      {sync.error ? <> · {t(`sources.reason_${sync.error}`)}</> : null}
    </span>
  );
}

function EditForm({ sources, source, onDone }: { sources: FitcherApi["sources"]; source: SourceView; onDone: () => void }) {
  const { t } = useI18n();
  const failure = useFailure();
  const [values, setValues] = useState<ConnectionValues>({
    kind: source.kind === "file" ? "postgres" : source.kind, name: source.id, host: source.host ?? "", port: source.port ? String(source.port) : "",
    database: source.database ?? "", schema_name: source.schema_name ?? "", user: source.user ?? "", password: "", tls_mode: source.tls_mode,
    ca_certificate: "",
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
      if (values.kind === "postgres" && body.schema_name) patch.schema_name = body.schema_name;
      if (values.password) patch.password = values.password;
      if (values.ca_certificate.trim()) patch.ca_certificate = values.ca_certificate;
      await sources.update(source.id, patch);
      setValues({ ...values, password: "", ca_certificate: "" });
      onDone();
    } catch (cause) {
      setError(failure(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="fc-stack" style={{ gap: "var(--base-size-12)" }} onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <ConnectionFields values={values} onChange={setValues} disabled={busy} editing />
      {error ? <WarningBanner tone="danger">{error}</WarningBanner> : null}
      <div className="fc-row" style={{ gap: "var(--base-size-8)" }}>
        <Button type="submit" variant="primary" disabled={busy}>{t("sources.save")}</Button>
        <Button disabled={busy} onClick={onDone}>{t("common.cancel")}</Button>
      </div>
    </form>
  );
}

function SourceRow({ sources, source, syncing, onSyncing, onChanged, onDelete }: {
  sources: FitcherApi["sources"]; source: SourceView; syncing: boolean; onSyncing: (on: boolean) => void;
  onChanged: () => Promise<void>; onDelete: () => void;
}) {
  const { t } = useI18n();
  const failure = useFailure();
  const [panel, setPanel] = useState<"tables" | "edit" | null>(null);
  const [tables, setTables] = useState<TableView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const running = syncing || source.last_sync?.status === "running";

  async function toggleTables() {
    if (panel === "tables") return setPanel(null);
    setPanel("tables");
    try {
      setTables(await sources.tables(source.id));
    } catch (cause) {
      setError(failure(cause));
    }
  }

  async function syncNow() {
    setError(null);
    try {
      await sources.sync(source.id);
      onSyncing(true);
    } catch (cause) {
      setError(failure(cause));
    }
  }

  async function cancel() {
    try {
      await sources.cancel(source.id);
    } catch (cause) {
      setError(failure(cause));
    }
  }

  const address = source.kind === "file" ? t("sources.kind_file") : `${source.host}:${source.port} / ${source.database}`;
  return (
    <li className="fc-stack" style={{ gap: "var(--base-size-8)", padding: "var(--base-size-12) var(--base-size-16)" }} aria-label={source.id}>
      <div className="fc-row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: "var(--base-size-8)" }}>
        <span>
          <strong className="fc-mono">{source.id}</strong> <span className="fc-pill fc-pill-neutral">{t(`sources.kind_${source.kind}`)}</span>
          <span className="fc-muted" style={{ display: "block" }}>
            {address} · {t("sources.tablesOf", { selected: source.selected_count, count: source.table_count })}
          </span>
          <LastSync source={source} syncing={syncing} />
        </span>
        <span className="fc-row" style={{ gap: "var(--base-size-8)", flexWrap: "wrap" }}>
          {source.kind !== "file" ? <Button size="sm" aria-label={t("sources.tablesButton", { name: source.id })} onClick={() => void toggleTables()}>{t("sources.tables")}</Button> : null}
          {running ? (
            <Button size="sm" aria-label={t("sources.cancelOf", { name: source.id })} onClick={() => void cancel()}>{t("sources.cancel")}</Button>
          ) : (
            <Button size="sm" aria-label={t("sources.syncOf", { name: source.id })} disabled={source.selected_count === 0} onClick={() => void syncNow()}>{t("sources.syncNow")}</Button>
          )}
          {source.kind !== "file" ? <Button size="sm" aria-label={t("sources.editOf", { name: source.id })} onClick={() => setPanel(panel === "edit" ? null : "edit")}>{t("sources.edit")}</Button> : null}
          <Button size="sm" aria-label={t("sources.deleteOf", { name: source.id })} onClick={onDelete}>{t("sources.delete")}</Button>
        </span>
      </div>
      {error ? <WarningBanner tone="danger">{error}</WarningBanner> : null}
      {panel === "tables" && tables ? (
        <TableChooser sources={sources} id={source.id} tables={tables} copyOnly={source.kind === "sqlserver"} onSaved={() => void onChanged()} />
      ) : null}
      {panel === "edit" ? <EditForm sources={sources} source={source} onDone={() => { setPanel(null); void onChanged(); }} /> : null}
    </li>
  );
}

export function SourcesSection() {
  const { t } = useI18n();
  const { api } = useChat();
  const sources = api.sources;
  const failure = useFailure();
  const { data, failed, reload } = useLoad(useCallback(() => sources.list(), [sources]));
  const [adding, setAdding] = useState(false);
  const [syncing, setSyncing] = useState<Record<string, boolean>>({});
  const [removing, setRemoving] = useState<SourceView | null>(null);
  const [confirm, setConfirm] = useState("");
  const [removeError, setRemoveError] = useState<string | null>(null);

  const running = (data ?? []).some((source) => source.last_sync?.status === "running") || Object.values(syncing).some(Boolean);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => {
      void reload().then(() => setSyncing({}));
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [running, reload]);

  async function remove() {
    if (!removing) return;
    try {
      await sources.remove(removing.id, confirm);
      setRemoving(null);
      setConfirm("");
      setRemoveError(null);
      await reload();
    } catch (cause) {
      setRemoveError(failure(cause));
    }
  }

  return (
    <ListPage section="sources" loading={!data} failed={failed}
      actions={<Button variant="primary" icon="plus" onClick={() => setAdding(!adding)}>{t("sources.add")}</Button>}>
      {adding ? (
        <section className="fc-card" aria-label={t("sources.add")}>
          <div className="fc-card-head"><h2 className="fc-card-title">{t("sources.add")}</h2></div>
          <div className="fc-card-body fc-stack">
            <SourceConnect sources={sources} onConnected={() => void reload()} onChosen={() => void reload()} onSynced={() => { setSyncing({}); void reload(); }} />
            <div><Button onClick={() => setAdding(false)}>{t("sources.done")}</Button></div>
          </div>
        </section>
      ) : null}
      <section className="fc-card">
        {data && data.length ? (
          <ul className="fc-list" aria-label={t("sources.list")}>
            {data.map((source) => (
              <SourceRow key={source.id} sources={sources} source={source} syncing={Boolean(syncing[source.id])}
                onSyncing={(on) => setSyncing((current) => ({ ...current, [source.id]: on }))} onChanged={reload}
                onDelete={() => { setRemoving(source); setConfirm(""); setRemoveError(null); }} />
            ))}
          </ul>
        ) : <p className="fc-muted" style={{ margin: 0, padding: "var(--base-size-16)" }}>{t("sources.empty")}</p>}
      </section>
      <Dialog open={removing !== null} title={t("sources.deleteTitle", { name: removing?.id ?? "" })} tone="danger" onClose={() => setRemoving(null)}
        actions={<>
          <Button onClick={() => setRemoving(null)}>{t("common.cancel")}</Button>
          <Button variant="danger" disabled={confirm !== removing?.id} onClick={() => void remove()}>{t("sources.delete")}</Button>
        </>}>
        <div className="fc-stack">
          <p style={{ margin: 0 }}>{t("sources.deleteText")}</p>
          <TextField label={t("sources.sourceName")} value={confirm} onChange={(event) => setConfirm(event.target.value)} />
          {removeError ? <WarningBanner tone="danger">{removeError}</WarningBanner> : null}
        </div>
      </Dialog>
    </ListPage>
  );
}
