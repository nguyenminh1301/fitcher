"use client";

// Connecting a source (DECISIONS §4, §15), shared by the Sources page and the setup's Data step: the connection
// of a PostgreSQL or MySQL/MariaDB database, which is tested and its tables listed before it is saved, or an
// uploaded CSV, XLSX or Parquet file whose column types are confirmed before the load. The password is sent once
// to the api, which writes it into ClickHouse; this form clears it and never shows it again.

import { useState } from "react";

import { tableNameOf, typeOptions } from "@/components/sources/format";
import { TableChooser, TableList } from "@/components/sources/TableChooser";
import { Button, Tabs, TextField } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import type { FitcherApi } from "@/lib/api/client";
import { SourceError } from "@/lib/api/http/sources";
import type { FileUploadView, SourceConnection, SourceDetail, TableView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

type Kind = SourceConnection["kind"];
type Tls = NonNullable<SourceConnection["tls_mode"]>;
const KINDS: Kind[] = ["postgres", "mysql", "sqlserver"];
const TLS: Tls[] = ["prefer", "require", "verify"];
const DEFAULT_PORTS: Record<Kind, string> = { postgres: "5432", mysql: "3306", sqlserver: "1433" };
const DEFAULT_SCHEMAS: Partial<Record<Kind, string>> = { postgres: "public", sqlserver: "dbo" };

/** One fixed message for a failure: the api's reason when it gave one, else its own message. */
export function useFailure() {
  const { t } = useI18n();
  return (cause: unknown): string => {
    if (cause instanceof SourceError && cause.reason) return t(`sources.reason_${cause.reason}`);
    if (cause instanceof SourceError && cause.marts?.length) return t("sources.inUse", { marts: cause.marts.join(", ") });
    return t("sources.failed", { reason: cause instanceof Error ? cause.message : String(cause) });
  };
}

export type ConnectionValues = {
  kind: Kind; name: string; host: string; port: string; database: string; schema_name: string; user: string;
  password: string; tls_mode: Tls; ca_certificate: string;
};

export const EMPTY_CONNECTION: ConnectionValues = {
  kind: "postgres", name: "", host: "", port: "", database: "", schema_name: "", user: "", password: "", tls_mode: "prefer", ca_certificate: "",
};

/** The request body for a test or a create; an empty port or schema is left out so the api's defaults apply. */
export function connectionBody(values: ConnectionValues): SourceConnection {
  const body: SourceConnection = {
    kind: values.kind, host: values.host.trim(), database: values.database.trim(), user: values.user.trim(),
    password: values.password, tls_mode: values.tls_mode,
  };
  if (values.port) body.port = Number(values.port);
  if (DEFAULT_SCHEMAS[values.kind] && values.schema_name) body.schema_name = values.schema_name.trim();
  if (values.kind !== "sqlserver" && values.ca_certificate.trim()) body.ca_certificate = values.ca_certificate;
  return body;
}

/** The fields of a connection; the same form serves a new source and the edit of a stored one. */
export function ConnectionFields({ values, onChange, disabled, editing }: {
  values: ConnectionValues; onChange: (next: ConnectionValues) => void; disabled?: boolean; editing?: boolean;
}) {
  const { t } = useI18n();
  const set = (patch: Partial<ConnectionValues>) => onChange({ ...values, ...patch });
  const sqlserver = values.kind === "sqlserver";
  // A SQL Server connection requires encryption unless the user asks for it only when offered, and its driver
  // cannot verify the certificate, so that mode is not offered.
  const modes = sqlserver ? TLS.filter((mode) => mode !== "verify") : TLS;
  return (
    <div className="fc-stack" style={{ gap: "var(--base-size-12)" }}>
      {editing ? null : (
        <div className="fc-field">
          <label className="fc-field-label" htmlFor="source-kind">{t("sources.databaseType")}</label>
          <select id="source-kind" className="fc-input" value={values.kind} disabled={disabled}
            onChange={(event) => {
              const kind = event.target.value as Kind;
              set({ kind, tls_mode: kind === "sqlserver" ? "require" : values.tls_mode === "require" ? "prefer" : values.tls_mode });
            }}>
            {KINDS.map((kind) => <option key={kind} value={kind}>{t(`sources.kind_${kind}`)}</option>)}
          </select>
        </div>
      )}
      {editing ? null : <TextField label={t("sources.name")} value={values.name} disabled={disabled} help={t("sources.nameHelp")}
        onChange={(event) => set({ name: event.target.value })} />}
      <TextField label={t("sources.host")} value={values.host} disabled={disabled} help={t("sources.hostHint")}
        onChange={(event) => set({ host: event.target.value })} />
      <TextField label={t("sources.port")} type="number" value={values.port} disabled={disabled}
        placeholder={DEFAULT_PORTS[values.kind]} onChange={(event) => set({ port: event.target.value })} />
      <TextField label={t("sources.database")} value={values.database} disabled={disabled}
        onChange={(event) => set({ database: event.target.value })} />
      {DEFAULT_SCHEMAS[values.kind] ? (
        <TextField label={t("sources.schema")} value={values.schema_name} disabled={disabled} placeholder={DEFAULT_SCHEMAS[values.kind]}
          onChange={(event) => set({ schema_name: event.target.value })} />
      ) : null}
      <TextField label={t("sources.user")} value={values.user} disabled={disabled} autoComplete="off" help={t("sources.readOnlyHint")}
        onChange={(event) => set({ user: event.target.value })} />
      <TextField label={t("sources.password")} type="password" autoComplete="new-password" value={values.password} disabled={disabled}
        help={editing ? t("sources.passwordKeep") : undefined} onChange={(event) => set({ password: event.target.value })} />
      <div className="fc-field">
        <label className="fc-field-label" htmlFor="source-tls">{t("sources.tls")}</label>
        <select id="source-tls" className="fc-input" value={values.tls_mode} disabled={disabled}
          onChange={(event) => set({ tls_mode: event.target.value as Tls })}>
          {modes.map((mode) => <option key={mode} value={mode}>{t(`sources.tls_${mode}`)}</option>)}
        </select>
        {sqlserver ? <span className="fc-field-help">{t("sources.sqlserverTls")}</span> : null}
      </div>
      {sqlserver ? null : (
        <TextField label={t("sources.caCertificate")} multiline rows={3} value={values.ca_certificate} disabled={disabled}
          help={editing ? t("sources.caKeep") : t("sources.caHelp")} onChange={(event) => set({ ca_certificate: event.target.value })} />
      )}
    </div>
  );
}

function DatabaseForm({ sources, onConnected }: { sources: FitcherApi["sources"]; onConnected: (source: SourceDetail) => void }) {
  const { t } = useI18n();
  const failure = useFailure();
  const [values, setValues] = useState<ConnectionValues>(EMPTY_CONNECTION);
  const [tables, setTables] = useState<TableView[] | null>(null);
  const [busy, setBusy] = useState<"test" | "connect" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const edit = (next: ConnectionValues) => {
    setValues(next);
    // A tested connection is no longer the connection on the form once a field changes.
    setTables(null);
  };
  const ready = values.host.trim() && values.database.trim() && values.user.trim() && values.password && values.name.trim();

  async function test() {
    setBusy("test");
    setError(null);
    try {
      setTables((await sources.test(connectionBody(values))).tables);
    } catch (cause) {
      setTables(null);
      setError(failure(cause));
    } finally {
      setBusy(null);
    }
  }

  async function connect() {
    setBusy("connect");
    setError(null);
    try {
      const source = await sources.create({ ...connectionBody(values), name: values.name.trim() });
      setValues(EMPTY_CONNECTION);
      setTables(null);
      onConnected(source);
    } catch (cause) {
      setError(failure(cause));
    } finally {
      setBusy(null);
    }
  }

  return (
    <form className="fc-stack" style={{ gap: "var(--base-size-16)" }} onSubmit={(event) => { event.preventDefault(); void test(); }}>
      <ConnectionFields values={values} onChange={edit} disabled={busy !== null} />
      {error ? <WarningBanner tone="danger">{error}</WarningBanner> : null}
      {tables ? (
        <div className="fc-stack" style={{ gap: "var(--base-size-8)" }}>
          <WarningBanner tone="success">{t("sources.tested", { count: tables.length })}</WarningBanner>
          <TableList tables={tables} copyOnly={values.kind === "sqlserver"} />
        </div>
      ) : null}
      <div className="fc-row" style={{ gap: "var(--base-size-8)" }}>
        <Button type="submit" disabled={busy !== null || !ready}>{busy === "test" ? t("sources.testing") : t("sources.test")}</Button>
        {tables ? (
          <Button variant="primary" disabled={busy !== null} onClick={() => void connect()}>
            {busy === "connect" ? t("sources.connecting") : t("sources.connect")}
          </Button>
        ) : null}
      </div>
    </form>
  );
}

function FileForm({ sources, onConnected }: { sources: FitcherApi["sources"]; onConnected: (source: SourceDetail) => void }) {
  const { t } = useI18n();
  const failure = useFailure();
  const [upload, setUpload] = useState<FileUploadView | null>(null);
  const [types, setTypes] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function choose(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const uploaded = await sources.upload(file);
      setUpload(uploaded);
      setTypes(Object.fromEntries(uploaded.columns.map((column) => [column.name, column.type])));
      setName(tableNameOf(uploaded.file_name));
    } catch (cause) {
      setUpload(null);
      setError(failure(cause));
    } finally {
      setBusy(false);
    }
  }

  async function load() {
    if (!upload) return;
    setBusy(true);
    setError(null);
    try {
      const source = await sources.loadFile(upload.id, {
        name, columns: upload.columns.map((column) => ({ name: column.name, type: types[column.name] })),
      });
      setUpload(null);
      onConnected(source);
    } catch (cause) {
      setError(failure(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fc-stack" style={{ gap: "var(--base-size-16)" }}>
      <div className="fc-field">
        <label className="fc-field-label" htmlFor="source-file">{t("sources.fileLabel")}</label>
        <input id="source-file" className="fc-input" type="file" accept=".csv,.xlsx,.parquet" disabled={busy}
          onChange={(event) => void choose(event.target.files?.[0])} />
        <span className="fc-field-help">{t("sources.fileHelp")}</span>
      </div>
      {error ? <WarningBanner tone="danger">{error}</WarningBanner> : null}
      {upload ? (
        <div className="fc-stack" style={{ gap: "var(--base-size-12)" }}>
          <p style={{ margin: 0 }}>{t("sources.typesInferred", { name: upload.file_name })}</p>
          <div className="fc-table-scroll">
            <table className="fc-table" aria-label={t("sources.columns")}>
              <thead>
                <tr><th scope="col">{t("sources.column")}</th><th scope="col">{t("sources.type")}</th><th scope="col">{t("sources.sample")}</th></tr>
              </thead>
              <tbody>
                {upload.columns.map((column, index) => (
                  <tr key={column.name}>
                    <td className="fc-mono">{column.name}</td>
                    <td>
                      <select className="fc-input" aria-label={t("sources.typeOf", { name: column.name })} value={types[column.name]}
                        onChange={(event) => setTypes({ ...types, [column.name]: event.target.value })}>
                        {typeOptions(column.type).map((type) => <option key={type} value={type}>{type}</option>)}
                      </select>
                    </td>
                    <td className="fc-muted">{upload.sample.map((row) => row[index] ?? "").join(" · ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <TextField label={t("sources.name")} value={name} help={t("sources.nameHelp")} onChange={(event) => setName(event.target.value)} />
          <div><Button variant="primary" disabled={busy || !name} onClick={() => void load()}>{t("sources.loadFile")}</Button></div>
        </div>
      ) : null}
    </div>
  );
}

/** Connect a database or upload a file; a connected source then shows its tables to choose from. */
export function SourceConnect({ sources, onConnected, onChosen, onSynced }: {
  sources: FitcherApi["sources"];
  /** A source was saved; the page reloads its list. */
  onConnected?: (source: SourceDetail) => void;
  /** The table selection was saved. */
  onChosen?: (tables: TableView[]) => void;
  onSynced?: () => void;
}) {
  const { t } = useI18n();
  const [tab, setTab] = useState<"database" | "file">("database");
  const [connected, setConnected] = useState<SourceDetail | null>(null);

  if (connected) {
    return (
      <div className="fc-stack" style={{ gap: "var(--base-size-12)" }}>
        <WarningBanner tone="success">{t("sources.connected", { name: connected.id })}</WarningBanner>
        <p className="fc-muted" style={{ margin: 0 }}>{t("sources.chooseHint")}</p>
        <TableChooser sources={sources} id={connected.id} tables={connected.tables} copyOnly={connected.kind === "sqlserver"}
          onSaved={onChosen} onSynced={onSynced} />
      </div>
    );
  }
  const done = (source: SourceDetail) => {
    setConnected(source);
    onConnected?.(source);
  };
  return (
    <div className="fc-stack" style={{ gap: "var(--base-size-16)" }}>
      <Tabs label={t("sources.addKind")} value={tab} onChange={(id) => setTab(id as "database" | "file")}
        tabs={[{ id: "database", label: t("sources.tabDatabase") }, { id: "file", label: t("sources.tabFile") }]} />
      {tab === "database" ? <DatabaseForm sources={sources} onConnected={done} /> : <FileForm sources={sources} onConnected={done} />}
    </div>
  );
}
