"use client";

// Review (DECISIONS §11, §15): pack items drafted from documents and data profiles, grouped by file,
// and examples proposed from feedback. A metric is test-run before approval; a proposal is approved
// only after its masked values are replaced and its SQL has been test-run.

import { useCallback, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { DataTable } from "@/components/chat/DataTable";
import { highlight, SqlView } from "@/components/chat/SqlView";
import { ConfidenceMeter } from "@/components/console/ConfidenceMeter";
import { useConsole } from "@/components/console/ConsoleLayout";
import { DetailPage } from "@/components/console/DetailPage";
import { ListPage, ListRow } from "@/components/console/ListPage";
import { Button, Segmented, Tabs, TextField } from "@/components/ui/controls";
import { EmptyState, Skeleton, StatusPill, WarningBanner } from "@/components/ui/feedback";
import type { ReviewItem } from "@/lib/contracts";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import type { Result } from "@/lib/contracts";
import { cx } from "@/lib/cx";
import { useI18n } from "@/lib/i18n/react";
import { langOf } from "@/lib/text";

const MASK = /\[MASKED_[A-Z0-9_]+\]/g;

function useReviewItems() {
  const { api } = useChat();
  return useLoad(useCallback(() => api.review.items(), [api]));
}

export function ReviewSection() {
  const { t } = useI18n();
  const { navigate } = useConsole();
  const { data, failed } = useReviewItems();
  const [tab, setTab] = useState("items");
  const [filter, setFilter] = useState("all");
  const items = (data ?? []).filter((item) => item.kind === "item");
  const proposals = (data ?? []).filter((item) => item.kind === "proposal" && item.status === "draft");
  const shown = items.filter((item) => filter === "all" || item.status === filter);
  const files = [...new Set(shown.map((item) => item.file))];
  const open = (item: ReviewItem) => navigate(`/console/review/${encodeURIComponent(item.id)}`);

  return (
    <ListPage section="review" loading={!data} failed={failed}>
      <Tabs label={t("ui.nav_review")} value={tab} onChange={setTab}
        tabs={[{ id: "items", label: t("ui.items"), count: items.length }, { id: "proposals", label: t("ui.proposals"), count: proposals.length }]} />
      {tab === "items" ? (
        <>
          <div className="fc-toolbar">
            <Segmented label={t("ui.status")} value={filter} onChange={setFilter}
              options={(["all", "draft", "approved"] as const).map((value) => [value, t(`ui.${value}`)])} />
          </div>
          {files.length ? files.map((file) => {
            const group = shown.filter((item) => item.file === file);
            return (
              <section key={file} className="fc-card">
                <div className="fc-card-head">
                  <h2 className="fc-group-label"><Icon name="fileText" />{file}</h2>
                  <span className="fc-counter" style={{ marginRight: "var(--base-size-8)" }}>{group.length}</span>
                </div>
                <ul className="fc-list">
                  {group.map((item) => (
                    <ListRow key={item.id} mono title={item.name} sub={item.body} subLang={langOf(item.body)} onOpen={() => open(item)}
                      side={<><StatusPill status={item.status} /><span className="fc-hide-sm"><ConfidenceMeter value={item.confidence} /></span></>} />
                  ))}
                </ul>
              </section>
            );
          }) : (
            <div className="fc-card"><EmptyState title={t("ui.noItems")}>{t("ui.noItemsText")}</EmptyState></div>
          )}
        </>
      ) : (
        <>
          <WarningBanner tone="info">{t("ui.proposalsNote")}</WarningBanner>
          <section className="fc-card">
            {proposals.length ? (
              <ul className="fc-list">
                {proposals.map((item) => (
                  <ListRow key={item.id} title={item.body} titleLang={langOf(item.body)} sub={item.evidence?.source} onOpen={() => open(item)} side={<StatusPill status={item.status} />} />
                ))}
              </ul>
            ) : <EmptyState title={t("ui.noItems")} />}
          </section>
        </>
      )}
    </ListPage>
  );
}

type Run = { state: "idle" | "running" | "done"; result?: Result };

/** The Test run pane: what a metric's formula or a proposal's SQL returns on the data. */
function TestPane({ run, runnable, emptyText }: { run: Run; runnable: boolean; emptyText: string }) {
  const { t } = useI18n();
  let body;
  if (!runnable) body = <EmptyState icon="fileText" title={t("ui.noTestTitle")}>{t("ui.noTestText")}</EmptyState>;
  else if (run.state === "running") body = <Skeleton variant="table" rows={2} />;
  else if (run.state === "done" && run.result) body = <DataTable result={run.result} title={t("ui.testOk", { n: run.result.row_count })} />;
  else body = <EmptyState icon="play" title={t("ui.testPanel")}>{emptyText}</EmptyState>;
  return <div className="fc-preview"><h2 className="fc-card-title">{t("ui.testPanel")}</h2>{body}</div>;
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
  return (
    <DetailPage feature="review"
      title={item?.name}
      mono
      status={item?.status}
      onBack={back}
      loading={loading}
      missing={!item}
      actions={item ? (editing ? (
        <>
          <Button variant="ghost" onClick={() => { setBody(item.body); setFormula(item.formula ?? ""); setEditing(false); }}>{t("ui.cancel")}</Button>
          <Button variant="primary" onClick={async () => {
            await api.review.update(item.id, item.formula === undefined ? { body } : { body, formula });
            setEditing(false);
            await reload();
          }}>{t("ui.save")}</Button>
        </>
      ) : (
        <>
          {item.formula ? (
            <Button icon={run.state === "running" ? "loader" : "play"} disabled={run.state === "running"} onClick={() => void test(item)}>
              {run.state === "running" ? t("ui.running") : t("ui.testRun")}
            </Button>
          ) : null}
          <Button icon="pencil" onClick={() => setEditing(true)}>{t("ui.edit")}</Button>
          {item.status !== "approved" ? (
            <Button variant="primary" icon="check" onClick={async () => {
              await api.review.approve(item.id);
              toast(t("ui.approvedName", { name: item.name }));
              await reload();
            }}>{t("ui.approve")}</Button>
          ) : null}
          <Button variant="danger" iconOnly icon="trash" label={`${t("ui.del")} ${item.name}`} onClick={async () => {
            await api.review.remove(item.id);
            toast(t("ui.deletedName", { name: item.name }));
            back();
          }} />
        </>
      )) : null}
    >
      {item ? (
        <div className="fc-split">
          <div>
            <dl className="fc-kv">
              <dt>{t("ui.body")}</dt>
              <dd className={cx(editing && "fc-kv-ctl")}>
                {editing ? <TextField multiline aria-label={t("ui.body")} value={body} onChange={(event) => setBody(event.target.value)} />
                  : <p className="fc-review-body" lang={langOf(item.body)}>{item.body}</p>}
              </dd>
              {item.formula !== undefined ? (
                <>
                  <dt>{t("ui.formula")}</dt>
                  <dd className="fc-kv-ctl">
                    {editing ? <TextField multiline aria-label={t("ui.formula")} value={formula} onChange={(event) => setFormula(event.target.value)} />
                      : <pre className="fc-formula"><code>{highlight(item.formula ?? "")}</code></pre>}
                  </dd>
                </>
              ) : null}
              {evidence ? (
                <>
                  <dt>{t("ui.evidence")}</dt>
                  <dd>
                    <div className={cx("fc-evidence", evidence.deleted && "fc-evidence-deleted")}>
                      <span className="fc-evidence-src">
                        <Icon name={evidence.deleted ? "flag" : "fileText"} />
                        {evidence.deleted ? `${t("ui.deletedSource")}: ${evidence.source}` : evidence.source}
                      </span>
                      {evidence.quote ? <q lang={langOf(evidence.quote)}>{evidence.quote}</q> : null}
                    </div>
                  </dd>
                </>
              ) : null}
              <dt>{t("ui.confidence")}</dt>
              <dd><ConfidenceMeter value={item.confidence} /></dd>
              <dt>{t("ui.sourceFile")}</dt>
              <dd><code className="fc-code">{item.file}</code></dd>
            </dl>
          </div>
          <div><TestPane run={run} runnable={!!item.formula} emptyText={t("ui.testEmpty")} /></div>
        </div>
      ) : null}
    </DetailPage>
  );
}

function ProposalDetail({ item, reload }: { item: ReviewItem; reload: () => Promise<void> }) {
  const { t } = useI18n();
  const { api } = useChat();
  const { navigate, toast } = useConsole();
  const [values, setValues] = useState<Record<string, string>>({});
  const [run, setRun] = useState<Run>({ state: "idle" });
  const tokens = [...new Set([...item.body.matchAll(MASK), ...(item.formula ?? "").matchAll(MASK)].map((match) => match[0]))];
  const filled = tokens.every((token) => values[token]?.trim());
  const fill = (text: string, quote: boolean) => tokens.reduce((out, token) => {
    const value = values[token]?.trim();
    return value ? out.split(token).join(quote ? value.replace(/'/g, "''") : value) : out;
  }, text);
  const sql = fill(item.formula ?? "", true);
  const back = () => navigate("/console/review");

  return (
    <DetailPage feature="review"
      title={t("ui.proposals")}
      status={item.status}
      onBack={back}
      loading={false}
      meta={<span className="fc-help">{!filled ? t("ui.replaceFirst") : run.state !== "done" ? t("ui.testFirst") : ""}</span>}
      actions={
        <>
          <Button icon={run.state === "running" ? "loader" : "play"} disabled={!filled || run.state === "running"} onClick={async () => {
            setRun({ state: "running" });
            const tested = await api.review.testRun(item.id);
            setRun({ state: "done", result: tested.test_result ?? undefined });
          }}>{t("ui.testRun")}</Button>
          <Button variant="primary" icon="check" disabled={run.state !== "done"} onClick={async () => {
            await api.review.update(item.id, { body: fill(item.body, false), formula: sql });
            await api.review.approve(item.id);
            toast(t("ui.approvedName", { name: fill(item.body, false) }));
            await reload();
            back();
          }}>{t("ui.approve")}</Button>
          <Button variant="danger" iconOnly icon="trash" label={t("ui.del")} onClick={async () => {
            await api.review.remove(item.id);
            toast(t("ui.deletedName", { name: item.name }));
            back();
          }} />
        </>
      }
    >
      <div className="fc-split">
        <div>
          <dl className="fc-kv">
            <dt>{t("ui.question")}</dt>
            <dd lang={langOf(item.body)}>{item.body}</dd>
            <dt>{t("ui.origin")}</dt>
            <dd>{item.evidence?.source ?? "—"}{item.evidence?.quote ? <>{" "}<q lang={langOf(item.evidence.quote)}>{item.evidence.quote}</q></> : null}</dd>
            <dt>{t("ui.variables")}</dt>
            <dd className="fc-kv-ctl">
              <div className="fc-stack" style={{ gap: "var(--base-size-12)" }}>
                {tokens.map((token) => (
                  <TextField key={token} label={t("ui.maskedValue", { token })} value={values[token] ?? ""}
                    onChange={(event) => { setValues({ ...values, [token]: event.target.value }); setRun({ state: "idle" }); }} />
                ))}
              </div>
            </dd>
          </dl>
        </div>
        <div>
          <div className="fc-preview">
            <h2 className="fc-card-title">{t("ui.testPanel")}</h2>
            <SqlView sql={sql} badge={false} defaultOpen />
            {run.state === "running" ? <Skeleton variant="table" rows={2} />
              : run.state === "done" && run.result ? <DataTable result={run.result} title={t("ui.testOk", { n: run.result.row_count })} />
                : <EmptyState icon="play" title={t("ui.testPanel")}>{t(!filled ? "ui.replaceFirst" : "ui.testFirst")}</EmptyState>}
          </div>
        </div>
      </div>
    </DetailPage>
  );
}
