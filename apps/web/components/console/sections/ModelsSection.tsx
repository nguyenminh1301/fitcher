"use client";

// Models (DECISIONS §2 Model tiers, §9, §15): the providers, the model each chat task uses with the pack's latest
// evaluation of it, the embedding model and the optional prompt-injection classifier. A provider is added from
// the setup's provider cards and checked at once; a failed check removes it again. A provider can be checked,
// list its models, take a new key, or be removed unless a task or the embedding uses it. Picking a model for a
// task saves it at once; the evaluation informs the choice and never blocks it. Changing the embedding is
// confirmed, because the pack must be compiled again. No key is ever shown.

import { useCallback, useEffect, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { useConsole } from "@/components/console/ConsoleLayout";
import { ListPage } from "@/components/console/ListPage";
import { billing, PRESETS, presetById, presetIncomplete, providerCreate, type ProviderPreset } from "@/components/models/presets";
import { presetName, ProviderPicker } from "@/components/models/ProviderPicker";
import { Segmented, Switch } from "@/components/ui/controls";
import { Dialog } from "@/components/ui/overlay";
import type { FitcherApi } from "@/lib/api/client";
import { errorText } from "@/lib/api/errorText";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import type { ClassifierStatus, EmbeddingChange, ModelTiersView, ProviderTestResult, ProviderView, TierView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

const LOCAL_MODELS = [
  "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
  "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
];
const FETCH_COMMAND = "docker compose run --rm guard-model";

type Page = { providers: ProviderView[]; tiers: ModelTiersView; classifier: ClassifierStatus };
type Models = FitcherApi["models"];

/** The preset a stored provider came from: its kind, or the service its address belongs to. */
function presetOf(provider: ProviderView): ProviderPreset | null {
  if (provider.kind !== "openai_compatible") return PRESETS.find((preset) => preset.kind === provider.kind) ?? null;
  return PRESETS.find((preset) => preset.baseUrl && preset.baseUrl === provider.base_url)
    ?? PRESETS.find((preset) => preset.name === provider.name) ?? null;
}

/** What a test call found, in one line: fine, usable with a warning, or failed. */
function outcome(result: ProviderTestResult, t: (key: string, values?: Record<string, string | number>) => string): { ok: boolean; text: string } {
  if (result.structured_output) return { ok: true, text: t("models.testPassed", { model: result.model ?? "", count: result.models.length }) };
  if (result.model && result.models.length) return { ok: false, text: t("onboarding.noStructured", { model: result.model, reason: result.error ?? "" }) };
  return { ok: false, text: t("models.testFailed", { reason: result.error ?? t("onboarding.noReply") }) };
}

function AddDialog({ models, onClose, onAdded }: { models: Models; onClose: () => void; onAdded: (provider: ProviderView) => void }) {
  const { t } = useI18n();
  const [presetId, setPresetId] = useState("openai");
  const [apiKey, setApiKey] = useState("");
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const preset = presetById(presetId);
  const name = presetName(preset, t);

  async function add() {
    setBusy(true);
    setError(null);
    let provider: ProviderView | null = null;
    try {
      provider = await models.addProvider(providerCreate(preset, apiKey, address));
      const result = await models.testProvider(provider.id);
      if (!result.model) throw new Error(result.error ?? t("onboarding.noReply"));
      onAdded(provider);
    } catch (cause) {
      if (provider) await models.removeProvider(provider.id).catch(() => undefined);
      setError(errorText(cause));
      setBusy(false);
    }
  }

  const cost = billing(preset);
  return (
    <Dialog open wide title={t("modelsPage.addTitle")} closeLabel={t("common.close")} onClose={onClose}
      actions={<>
        {cost === "billed" ? <span className="fc-muted dlg-status">{t("onboarding.paidCheck", { name })}</span> : null}
        <button type="button" className="fc-btn" onClick={onClose}>{t("common.cancel")}</button>
        <button type="button" className="fc-btn fc-btn-primary" disabled={busy || presetIncomplete(preset, apiKey, address)} onClick={() => void add()}>
          {busy ? <span className="fc-spin fc-spinning" aria-hidden="true" /> : null}{t("modelsPage.checkAndAdd")}
        </button>
      </>}>
      <ProviderPicker presetId={presetId} onPreset={(id) => { setPresetId(id); setAddress(presetById(id).suggestedUrl ?? ""); setError(null); }}
        apiKey={apiKey} onApiKey={setApiKey} address={address} onAddress={setAddress} error={error} disabled={busy} />
    </Dialog>
  );
}

function ProviderRow({ models, provider, onChanged, onRemove }: {
  models: Models; provider: ProviderView; onChanged: (text: string) => Promise<void>; onRemove: () => void;
}) {
  const { t } = useI18n();
  const preset = presetOf(provider);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [listed, setListed] = useState<string[] | null>(null);
  const [key, setKey] = useState<string | null>(null);
  const [busy, setBusy] = useState<"test" | "list" | "key" | null>(null);

  async function act(kind: "test" | "list" | "key", action: () => Promise<void>) {
    setBusy(kind);
    try {
      await action();
    } catch (cause) {
      setResult({ ok: false, text: t("models.failed", { reason: errorText(cause) }) });
    } finally {
      setBusy(null);
    }
  }

  const group = preset?.group ?? "other";
  const where = t(`modelsPage.group_${group}`);
  const keyText = provider.key_set ? t("models.keySet", { last4: provider.key_last4 ?? "" }) : t("models.noKey");
  const takesKey = (preset?.key ?? "optional") !== "none";
  return (
    <div className="prov-row" aria-label={provider.name} role="group">
      <span className="opt-icon"><Icon name={group === "hosted" ? "sparkles" : group === "local" ? "laptop" : "cloud"} /></span>
      <div className="prov-main">
        <div className="prov-name">{provider.name}{provider.in_use ? <span className="fc-label fc-label-success">{t("models.inUse")}</span> : null}</div>
        <div className="fc-muted">{where} · {keyText}</div>
      </div>
      <div className="toolbar">
        <button type="button" className="fc-btn fc-btn-sm" disabled={busy !== null}
          onClick={() => void act("test", async () => setResult(outcome(await models.testProvider(provider.id), t)))}>
          {busy === "test" ? <span className="fc-spin fc-spinning" aria-hidden="true" /> : null}{t("models.test")}
        </button>
        <button type="button" className="fc-btn fc-btn-sm" disabled={busy !== null} aria-expanded={listed !== null}
          onClick={() => (listed ? setListed(null) : void act("list", async () => setListed((await models.providerModels(provider.id)).models)))}>
          {t("models.listModels")}
        </button>
        {takesKey ? <button type="button" className="fc-btn fc-btn-sm" disabled={busy !== null} onClick={() => setKey(key === null ? "" : null)}>{t("models.replaceKey")}</button> : null}
        <button type="button" className="fc-btn fc-btn-ghost fc-btn-icon fc-btn-sm" aria-label={t("modelsPage.removeOf", { name: provider.name })}
          disabled={provider.in_use} title={provider.in_use ? t("modelsPage.inUseNote") : undefined} onClick={onRemove}><Icon name="trash" /></button>
      </div>
      {result || listed || key !== null || (provider.hosted && preset && billing(preset) === "billed") ? (
        <div className="prov-extra">
          {provider.hosted && preset && billing(preset) === "billed" ? <span className="fc-field-help">{t("onboarding.paidCheck", { name: provider.name })}</span> : null}
          {key !== null ? (
            <form className="prov-key" onSubmit={(event) => { event.preventDefault(); void act("key", async () => {
              await models.changeProvider(provider.id, { api_key: key });
              setKey(null);
              await onChanged(t("models.keySaved", { name: provider.name }));
            }); }}>
              <div className="fc-field">
                <label className="fc-field-label" htmlFor={`key-${provider.id}`}>{t("modelsPage.newKey", { name: provider.name })}</label>
                <input id={`key-${provider.id}`} className="fc-input fc-input-sm" type="password" autoComplete="off" placeholder={t("onboarding.keyPlaceholder")}
                  value={key} onChange={(event) => setKey(event.target.value)} />
              </div>
              <button type="button" className="fc-btn fc-btn-sm" onClick={() => setKey(null)}>{t("common.cancel")}</button>
              <button type="submit" className="fc-btn fc-btn-primary fc-btn-sm" disabled={!key || busy !== null}>{t("models.saveKey")}</button>
            </form>
          ) : null}
          {result ? (
            <div className={`fc-banner ${result.ok ? "fc-banner-success" : "fc-banner-attention"}`} role="status"><Icon name={result.ok ? "check" : "alert"} /><div>{result.text}</div></div>
          ) : null}
          {listed ? <pre className="prov-models" aria-label={t("modelsPage.modelsOf", { name: provider.name })}>{listed.length ? listed.join("\n") : t("onboarding.noMatchPlain")}</pre> : null}
        </div>
      ) : null}
    </div>
  );
}

function EvalLabel({ tier }: { tier: TierView }) {
  const { t } = useI18n();
  if (!tier.eval || !tier.eval.evaluated) return <span className="fc-label">{t("models.notEvaluated")}</span>;
  return tier.eval.passed
    ? <span className="fc-label fc-label-success">{t("models.evalPassed")}</span>
    : <span className="fc-label fc-label-attention">{t("models.evalNotPassed", { reason: tier.eval.reason })}</span>;
}

function TierRow({ models, tier, providers, listOf, onSaved }: {
  models: Models; tier: TierView; providers: ProviderView[]; listOf: (id: string) => Promise<string[]>; onSaved: (text: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const [providerId, setProviderId] = useState(tier.provider_id ?? "");
  const [listed, setListed] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!providerId) return;
    let live = true;
    listOf(providerId).then((list) => { if (live) setListed(list); }).catch(() => { if (live) setListed([]); });
    return () => { live = false; };
  }, [providerId, listOf]);

  async function save(model: string) {
    setError(null);
    try {
      await models.setTier(tier.tier, { provider_id: providerId, model });
      await onSaved(t("models.tierSaved", { tier: tier.tier, model }));
    } catch (cause) {
      setError(t("models.failed", { reason: errorText(cause) }));
    }
  }

  const current = providerId === tier.provider_id ? tier.model ?? "" : "";
  const options = [...new Set([...(current ? [current] : []), ...(listed ?? [])])];
  return (
    <tr>
      <td><span>{t(`onboarding.tier_${tier.tier}`)}</span> <span className="fc-mono fc-muted">{tier.tier}</span></td>
      <td>
        <div className="sel">
          <select className="fc-input fc-input-sm" aria-label={t("modelsPage.providerFor", { tier: tier.tier })} value={providerId}
            onChange={(event) => setProviderId(event.target.value)}>
            {tier.provider_id ? null : <option value="">{t("onboarding.noModel")}</option>}
            {providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}
          </select>
          <Icon name="chevronDown" />
        </div>
      </td>
      <td>
        <div className="sel">
          <select className="fc-input fc-input-sm" aria-label={t("modelsPage.modelFor", { tier: tier.tier })} value={current} disabled={!providerId}
            onChange={(event) => { if (event.target.value) void save(event.target.value); }}>
            {current ? null : <option value="">{listed === null && providerId ? t("onboarding.loadingModels") : t("onboarding.noModel")}</option>}
            {options.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
          <Icon name="chevronDown" />
        </div>
        {error ? <span className="fc-field-error" role="alert"><Icon name="alert" />{error}</span> : null}
      </td>
      <td><EvalLabel tier={tier} /></td>
    </tr>
  );
}

function EmbeddingDialog({ models, view, providers, onClose, onSaved }: {
  models: Models; view: ModelTiersView["embedding"]; providers: ProviderView[]; onClose: () => void; onSaved: (text: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const [backend, setBackend] = useState<EmbeddingChange["backend"]>(view.backend);
  const [model, setModel] = useState(view.model);
  const [providerId, setProviderId] = useState(view.provider_id ?? providers[0]?.id ?? "");
  const [dimensions, setDimensions] = useState(String(view.dimensions));
  const [error, setError] = useState<string | null>(null);

  async function change() {
    const body: EmbeddingChange = backend === "local"
      ? { backend, model, confirm_reindex: true }
      : { backend, model, provider_id: providerId, dimensions: Number(dimensions), confirm_reindex: true };
    try {
      await models.setEmbedding(body);
      onClose();
      await onSaved(t("models.embeddingSaved"));
    } catch (cause) {
      setError(t("models.failed", { reason: errorText(cause) }));
    }
  }

  const unchanged = backend === view.backend && model === view.model && (backend === "local" || (providerId === view.provider_id && Number(dimensions) === view.dimensions));
  return (
    <Dialog open title={t("models.reindexTitle")} closeLabel={t("common.close")} onClose={onClose}
      actions={<>
        <button type="button" className="fc-btn" onClick={onClose}>{t("common.cancel")}</button>
        <button type="button" className="fc-btn fc-btn-primary" disabled={!model || unchanged} onClick={() => void change()}>{t("modelsPage.changeModel")}</button>
      </>}>
      <p style={{ margin: 0 }}>{t("models.reindexText")}</p>
      <div className="fc-field">
        <span className="fc-field-label">{t("models.embeddingBackend")}</span>
        <div style={{ alignSelf: "flex-start" }}>
          <Segmented label={t("models.embeddingBackend")} value={backend}
            onChange={(next) => { setBackend(next as EmbeddingChange["backend"]); setModel(next === "local" ? LOCAL_MODELS[0] : ""); }}
            options={[["local", t("models.backend_local")], ...(providers.length ? [["provider", t("models.backend_provider")] as [string, string]] : [])]} />
        </div>
      </div>
      {backend === "local" ? (
        <div className="fc-field">
          <label className="fc-field-label" htmlFor="embedding-model">{t("models.embeddingModel")}</label>
          <div className="sel">
            <select id="embedding-model" className="fc-input" value={model} onChange={(event) => setModel(event.target.value)}>
              {LOCAL_MODELS.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
            <Icon name="chevronDown" />
          </div>
        </div>
      ) : (
        <>
          <div className="fc-field">
            <label className="fc-field-label" htmlFor="embedding-provider">{t("models.tierProvider")}</label>
            <div className="sel">
              <select id="embedding-provider" className="fc-input" value={providerId} onChange={(event) => setProviderId(event.target.value)}>
                {providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}
              </select>
              <Icon name="chevronDown" />
            </div>
          </div>
          <div className="fc-field">
            <label className="fc-field-label" htmlFor="embedding-name">{t("models.embeddingModel")}</label>
            <input id="embedding-name" className="fc-input" value={model} onChange={(event) => setModel(event.target.value)} />
          </div>
          <div className="fc-field">
            <label className="fc-field-label" htmlFor="embedding-dimensions">{t("models.dimensions")}</label>
            <input id="embedding-dimensions" className="fc-input" inputMode="numeric" value={dimensions} onChange={(event) => setDimensions(event.target.value)} />
          </div>
        </>
      )}
      {error ? <span className="fc-field-error" role="alert"><Icon name="alert" />{error}</span> : null}
    </Dialog>
  );
}

export function ModelsSection() {
  const { t } = useI18n();
  const { api } = useChat();
  const { toast } = useConsole();
  const models = api.models;
  const { data, failed, reload } = useLoad(useCallback(async (): Promise<Page> => {
    const [providers, tiers, classifier] = await Promise.all([models.providers(), models.tiers(), models.classifier()]);
    return { providers, tiers, classifier };
  }, [models]));
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<ProviderView | null>(null);
  const [embedding, setEmbedding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Each provider's model list is read once and shared by the task rows.
  const [lists] = useState(() => new Map<string, Promise<string[]>>());
  const listOf = useCallback((id: string) => {
    if (!lists.has(id)) lists.set(id, models.providerModels(id).then((reply) => [...reply.models].sort()).catch(() => []));
    return lists.get(id) as Promise<string[]>;
  }, [lists, models]);

  const changed = async (text: string) => {
    toast(text);
    await reload();
  };

  async function remove() {
    const pending = removing;
    setRemoving(null);
    if (!pending) return;
    try {
      await models.removeProvider(pending.id);
      setError(null);
      await changed(t("models.removed", { name: pending.name }));
    } catch (cause) {
      setError(t("models.failed", { reason: errorText(cause) }));
    }
  }

  async function toggleClassifier(status: ClassifierStatus) {
    try {
      await models.setClassifier(!status.enabled);
      await changed(status.enabled ? t("modelsPage.classifierOff") : t("modelsPage.classifierOn"));
    } catch (cause) {
      setError(t("models.failed", { reason: errorText(cause) }));
    }
  }

  const add = <button type="button" className="fc-btn fc-btn-primary" onClick={() => setAdding(true)}><Icon name="plus" />{t("modelsPage.addProvider")}</button>;
  const view = data?.tiers.embedding;
  return (
    <ListPage section="models" loading={!data} failed={failed} skeleton="page" actions={data?.providers.length ? add : undefined}>
      {error ? <div className="fc-banner fc-banner-danger" role="alert"><Icon name="alert" /><div>{error}</div></div> : null}
      {data && !data.providers.length ? (
        <div className="box">
          <div className="empty">
            <div className="empty-icon"><Icon name="cpu" size="lg" /></div>
            <p className="empty-title">{t("modelsPage.emptyTitle")}</p>
            <p className="empty-text">{t("modelsPage.emptyText")}</p>
            {add}
          </div>
        </div>
      ) : null}
      {data?.providers.length ? (
        <>
          <section className="box" aria-labelledby="providers-title">
            <div className="box-head"><h2 id="providers-title" className="box-title">{t("models.providers")}</h2></div>
            {data.providers.map((provider) => (
              <ProviderRow key={provider.id} models={models} provider={provider} onChanged={changed} onRemove={() => setRemoving(provider)} />
            ))}
          </section>
          <section className="box" aria-labelledby="tiers-title">
            <div className="box-head"><h2 id="tiers-title" className="box-title">{t("modelsPage.tiersTitle")}</h2></div>
            <div style={{ overflowX: "auto" }}>
              <table className="tbl tier-table">
                <thead><tr><th>{t("modelsPage.task")}</th><th>{t("models.tierProvider")}</th><th>{t("models.tierModel")}</th><th>{t("modelsPage.latestEval")}</th></tr></thead>
                <tbody>
                  {data.tiers.tiers.map((tier) => (
                    <TierRow key={`${tier.tier}-${tier.provider_id}-${tier.model}`} models={models} tier={tier} providers={data.providers} listOf={listOf} onSaved={changed} />
                  ))}
                </tbody>
              </table>
            </div>
            <p className="fc-field-help box-note">{t("modelsPage.evalNote")}</p>
          </section>
        </>
      ) : null}
      {view ? (
        <section className="box" aria-labelledby="embedding-title">
          <div className="box-head"><h2 id="embedding-title" className="box-title">{t("models.embedding")}</h2></div>
          <div className="box-body">
            {view.needs_reindex ? <div className="fc-banner fc-banner-attention" role="status"><Icon name="alert" /><div>{t("models.needsReindex")}</div></div> : null}
            <dl className="kv">
              <dt>{t("models.embeddingBackend")}</dt><dd>{view.backend === "local" ? t("models.backend_local") : data?.providers.find((p) => p.id === view.provider_id)?.name ?? view.provider_id}</dd>
              <dt>{t("models.embeddingModel")}</dt><dd className="fc-mono">{view.model}</dd>
              <dt>{t("models.dimensions")}</dt><dd>{view.dimensions}</dd>
            </dl>
            <div><button type="button" className="fc-btn fc-btn-sm" onClick={() => setEmbedding(true)}>{t("models.changeEmbedding")}</button></div>
          </div>
        </section>
      ) : null}
      {data ? (
        <section className="box" aria-labelledby="classifier-title">
          <div className="box-head"><h2 id="classifier-title" className="box-title">{t("models.classifier")}</h2></div>
          <div className="box-body">
            <div>
              <Switch label={t("models.classifier")} checked={data.classifier.enabled} disabled={!data.classifier.enabled && !data.classifier.model_present}
                onChange={() => void toggleClassifier(data.classifier)} />
            </div>
            <p className="fc-muted" style={{ margin: 0 }}>{t("models.classifierOff")}</p>
            <p className="fc-muted" style={{ margin: 0 }}>{t("models.classifierOn")}</p>
            {!data.classifier.model_present ? (
              <div className="fc-banner fc-banner-info" role="status"><Icon name="info" /><div>{t("models.classifierMissing", { command: FETCH_COMMAND })}</div></div>
            ) : null}
          </div>
        </section>
      ) : null}
      {adding ? <AddDialog models={models} onClose={() => setAdding(false)} onAdded={(provider) => { setAdding(false); void changed(t("models.added", { name: provider.name })); }} /> : null}
      {embedding && view && data ? <EmbeddingDialog models={models} view={view} providers={data.providers} onClose={() => setEmbedding(false)} onSaved={changed} /> : null}
      <Dialog open={!!removing} tone="danger" title={t("models.removeTitle", { name: removing?.name ?? "" })} closeLabel={t("common.close")} onClose={() => setRemoving(null)}
        actions={<>
          <button type="button" className="fc-btn" onClick={() => setRemoving(null)}>{t("common.cancel")}</button>
          <button type="button" className="fc-btn fc-btn-danger" onClick={() => void remove()}>{t("models.remove")}</button>
        </>}>
        <p style={{ margin: 0 }}>{t("models.removeText")}</p>
      </Dialog>
    </ListPage>
  );
}
