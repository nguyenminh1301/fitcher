"use client";

// Review (DECISIONS §11, §15): pack items drafted from documents and data profiles, grouped by file,
// and examples proposed from feedback. A metric is test-run before approval; a proposal is approved
// only after its masked values are replaced and its SQL has been test-run. A reviewer may also confirm the
// proposal's spec, which then answers the same question without resolving its terms again.

import { useCallback, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { DataTable } from "@/components/chat/DataTable";
import { highlight, SqlView } from "@/components/chat/SqlView";
import { useConsole } from "@/components/console/ConsoleLayout";
import { DetailPage } from "@/components/console/DetailPage";
import { Empty, Meter, StatusLabel } from "@/components/console/kit";
import { ListPage } from "@/components/console/ListPage";
import { Checkbox, Segmented } from "@/components/ui/controls";
import { Skeleton } from "@/components/ui/feedback";
import type { ReviewItem } from "@/lib/contracts";
import { useChat } from "@/lib/chat/ChatContext";
import { parseSpec, specFields, type SpecFields } from "@/lib/console/reviewedSpec";
import { useLoad } from "@/lib/console/useLoad";
import type { Result } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";
import { langOf } from "@/lib/text";

const MASK = /\[MASKED_[A-Z0-9_]+\]/g;

function useReviewItems() {
  const { api } = useChat();
  return useLoad(useCallback(() => api.review.items(), [api]));
}

// What a pack item is follows from the pack file that holds it (metrics.yaml, glossary.yaml and so on).
const KINDS = ["metrics", "glossary", "policies", "datasets", "relationships", "examples"];
const KIND_KEY = (item: ReviewItem) => {
  const stem = item.file.replace(/^.*\//, "").replace(/\.ya?ml$/, "");
  return KINDS.includes(stem) ? `reviewPage.kind_${stem}` : "reviewPage.kind_other";
};

export function ReviewSection() {
  const { t } = useI18n();
  const { navigate } = useConsole();
  const { data, failed } = useReviewItems();
  const [tab, setTab] = useState<"items" | "proposals">("items");
  const [filter, setFilter] = useState("all");
  const items = (data ?? []).filter((item) => item.kind === "item");
  const proposals = (data ?? []).filter((item) => item.kind === "proposal" && item.status === "draft");
  const shown = items.filter((item) => filter === "all" || item.status === filter);
  const files = [...new Set(shown.map((item) => item.file))];
  const open = (item: ReviewItem) => navigate(`/console/review/${encodeURIComponent(item.id)}`);
  const status = (item: ReviewItem) => item.reviewed === false
    ? <StatusLabel status="unreviewed">{t("ui.unreviewed")}</StatusLabel>
    : <StatusLabel status={item.status}>{t(`ui.${item.status}`)}</StatusLabel>;

  return (
    <ListPage section="review" loading={!data} failed={failed}>
      <div className="tabs" role="tablist" aria-label={t("ui.nav_review")}>
        {([["items", t("ui.items"), items.length], ["proposals", t("ui.proposals"), proposals.length]] as const).map(([id, label, count]) => (
          <button key={id} type="button" role="tab" className="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
            {label} <span className="fc-count">{count}</span>
          </button>
        ))}
      </div>
      {tab === "items" ? (
        <>
          <div className="toolbar">
            <Segmented label={t("reviewPage.filter")} value={filter} onChange={setFilter}
              options={(["all", "draft", "approved"] as const).map((value) => [value, t(`ui.${value}`)])} />
          </div>
          {files.length ? files.map((file) => (
            <section key={file} className="box" aria-label={file}>
              <div className="box-head"><h2 className="box-title file-title"><Icon name="fileText" /><span className="fc-mono">{file}</span></h2></div>
              <div className="card-table">
                <table className="tbl tbl-cards tbl-review">
                  {/* Fixed column widths, so the tables of the files stacked on this page line up. */}
                  <colgroup><col /><col className="col-kind" /><col className="col-origin" /><col className="col-confidence" /><col className="col-status" /></colgroup>
                  <thead><tr><th>{t("ui.name")}</th><th>{t("reviewPage.kind")}</th><th>{t("ui.origin")}</th><th>{t("ui.confidence")}</th><th>{t("ui.status")}</th></tr></thead>
                  <tbody>
                    {shown.filter((item) => item.file === file).map((item) => (
                      <tr key={item.id} aria-label={item.name}>
                        <td><button type="button" className="src-link" onClick={() => open(item)}>{item.name}</button>
                          <div className="fc-muted row-sub" lang={langOf(item.body)}>{item.body}</div></td>
                        <td data-label={t("reviewPage.kind")}><StatusLabel tone={null}>{t(KIND_KEY(item))}</StatusLabel></td>
                        <td data-label={t("ui.origin")}><span className="fc-muted">{item.evidence?.source ?? "—"}</span></td>
                        <td data-label={t("ui.confidence")}><Meter value={item.confidence} /></td>
                        <td data-label={t("ui.status")}>{status(item)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )) : <div className="box"><Empty title={t("ui.noItems")} text={t("ui.noItemsText")} /></div>}
        </>
      ) : (
        <>
          <div className="fc-banner fc-banner-info" role="status"><Icon name="info" /><div>{t("ui.proposalsNote")}</div></div>
          <section className="box" aria-labelledby="proposals-title">
            <div className="box-head"><h2 id="proposals-title" className="box-title">{t("ui.proposals")}</h2></div>
            {proposals.length ? (
              <div className="card-table">
                <table className="tbl tbl-cards">
                  <thead><tr><th>{t("ui.question")}</th><th>{t("ui.origin")}</th><th>{t("ui.status")}</th></tr></thead>
                  <tbody>
                    {proposals.map((item) => (
                      <tr key={item.id}>
                        <td><button type="button" className="src-link plain" lang={langOf(item.body)} onClick={() => open(item)}>{item.body}</button></td>
                        <td data-label={t("ui.origin")}><span className="fc-muted">{item.evidence?.source ?? "—"}</span></td>
                        <td data-label={t("ui.status")}><StatusLabel tone={null}>{t("reviewPage.waiting")}</StatusLabel></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <Empty title={t("ui.noItems")} />}
          </section>
        </>
      )}
    </ListPage>
  );
}

type Run = { state: "idle" | "running" | "done"; result?: Result };

/** The Test run box: what a metric's formula or a proposal's SQL returns on the data. */
function TestBox({ run, runnable, emptyText, action }: { run: Run; runnable: boolean; emptyText: string; action?: React.ReactNode }) {
  const { t } = useI18n();
  let body;
  if (!runnable) body = <p className="fc-muted box-pad">{t("ui.noTestText")}</p>;
  else if (run.state === "running") body = <div className="box-pad"><Skeleton variant="table" rows={2} /></div>;
  else if (run.state === "done" && run.result) body = <div className="box-pad"><DataTable result={run.result} title={t("ui.testOk", { n: run.result.row_count })} /></div>;
  else body = <p className="fc-muted box-pad">{emptyText}</p>;
  return (
    <section className="box" aria-labelledby="test-title">
      <div className="box-head"><h2 id="test-title" className="box-title">{t("ui.testPanel")}</h2>{action ?? null}</div>
      {body}
    </section>
  );
}

function RunButton({ run, disabled, onRun }: { run: Run; disabled?: boolean; onRun: () => void }) {
  const { t } = useI18n();
  return (
    <button type="button" className="fc-btn fc-btn-sm" disabled={disabled || run.state === "running"} onClick={onRun}>
      {run.state === "running" ? <span className="fc-spin fc-spinning" aria-hidden="true" /> : <Icon name="play" />}
      {run.state === "running" ? t("ui.running") : t("ui.testRun")}
    </button>
  );
}

export function ReviewDetail({ id }: { id: string }) {
  const { data, reload } = useReviewItems();
  const item = data?.find((candidate) => candidate.id === id);
  if (item?.kind === "proposal") return <ProposalDetail key={item.id} item={item} reload={reload} />;
  return <ItemDetail key={item?.id ?? "missing"} item={item} loading={!data} reload={reload} />;
}

function ItemDetail({ item, loading, reload }: { item?: ReviewItem; loading: boolean; reload: () => Promise<void> }) {
  const { t } = useI18n();
  const { api } = useChat();
  const { navigate, toast } = useConsole();
  const [editing, setEditing] = useState(false);
  const [body, setBody] = useState(item?.body ?? "");
  const [formula, setFormula] = useState(item?.formula ?? "");
  const [run, setRun] = useState<Run>({ state: "idle" });
  const back = () => navigate("/console/review");

  async function test(target: ReviewItem) {
    setRun({ state: "running" });
    const tested = await api.review.testRun(target.id);
    setRun({ state: "done", result: tested.test_result ?? undefined });
  }

  const evidence = item?.evidence;
  // A metric is test-run before it is approved; terms and policies are checked against their evidence.
  const needsRun = Boolean(item?.formula) && run.state !== "done";
  const canApprove = item ? item.status !== "approved" || item.reviewed === false : false;
  return (
    <DetailPage feature="review" title={item?.name} mono backLabel={t("ui.nav_review")} onBack={back} loading={loading} missing={!item}
      labels={item ? (
        <>
          <StatusLabel tone={null}>{t(KIND_KEY(item))}</StatusLabel>
          {item.reviewed === false ? <StatusLabel status="unreviewed">{t("ui.unreviewed")}</StatusLabel> : <StatusLabel status={item.status}>{t(`ui.${item.status}`)}</StatusLabel>}
        </>
      ) : null}
      actions={item ? (
        <>
          <button type="button" className="fc-btn fc-btn-ghost" aria-label={`${t("ui.del")} ${item.name}`} onClick={async () => {
            await api.review.remove(item.id);
            toast(t("ui.deletedName", { name: item.name }));
            back();
          }}><Icon name="trash" />{t("ui.del")}</button>
          {canApprove ? (
            <>
              {/* An item an instant pack approved without a person is confirmed with the same action (DECISIONS §5). */}
              <button type="button" className="fc-btn fc-btn-primary" disabled={needsRun || editing} aria-describedby={needsRun ? "approve-why" : undefined} onClick={async () => {
                await api.review.approve(item.id);
                toast(t("ui.approvedName", { name: item.name }));
                await reload();
              }}><Icon name="check" />{item.reviewed === false ? t("ui.confirm") : t("ui.approve")}</button>
              {needsRun ? <span className="fc-field-help" id="approve-why">{t("ui.testFirst")}</span> : null}
            </>
          ) : null}
        </>
      ) : null}
    >
      {item ? (
        <div className="split">
          <div className="split-main">
            <section className="box" aria-labelledby="definition-title">
              <div className="box-head">
                <h2 id="definition-title" className="box-title">{item.formula != null ? t("reviewPage.definitionFormula") : t("ui.body")}</h2>
                {editing ? (
                  <div className="toolbar">
                    <button type="button" className="fc-btn fc-btn-sm" onClick={() => { setBody(item.body); setFormula(item.formula ?? ""); setEditing(false); }}>{t("ui.cancel")}</button>
                    <button type="button" className="fc-btn fc-btn-primary fc-btn-sm" onClick={async () => {
                      await api.review.update(item.id, item.formula == null ? { body } : { body, formula });
                      setEditing(false);
                      setRun({ state: "idle" });
                      await reload();
                    }}>{t("ui.save")}</button>
                  </div>
                ) : <button type="button" className="fc-btn fc-btn-sm" onClick={() => setEditing(true)}><Icon name="pencil" />{t("ui.edit")}</button>}
              </div>
              <div className="box-body">
                {editing ? (
                  <>
                    <textarea className="fc-textarea" aria-label={t("ui.body")} value={body} style={{ fontFamily: "var(--font-sans)" }} onChange={(event) => setBody(event.target.value)} />
                    {item.formula != null ? <textarea className="fc-textarea" aria-label={t("ui.formula")} spellCheck={false} value={formula} onChange={(event) => setFormula(event.target.value)} /> : null}
                  </>
                ) : (
                  <>
                    <p style={{ margin: 0 }} lang={langOf(item.body)}>{item.body}</p>
                    {item.formula != null ? <pre className="code" tabIndex={0} aria-label={t("ui.formula")}><code>{highlight(item.formula ?? "")}</code></pre> : null}
                  </>
                )}
              </div>
            </section>
            <section className="box" aria-labelledby="evidence-title">
              <div className="box-head"><h2 id="evidence-title" className="box-title">{t("ui.evidence")}</h2><Meter value={item.confidence} /></div>
              {evidence ? (
                <ul className="ev-list">
                  <li>
                    <div className="ev-src">
                      <Icon name="fileText" /><span className="fc-mono">{evidence.source}</span>
                      {evidence.deleted ? <StatusLabel tone="attention">{t("ui.deletedSource")}</StatusLabel> : null}
                    </div>
                    {evidence.quote ? <blockquote lang={langOf(evidence.quote)}>&ldquo;{evidence.quote}&rdquo;</blockquote> : null}
                  </li>
                </ul>
              ) : <p className="fc-muted box-pad">{t("reviewPage.noEvidence")}</p>}
            </section>
          </div>
          <div className="split-side">
            <TestBox run={run} runnable={!!item.formula} emptyText={t("ui.testEmpty")}
              action={item.formula ? <RunButton run={run} disabled={editing} onRun={() => void test(item)} /> : null} />
          </div>
        </div>
      ) : null}
    </DetailPage>
  );
}

function ProposalDetail({ item, reload }: { item: ReviewItem; reload: () => Promise<void> }) {
  const { t } = useI18n();
  const { api } = useChat();
  const { navigate, toast } = useConsole();
  const [question, setQuestion] = useState(item.body);
  const [formula, setFormula] = useState(item.formula ?? "");
  const [values, setValues] = useState<Record<string, string>>({});
  const [useSpec, setUseSpec] = useState(item.spec_reviewed ?? false);
  const [fields, setFields] = useState<SpecFields>(specFields(item.spec));
  const [run, setRun] = useState<Run>({ state: "idle" });
  const masked = (text: string) => [...text.matchAll(MASK)].map((match) => match[0]);
  const tokens = [...new Set([...masked(question), ...masked(formula), ...(useSpec ? masked(fields.filters) : [])])];
  const filled = tokens.every((token) => values[token]?.trim());
  const fill = (text: string, quote: boolean) => tokens.reduce((out, token) => {
    const value = values[token]?.trim();
    return value ? out.split(token).join(quote ? value.replace(/'/g, "''") : value) : out;
  }, text);
  const body = fill(question, false);
  const sql = fill(formula, true);
  const parsed = parseSpec({ ...fields, filters: fill(fields.filters, false) });
  const specError = useSpec && "error" in parsed ? parsed.error : null;
  const specPatch = useSpec && "spec" in parsed ? { spec: parsed.spec } : item.spec_reviewed ? { spec_reviewed: false } : {};
  // Any edit invalidates the last test-run: approval needs a test-run of the text that will be saved.
  const edit = (apply: () => void) => { apply(); setRun({ state: "idle" }); };
  const back = () => navigate("/console/review");
  const why = !filled ? t("ui.replaceFirst") : run.state !== "done" ? t("ui.testFirst") : null;
  const field = (name: keyof SpecFields, label: string, extra: { multiline?: boolean; numeric?: boolean; help?: string; error?: string | null } = {}) => {
    const id = `spec-${name}`;
    const described = [extra.error ? `${id}-error` : "", extra.help ? `${id}-help` : ""].filter(Boolean).join(" ") || undefined;
    const props = {
      id, value: fields[name], spellCheck: false, "aria-invalid": extra.error ? true : undefined, "aria-describedby": described,
      onChange: (event: { target: { value: string } }) => edit(() => setFields({ ...fields, [name]: event.target.value })),
    };
    return (
      <div className="fc-field">
        <label className="fc-field-label" htmlFor={id}>{label}</label>
        {extra.multiline ? <textarea className="fc-textarea" {...props} /> : <input className="fc-input" inputMode={extra.numeric ? "numeric" : undefined} {...props} />}
        {extra.error ? <span className="fc-field-error" id={`${id}-error`} role="alert"><Icon name="alert" />{extra.error}</span> : null}
        {extra.help ? <span className="fc-field-help" id={`${id}-help`}>{extra.help}</span> : null}
      </div>
    );
  };

  return (
    <DetailPage feature="review" title={body} titleLang={langOf(body)} backLabel={t("ui.proposals")} onBack={back} loading={false}
      description={item.evidence?.source ? t("reviewPage.fromRun", { source: item.evidence.source }) : null}
      actions={
        <>
          <button type="button" className="fc-btn fc-btn-ghost" aria-label={t("ui.del")} onClick={async () => {
            await api.review.remove(item.id);
            toast(t("ui.deletedName", { name: item.name }));
            back();
          }}><Icon name="trash" />{t("ui.del")}</button>
          <button type="button" className="fc-btn fc-btn-primary" disabled={why !== null} aria-describedby={why ? "approve-why" : undefined} onClick={async () => {
            try {
              await api.review.approve(item.id);
            } catch (refused) {
              // The api checks the spec's pack items and filter values on approval.
              toast(refused instanceof Error ? refused.message : String(refused));
              return;
            }
            toast(t("ui.approvedName", { name: body }));
            await reload();
            back();
          }}><Icon name="check" />{t("ui.approve")}</button>
          {why ? <span className="fc-field-help" id="approve-why">{why}</span> : null}
        </>
      }
    >
      <div className="split">
        <div className="split-main">
          <section className="box" aria-labelledby="question-title">
            <div className="box-head"><h2 id="question-title" className="box-title">{t("ui.question")}</h2></div>
            <div className="box-body">
              <textarea className="fc-textarea" aria-label={t("ui.question")} lang={langOf(question)} value={question} style={{ fontFamily: "var(--font-sans)" }}
                onChange={(event) => edit(() => setQuestion(event.target.value))} />
            </div>
          </section>
          {tokens.length ? (
            <section className="box" aria-labelledby="masked-title">
              <div className="box-head"><h2 id="masked-title" className="box-title">{t("ui.variables")}</h2></div>
              <div className="box-body">
                {tokens.map((token) => (
                  <div key={token} className="fc-field">
                    <label className="fc-field-label" htmlFor={`mask-${token}`}>{t("ui.maskedValue", { token })}</label>
                    <input id={`mask-${token}`} className="fc-input" placeholder={t("reviewPage.realValue")} value={values[token] ?? ""}
                      onChange={(event) => edit(() => setValues({ ...values, [token]: event.target.value }))} />
                  </div>
                ))}
              </div>
            </section>
          ) : null}
          <section className="box" aria-labelledby="sql-title">
            <div className="box-head"><h2 id="sql-title" className="box-title">{t("ui.sql")}</h2></div>
            <div className="box-body">
              <textarea className="fc-textarea" aria-label={t("ui.sql")} spellCheck={false} value={formula} onChange={(event) => edit(() => setFormula(event.target.value))} />
            </div>
          </section>
          <section className="box" aria-labelledby="spec-title">
            <div className="box-head"><h2 id="spec-title" className="box-title">{t("ui.spec")}</h2></div>
            <div className="box-body">
              <Checkbox label={t("ui.useSpec")} checked={useSpec} onChange={(checked) => edit(() => setUseSpec(checked))} />
              {useSpec ? (
                <>
                  {field("dataset", t("ui.specDataset"))}
                  <div className="fields-2">
                    {field("metrics", t("ui.specMetrics"), { help: t("reviewPage.commaList") })}
                    {field("dimensions", t("ui.specDimensions"))}
                  </div>
                  {field("filters", t("ui.specFilters"), { multiline: true, help: t("reviewPage.filterHelp"),
                    error: specError !== null ? t("ui.specInvalid", { text: specError || "—" }) : null })}
                  <div className="fields-2">
                    {field("rankBy", t("ui.specRankBy"))}
                    {field("topN", t("ui.specTopN"), { numeric: true })}
                  </div>
                </>
              ) : null}
            </div>
          </section>
        </div>
        <div className="split-side">
          <TestBox run={run} runnable emptyText={why ?? t("ui.testEmpty")}
            action={<RunButton run={run} disabled={!filled || !body.trim() || !sql.trim() || specError !== null} onRun={async () => {
              setRun({ state: "running" });
              // The api test-runs the stored SQL, so the reviewer's edits are saved first.
              await api.review.update(item.id, { body, formula: sql, ...specPatch });
              const tested = await api.review.testRun(item.id);
              setRun({ state: "done", result: tested.test_result ?? undefined });
            }} />} />
          {sql.trim() ? <SqlView sql={sql} badge={false} defaultOpen /> : null}
        </div>
      </div>
    </DetailPage>
  );
}
