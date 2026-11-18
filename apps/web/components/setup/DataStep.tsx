"use client";

// The setup's Data step (DECISIONS §4, §15) on three screens. The first chooses a file or a database: a file is
// uploaded at once, its guessed column types can be checked and changed, and "Load the file" loads it. The
// database screen asks for the five connection fields, with the source name, schema, TLS and CA certificate under
// "Advanced"; "Check the connection" only tests and counts the tables, and "Choose tables" saves the source. The
// last screen chooses the tables, keeping the mode fitcher proposes for each; saving starts preparing them.

import { useRef, useState, type DragEvent, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { StepHead } from "@/components/setup/SetupShell";
import { formatBytes, FILE_TYPES, tableNameOf } from "@/components/sources/format";
import {
  connectionBody, DEFAULT_PORTS, DEFAULT_SCHEMAS, EMPTY_CONNECTION, KINDS, TLS, useFailure, type ConnectionValues,
} from "@/components/sources/connection";
import { Segmented } from "@/components/ui/controls";
import type { FitcherApi } from "@/lib/api/client";
import type { FileUploadView, SourceDetail, TableView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

/** The tables chosen in this step, kept for the Start step. */
export type Chosen = { source: SourceDetail; tables: TableView[] };

type Props = {
  sources: FitcherApi["sources"];
  meta: ReactNode;
  disabled?: boolean;
  onBack?: () => void;
  onSkip?: () => void;
  /** The tables are saved and their preparation has started. */
  onChosen: (chosen: Chosen) => void;
  /** The screen to open on; the console's "Add a source" opens the database form directly. */
  initial?: "choose" | "database";
};

export function DataStep(props: Props) {
  const [screen, setScreen] = useState<"choose" | "database">(props.initial ?? "choose");
  const [source, setSource] = useState<SourceDetail | null>(null);
  if (source) return <TablesScreen {...props} source={source} onBack={() => setSource(null)} />;
  if (screen === "database") {
    return <DatabaseScreen {...props} onBack={props.initial === "database" ? props.onBack : () => setScreen("choose")} onSaved={setSource} />;
  }
  return <ChooseScreen {...props} onDatabase={() => setScreen("database")} onLoaded={setSource} />;
}

function Links({ onBack, onSkip, disabled, extra }: { onBack?: () => void; onSkip?: () => void; disabled?: boolean; extra?: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="ob-links">
      {onBack ? <button type="button" className="fc-textlink" disabled={disabled} onClick={onBack}><Icon name="arrowLeft" />{t("onboarding.back")}</button> : null}
      {extra}
      {onSkip ? <button type="button" className="fc-textlink" disabled={disabled} onClick={onSkip}>{t("onboarding.later")}</button> : null}
    </div>
  );
}

function Spinner() {
  return <span className="fc-spin fc-spinning" aria-hidden="true" />;
}

// ---- Choose a file or a database -------------------------------------------------------------------------

// The column types a file can be loaded as, with or without empty values (components/sources/format.ts).
const TYPE_KEYS: Record<string, string> = {
  String: "string", Int64: "int", UInt64: "uint", Float64: "float", "Decimal(18, 2)": "decimal", Bool: "bool", Date: "date", "DateTime64(6)": "datetime",
};
const bare = (type: string) => /^Nullable\((.*)\)$/.exec(type)?.[1] ?? type;
const isNullable = (type: string) => type.startsWith("Nullable(");

function ChooseScreen({ sources, meta, disabled, onBack, onSkip, onDatabase, onLoaded }: Props & {
  onDatabase: () => void; onLoaded: (source: SourceDetail) => void;
}) {
  const { t } = useI18n();
  const failure = useFailure();
  const input = useRef<HTMLInputElement>(null);
  const [upload, setUpload] = useState<FileUploadView | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [failed, setFailed] = useState<{ name: string; reason: string } | null>(null);
  const [types, setTypes] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [columns, setColumns] = useState(false);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function choose(file: File | undefined) {
    if (!file) return;
    setUploading(file.name);
    setFailed(null);
    setError(null);
    try {
      const uploaded = await sources.upload(file);
      setUpload(uploaded);
      setTypes(Object.fromEntries(uploaded.columns.map((column) => [column.name, column.type])));
      setName(tableNameOf(uploaded.file_name));
    } catch (cause) {
      setUpload(null);
      setFailed({ name: file.name, reason: failure(cause) });
    } finally {
      setUploading(null);
    }
  }

  async function load() {
    if (!upload) return;
    setBusy(true);
    setError(null);
    try {
      onLoaded(await sources.loadFile(upload.id, {
        name: name.trim(), columns: upload.columns.map((column) => ({ name: column.name, type: types[column.name] })),
      }));
    } catch (cause) {
      setError(failure(cause));
    } finally {
      setBusy(false);
    }
  }

  const dropped = (event: DragEvent) => {
    event.preventDefault();
    setDrag(false);
    void choose(event.dataTransfer.files?.[0]);
  };
  const setType = (column: string, type: string, nullable: boolean) => setTypes({ ...types, [column]: nullable ? `Nullable(${type})` : type });

  let file: ReactNode;
  if (uploading) {
    file = (
      <div className="filerow" role="status">
        <Icon name="fileText" />
        <div className="filerow-body"><div className="filerow-name">{uploading}</div><div className="fc-muted"><Spinner /> {t("onboarding.uploading")}</div></div>
      </div>
    );
  } else if (upload) {
    file = (
      <>
        <div className="filerow">
          <Icon name="fileText" />
          <div className="filerow-body">
            <div className="filerow-name">{upload.file_name}</div>
            <div className="fc-muted">
              {t("onboarding.fileFacts", { size: formatBytes(upload.size_bytes), columns: upload.columns.length })}
              {upload.format === "xlsx" ? ` · ${t("onboarding.firstSheet")}` : ""}
            </div>
          </div>
          <button type="button" className="fc-btn fc-btn-ghost fc-btn-icon fc-btn-sm" aria-label={t("onboarding.removeFile", { name: upload.file_name })}
            disabled={busy} onClick={() => { setUpload(null); setColumns(false); }}><Icon name="x" /></button>
        </div>
        <button type="button" className="fc-textlink" aria-expanded={columns} style={{ alignSelf: "flex-start" }} onClick={() => setColumns(!columns)}>
          <Icon name={columns ? "chevronUp" : "chevronDown"} />
          {columns ? t("onboarding.hideColumns") : t("onboarding.showColumns", { n: upload.columns.length })}
        </button>
        {columns ? (
          <>
            <div className="fc-field">
              <label className="fc-field-label" htmlFor="file-source-name">{t("onboarding.sourceName")}</label>
              <input id="file-source-name" className="fc-input" value={name} spellCheck={false} aria-describedby="file-source-name-help"
                onChange={(event) => setName(event.target.value)} />
              <span className="fc-field-help" id="file-source-name-help">{t("onboarding.sourceNameHelp")}</span>
            </div>
            <div className="box cols-box">
              <table className="tbl">
                <caption className="fc-sr">{t("onboarding.columnsCaption", { name: upload.file_name })}</caption>
                <thead>
                  <tr><th>{t("onboarding.column")}</th><th>{t("onboarding.type")}</th><th>{t("onboarding.nullable")}</th><th>{t("onboarding.firstValues")}</th></tr>
                </thead>
                <tbody>
                  {upload.columns.map((column, index) => {
                    const current = types[column.name];
                    const base = bare(current);
                    const options = TYPE_KEYS[base] ? FILE_TYPES : [base, ...FILE_TYPES];
                    return (
                      <tr key={column.name}>
                        <td><span className="fc-mono">{column.name}</span></td>
                        <td>
                          <div className="sel">
                            <select className="fc-input fc-input-sm" aria-label={t("onboarding.typeOf", { name: column.name })} value={base}
                              onChange={(event) => setType(column.name, event.target.value, isNullable(current))}>
                              {options.map((type) => <option key={type} value={type}>{TYPE_KEYS[type] ? t(`onboarding.type_${TYPE_KEYS[type]}`) : type}</option>)}
                            </select>
                            <Icon name="chevronDown" />
                          </div>
                        </td>
                        <td>
                          <input type="checkbox" aria-label={t("onboarding.nullableOf", { name: column.name })} checked={isNullable(current)}
                            onChange={(event) => setType(column.name, base, event.target.checked)} />
                        </td>
                        <td><span className="fc-muted fc-mono">{upload.sample.slice(0, 3).map((row) => row[index] ?? "").filter(Boolean).join(", ")}</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </>
    );
  } else {
    file = (
      <>
        {failed ? (
          <div className="filerow" data-state="error">
            <Icon name="fileText" />
            <div className="filerow-body">
              <div className="filerow-name">{failed.name}</div>
              <div className="fc-field-error" role="alert"><Icon name="alert" />{failed.reason}</div>
            </div>
            <button type="button" className="fc-btn fc-btn-ghost fc-btn-icon fc-btn-sm" aria-label={t("onboarding.removeFile", { name: failed.name })}
              onClick={() => setFailed(null)}><Icon name="x" /></button>
          </div>
        ) : null}
        <div className="drop" data-state={drag ? "drag" : undefined} onDragOver={(event) => { event.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)} onDrop={dropped}>
          <div className="drop-icon"><Icon name="upload" size="lg" /></div>
          <div>{t("onboarding.dropHere")}</div>
          <div className="fc-muted">{t("onboarding.fileDesc")}</div>
          <button type="button" className="fc-btn fc-btn-sm" disabled={disabled} onClick={() => input.current?.click()}>{t("onboarding.chooseFile")}</button>
          <input ref={input} type="file" accept=".csv,.xlsx,.parquet" aria-label={t("onboarding.chooseFile")}
            onChange={(event) => { void choose(event.target.files?.[0]); event.target.value = ""; }} />
        </div>
        <p className="fc-field-help" style={{ margin: 0 }}>{t("onboarding.excelNote")}</p>
      </>
    );
  }

  return (
    <>
      <StepHead icon={<Icon name="database" size="xl" />} title={t("onboarding.dataTitle")}>{t("onboarding.dataSub")}</StepHead>
      <div className="opt-list" role="radiogroup" aria-label={t("onboarding.sourceKind")}>
        <div className="opt-group">
          <button type="button" className="opt" role="radio" aria-checked="true">
            <span className="opt-icon"><Icon name="upload" /></span>
            <span className="opt-body"><span className="opt-title">{t("onboarding.fileCard")}</span><span className="opt-desc">{t("onboarding.fileDesc")}</span></span>
            <span className="opt-radio"><Icon name="check" /></span>
          </button>
          <div className="opt-more">{file}</div>
        </div>
        <button type="button" className="opt" role="radio" aria-checked="false" disabled={disabled || busy} onClick={onDatabase}>
          <span className="opt-icon"><Icon name="database" /></span>
          <span className="opt-body"><span className="opt-title">{t("onboarding.dbCard")}</span><span className="opt-desc">{t("onboarding.dbDesc")}</span></span>
          <span className="opt-radio" />
        </button>
      </div>
      {error ? <span className="fc-field-error" role="alert"><Icon name="alert" />{error}</span> : null}
      <div className="ob-foot">
        <button type="button" className="fc-btn fc-btn-primary fc-btn-xl fc-btn-block" aria-busy={busy || undefined}
          disabled={disabled || busy || !upload || !name.trim()} aria-describedby={upload ? undefined : "data-why"} onClick={() => void load()}>
          {busy ? <Spinner /> : null}{busy ? t("onboarding.loadingFile") : t("onboarding.loadFile")}
        </button>
        {upload ? null : <p className="ob-meta" id="data-why">{t("onboarding.pickFileFirst")}</p>}
        <Links onBack={onBack} onSkip={onSkip} disabled={busy} />
        {meta}
      </div>
    </>
  );
}

// ---- Database connection -----------------------------------------------------------------------------------

function DatabaseScreen({ sources, meta, disabled, onBack, onSaved }: Props & { onBack?: () => void; onSaved: (source: SourceDetail) => void }) {
  const { t } = useI18n();
  const failure = useFailure();
  const [values, setValues] = useState<ConnectionValues>(EMPTY_CONNECTION);
  const [named, setNamed] = useState(false);
  const [found, setFound] = useState<number | null>(null);
  const [busy, setBusy] = useState<"test" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const name = named ? values.name : tableNameOf(values.database || "source");

  // A tested connection is no longer the one on the form once a field changes.
  const set = (patch: Partial<ConnectionValues>) => { setValues({ ...values, ...patch }); setFound(null); };
  const ready = values.host.trim() && values.database.trim() && values.user.trim() && values.password && name.trim();

  async function test() {
    setBusy("test");
    setError(null);
    try {
      setFound((await sources.test(connectionBody(values))).tables.length);
    } catch (cause) {
      setFound(null);
      setError(failure(cause));
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    setBusy("save");
    setError(null);
    try {
      onSaved(await sources.create({ ...connectionBody(values), name: name.trim() }));
    } catch (cause) {
      setError(failure(cause));
      setBusy(null);
    }
  }

  const off = disabled || busy !== null;
  return (
    <form style={{ display: "contents" }} onSubmit={(event) => { event.preventDefault(); if (found === null) void test(); else void save(); }}>
      <StepHead icon={<Icon name="database" size="xl" />} title={t("onboarding.dbTitle")}>{t("onboarding.dbSub")}</StepHead>
      <DatabaseFields values={values} onChange={set} name={name} onName={(next) => { setNamed(true); set({ name: next }); }}
        disabled={off} invalid={Boolean(error)} />
      {error ? <div className="fc-field-error" id="db-error" role="alert"><Icon name="alert" />{error}</div> : null}
      {found !== null ? (
        <div className="fc-banner fc-banner-success" role="status"><Icon name="check" /><div>{t("onboarding.dbFound", { count: found })}</div></div>
      ) : null}
      <div className="ob-foot">
        {found === null ? (
          <button type="submit" className="fc-btn fc-btn-primary fc-btn-xl fc-btn-block" aria-busy={busy === "test" || undefined} disabled={off || !ready}>
            {busy === "test" ? <Spinner /> : null}{busy === "test" ? t("onboarding.testingConnection") : t("onboarding.testConnection")}
          </button>
        ) : (
          <>
            <button type="submit" className="fc-btn fc-btn-primary fc-btn-xl fc-btn-block" aria-busy={busy === "save" || undefined} disabled={off}>
              {busy === "save" ? <Spinner /> : null}{busy === "save" ? t("onboarding.saving") : t("onboarding.chooseTables")}
            </button>
            <p className="ob-meta">{t("onboarding.savesOnChoose")}</p>
          </>
        )}
        <Links onBack={onBack} disabled={busy !== null}
          extra={found !== null ? <button type="button" className="fc-textlink" disabled={off} onClick={() => void test()}><Icon name="refresh" />{t("onboarding.testAgain")}</button> : null} />
        {meta}
      </div>
    </form>
  );
}

/**
 * The fields of a database connection: the kind, host and port, database, user and password, then the source
 * name, schema, TLS and CA certificate under "Advanced". Editing a saved source keeps its kind and name, and an
 * empty password or certificate keeps the stored one.
 */
export function DatabaseFields({ values, onChange, name, onName, disabled, invalid, editing = false }: {
  values: ConnectionValues;
  onChange: (patch: Partial<ConnectionValues>) => void;
  name: string;
  onName?: (name: string) => void;
  disabled?: boolean;
  /** The last check failed; the fields point at the error line ``db-error``. */
  invalid?: boolean;
  editing?: boolean;
}) {
  const { t } = useI18n();
  const [advanced, setAdvanced] = useState(editing);
  const sqlserver = values.kind === "sqlserver";
  const field = (id: keyof ConnectionValues, label: string, extra: { type?: string; placeholder?: string; inputMode?: "numeric"; help?: string } = {}) => (
    <div className="fc-field">
      <label className="fc-field-label" htmlFor={`db-${id}`}>{label}</label>
      <input id={`db-${id}`} className="fc-input" type={extra.type ?? "text"} value={values[id]} placeholder={extra.placeholder} inputMode={extra.inputMode}
        autoComplete={id === "password" ? "new-password" : "off"} spellCheck={false} disabled={disabled}
        aria-invalid={invalid ? true : undefined}
        aria-describedby={[invalid ? "db-error" : "", extra.help ? `db-${id}-help` : ""].filter(Boolean).join(" ") || undefined}
        onChange={(event) => onChange({ [id]: event.target.value })} />
      {extra.help ? <span className="fc-field-help" id={`db-${id}-help`}>{extra.help}</span> : null}
    </div>
  );
  return (
    <>
      <div className="fc-field" role="group" aria-labelledby="db-kind">
        <span className="fc-field-label" id="db-kind">{t("onboarding.dbKind")}</span>
        <div style={{ alignSelf: "flex-start" }} aria-disabled={editing || undefined} className={editing ? "seg-locked" : undefined}>
          <Segmented label={t("onboarding.dbKind")} value={values.kind}
            onChange={(kind) => { if (!editing) onChange({ kind: kind as ConnectionValues["kind"], tls_mode: kind === "sqlserver" && values.tls_mode === "verify" ? "require" : values.tls_mode }); }}
            options={KINDS.filter((kind) => !editing || kind === values.kind).map((kind) => [kind, t(`sources.kind_${kind}`)])} />
        </div>
        {sqlserver ? <span className="fc-field-help">{t("onboarding.sqlserverCopy")}</span> : null}
      </div>
      <div className="fields-port">
        {field("host", t("onboarding.host"), { placeholder: "host.docker.internal" })}
        {field("port", t("onboarding.port"), { placeholder: DEFAULT_PORTS[values.kind], inputMode: "numeric" })}
      </div>
      {field("database", t("onboarding.database"))}
      <div className="fields-2">
        {field("user", t("onboarding.user"))}
        {field("password", t("onboarding.password"), editing ? { type: "password", placeholder: t("onboarding.keepPassword"), help: t("onboarding.keepPassword") } : { type: "password" })}
      </div>
      <span className="fc-field-help" style={{ marginTop: -8 }}>{t("onboarding.dockerHint")}</span>
      <div className="fc-stack" style={{ gap: 12 }}>
        <button type="button" className="fc-textlink" aria-expanded={advanced} style={{ alignSelf: "flex-start" }} onClick={() => setAdvanced(!advanced)}>
          <Icon name={advanced ? "chevronUp" : "chevronDown"} />{advanced ? t("onboarding.hideAdvanced") : t("onboarding.advanced")}
        </button>
        {advanced ? (
          <>
            <div className="fc-field">
              <label className="fc-field-label" htmlFor="db-source-name">{t("onboarding.sourceName")}</label>
              <input id="db-source-name" className="fc-input" value={name} spellCheck={false} disabled={disabled || editing || !onName}
                aria-describedby="db-source-name-help" onChange={(event) => onName?.(event.target.value)} />
              <span className="fc-field-help" id="db-source-name-help">{editing ? t("onboarding.nameFixed") : t("onboarding.sourceNameHelp")}</span>
            </div>
            {DEFAULT_SCHEMAS[values.kind] ? field("schema_name", t("onboarding.schema"), { placeholder: DEFAULT_SCHEMAS[values.kind] }) : null}
            <div className="fc-field">
              <label className="fc-field-label" htmlFor="db-tls">{t("onboarding.tls")}</label>
              <div className="sel">
                <select id="db-tls" className="fc-input" value={values.tls_mode} disabled={disabled}
                  onChange={(event) => onChange({ tls_mode: event.target.value as ConnectionValues["tls_mode"] })}>
                  {(sqlserver ? TLS.filter((mode) => mode !== "verify") : TLS).map((mode) => <option key={mode} value={mode}>{t(`sources.tls_${mode}`)}</option>)}
                </select>
                <Icon name="chevronDown" />
              </div>
              {sqlserver ? <span className="fc-field-help">{t("onboarding.sqlserverTls")}</span> : null}
            </div>
            {sqlserver ? null : (
              <div className="fc-field">
                <label className="fc-field-label" htmlFor="db-ca">{t("onboarding.caCert")}</label>
                <textarea id="db-ca" className="fc-textarea" placeholder="-----BEGIN CERTIFICATE-----" value={values.ca_certificate} disabled={disabled}
                  aria-describedby="db-ca-help" onChange={(event) => onChange({ ca_certificate: event.target.value })} />
                <span className="fc-field-help" id="db-ca-help">{editing ? `${t("onboarding.caHelp")} ${t("onboarding.keepCa")}` : t("onboarding.caHelp")}</span>
              </div>
            )}
          </>
        ) : null}
      </div>
    </>
  );
}

// ---- Tables ------------------------------------------------------------------------------------------------

// A small source starts with every table chosen; past 20 tables nothing is, and the page says why.
const PRESELECT_AT_MOST = 20;

function TablesScreen({ sources, meta, disabled, source, onBack, onChosen }: Props & { source: SourceDetail; onBack: () => void }) {
  const { t, formatNumber } = useI18n();
  const failure = useFailure();
  const many = source.tables.length > PRESELECT_AT_MOST;
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(source.tables.filter((table) => table.selected || !many).map((table) => table.name)));
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const shown = source.tables.filter((table) => !query.trim() || table.name.toLowerCase().includes(query.trim().toLowerCase()));

  function toggle(name: string, on: boolean) {
    const next = new Set(chosen);
    if (on) next.add(name); else next.delete(name);
    setChosen(next);
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const saved = await sources.changeTables(source.id, {
        tables: source.tables.map((table) => ({
          name: table.name, selected: chosen.has(table.name), mode: table.mode, interval_seconds: table.interval_seconds, cursor_column: table.cursor_column,
        })),
      });
      await sources.sync(source.id);
      onChosen({ source, tables: saved.filter((table) => table.selected) });
    } catch (cause) {
      setError(failure(cause));
      setBusy(false);
    }
  }

  const count = chosen.size;
  return (
    <>
      <StepHead icon={<Icon name="table" size="xl" />} title={t("onboarding.tablesTitle")}>{t("onboarding.tablesSub")}</StepHead>
      {many ? <div className="fc-banner fc-banner-info" role="status"><Icon name="info" /><div>{t("onboarding.manyTables", { count: source.tables.length })}</div></div> : null}
      <div className="box">
        <div className="box-head">
          <div className="fc-input-wrap" style={{ flex: 1 }}>
            <Icon name="search" />
            <input className="fc-input fc-input-sm" placeholder={t("onboarding.searchTables")} aria-label={t("onboarding.searchTables")}
              value={query} onChange={(event) => setQuery(event.target.value)} />
          </div>
          <span className="fc-muted" aria-live="polite" style={{ whiteSpace: "nowrap" }}>{t("onboarding.tableCount", { selected: count, total: source.tables.length })}</span>
        </div>
        <div className="tables-box">
          <table className="tbl">
            <caption className="fc-sr">{t("onboarding.tablesCaption", { name: source.id })}</caption>
            <thead>
              <tr>
                <th><span className="fc-sr">{t("onboarding.choose")}</span></th><th>{t("onboarding.table")}</th>
                <th className="num">{t("onboarding.rows")}</th><th className="num">{t("onboarding.size")}</th><th>{t("onboarding.readMode")}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((table) => {
                const id = `table-${table.name}`;
                return (
                  <tr key={table.name}>
                    <td style={{ width: 40, paddingRight: 0 }}>
                      <input type="checkbox" id={id} checked={chosen.has(table.name)} disabled={busy} onChange={(event) => toggle(table.name, event.target.checked)} />
                    </td>
                    <td>
                      <label htmlFor={id} className="fc-mono">{table.name}</label>
                      {table.kind === "view" ? <> <span className="fc-label">view</span></> : null}
                    </td>
                    <td className="num">{table.rows === null ? <span className="fc-muted">{t("onboarding.unknown")}</span> : formatNumber(table.rows)}</td>
                    <td className="num">{table.size_bytes === null ? <span className="fc-muted">{t("onboarding.unknown")}</span> : formatBytes(table.size_bytes)}</td>
                    <td>
                      <span className="tip-wrap">
                        <button type="button" className="fc-label" aria-describedby={`${id}-why`}>{t(`sources.${table.mode}`)}</button>
                        <span className="tip" role="tooltip" id={`${id}-why`}>
                          {t("onboarding.proposedWhy", { mode: t(`sources.${table.proposed_mode}`), why: t(`sources.why_${table.reason}`) })}
                        </span>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <p className="fc-field-help" style={{ margin: 0, display: "flex", gap: 6, alignItems: "flex-start" }}>
        <Icon name="info" /><span>{t("onboarding.tablesNote")}</span>
      </p>
      {error ? <span className="fc-field-error" role="alert"><Icon name="alert" />{error}</span> : null}
      <div className="ob-foot">
        <button type="button" className="fc-btn fc-btn-primary fc-btn-xl fc-btn-block" aria-busy={busy || undefined} disabled={disabled || busy || count === 0}
          onClick={() => void save()}>
          {busy ? <Spinner /> : null}{count === 1 ? t("onboarding.useTable") : t("onboarding.useTables", { count })}
        </button>
        <Links onBack={onBack} disabled={busy} />
        {meta}
      </div>
    </>
  );
}
