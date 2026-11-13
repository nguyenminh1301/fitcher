"use client";

// Models (DECISIONS §2 Model tiers, §9, §15): the providers with whether a key is set, each chat tier with
// its model and the pack's latest eval result for it, the embedding model and the optional screening
// classifier. An admin adds, tests and removes providers and maps a tier to any model of a configured
// provider; the eval result informs the choice and never gates it. Changing the embedding is a separate,
// confirmed action, because the pack must be recompiled with the new model. No key is ever shown.

import { useCallback, useState } from "react";

import { useConsole } from "@/components/console/ConsoleLayout";
import { ListPage } from "@/components/console/ListPage";
import { ProviderForm, ProviderTestButton, TestOutcome } from "@/components/models/ProviderForm";
import { Button, TextField } from "@/components/ui/controls";
import { StatusPill, WarningBanner } from "@/components/ui/feedback";
import { Dialog } from "@/components/ui/overlay";
import type { FitcherApi } from "@/lib/api/client";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import type {
  ClassifierStatus, EmbeddingChange, ModelTiersView, ProviderTestResult, ProviderView, TierView,
} from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

const LOCAL_MODELS = [
  "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
  "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
];
const FETCH_COMMAND = "docker compose run --rm guard-model";

type Page = { providers: ProviderView[]; tiers: ModelTiersView; classifier: ClassifierStatus };
type Models = FitcherApi["models"];

function message(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

function ProviderRow({ models, provider, onChanged, onRemove }: {
  models: Models; provider: ProviderView; onChanged: (text: string) => Promise<void>; onRemove: () => void;
}) {
  const { t } = useI18n();
  const [test, setTest] = useState<{ result: ProviderTestResult | null; error?: string } | null>(null);
  const [key, setKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function saveKey() {
    if (!key) return;
    try {
      await models.changeProvider(provider.id, { api_key: key });
      setKey(null);
      setError(null);
      await onChanged(t("models.keySaved", { name: provider.name }));
    } catch (cause) {
      setError(t("models.failed", { reason: message(cause) }));
    }
  }

  return (
    <li className="fc-stack" style={{ gap: "var(--base-size-8)" }} aria-label={provider.name}>
      <div className="fc-row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: "var(--base-size-8)" }}>
        <span>
          <strong>{provider.name}</strong> <span className="fc-muted">{t(`models.kind_${provider.kind}`)}</span>
          {provider.base_url ? <> · <code className="fc-code">{provider.base_url}</code></> : null}
          {" · "}{provider.key_set ? t("models.keySet", { last4: provider.key_last4 ?? "" }) : t("models.noKey")}
          {provider.in_use ? <> · <StatusPill status="active">{t("models.inUse")}</StatusPill></> : null}
        </span>
        <span className="fc-row" style={{ gap: "var(--base-size-8)" }}>
          <ProviderTestButton models={models} provider={provider} onResult={(result, failure) => setTest({ result, error: failure })} />
          {provider.kind !== "ollama" ? <Button size="sm" onClick={() => setKey(key === null ? "" : null)}>{t("models.replaceKey")}</Button> : null}
          <Button size="sm" disabled={provider.in_use} onClick={onRemove}>{t("models.remove")}</Button>
        </span>
      </div>
      {key !== null ? (
        <form className="fc-row" style={{ gap: "var(--base-size-8)", alignItems: "flex-end" }}
          onSubmit={(event) => { event.preventDefault(); void saveKey(); }}>
          <TextField label={t("models.apiKey")} type="password" autoComplete="off" value={key} onChange={(event) => setKey(event.target.value)} />
          <Button type="submit" variant="primary" disabled={!key}>{t("models.saveKey")}</Button>
        </form>
      ) : null}
      {test?.result ? <TestOutcome result={test.result} /> : null}
      {test?.error ? <WarningBanner tone="danger">{t("models.testFailed", { reason: test.error })}</WarningBanner> : null}
      {error ? <WarningBanner tone="danger">{error}</WarningBanner> : null}
    </li>
  );
}

function EvalNote({ tier }: { tier: TierView }) {
  const { t, formatDate } = useI18n();
  if (!tier.eval || !tier.eval.evaluated) return <span className="fc-muted">{t("models.notEvaluated")}</span>;
  const when = tier.eval.report_ts ? ` · ${formatDate(tier.eval.report_ts)}` : "";
  return tier.eval.passed
    ? <span><StatusPill status="eligible">{t("models.evalPassed")}</StatusPill><span className="fc-muted">{when}</span></span>
    : <span className="fc-muted">{t("models.evalNotPassed", { reason: tier.eval.reason })}{when}</span>;
}

function TierRow({ models, tier, providers, onSaved }: {
  models: Models; tier: TierView; providers: ProviderView[]; onSaved: (text: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const [providerId, setProviderId] = useState(tier.provider_id ?? providers[0]?.id ?? "");
  const [model, setModel] = useState(tier.model ?? "");
  const [listed, setListed] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const listId = `tier-models-${tier.tier}`;

  async function list() {
    try {
      setListed((await models.providerModels(providerId)).models);
      setError(null);
    } catch (cause) {
      setError(message(cause));
    }
  }

  async function save() {
    setBusy(true);
    try {
      await models.setTier(tier.tier, { provider_id: providerId, model });
      setError(null);
      await onSaved(t("models.tierSaved", { tier: tier.tier, model }));
    } catch (cause) {
      setError(t("models.failed", { reason: message(cause) }));
    } finally {
      setBusy(false);
    }
  }

  const unchanged = providerId === tier.provider_id && model === tier.model;
  return (
    <section className="fc-card" aria-label={tier.tier}>
      <div className="fc-card-head"><h2 className="fc-card-title fc-mono">{tier.tier}</h2></div>
      <div className="fc-card-body fc-stack" style={{ gap: "var(--base-size-12)" }}>
        <p style={{ margin: 0 }}>{t(`ui.tierDesc_${tier.tier.replace(/-/g, "_")}`)}</p>
        <p style={{ margin: 0 }}>
          <code className="fc-code">{tier.model ? `${tier.provider_id}/${tier.model}` : t("models.notMapped")}</code> · <EvalNote tier={tier} />
        </p>
        <div className="fc-row" style={{ gap: "var(--base-size-8)", alignItems: "flex-end", flexWrap: "wrap" }}>
          <div className="fc-field">
            <label className="fc-field-label" htmlFor={`${listId}-provider`}>{t("models.tierProvider")}</label>
            <select id={`${listId}-provider`} className="fc-input" value={providerId} disabled={busy || !providers.length}
              onChange={(event) => { setProviderId(event.target.value); setListed([]); }}>
              {providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}
            </select>
          </div>
          <TextField label={t("models.tierModel")} value={model} list={listId} disabled={busy || !providers.length}
            onChange={(event) => setModel(event.target.value)} />
          <datalist id={listId}>{listed.map((name) => <option key={name} value={name} />)}</datalist>
          <Button size="sm" disabled={busy || !providerId} onClick={() => void list()}>{t("models.listModels")}</Button>
          <Button size="sm" variant="primary" disabled={busy || !providerId || !model || unchanged} onClick={() => void save()}>
            {t("models.useModel")}
          </Button>
        </div>
        {error ? <WarningBanner tone="danger">{error}</WarningBanner> : null}
      </div>
    </section>
  );
}

function EmbeddingCard({ models, view, providers, onSaved }: {
  models: Models; view: ModelTiersView["embedding"]; providers: ProviderView[]; onSaved: (text: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const [backend, setBackend] = useState<EmbeddingChange["backend"]>(view.backend);
  const [model, setModel] = useState(view.model);
  const [providerId, setProviderId] = useState(view.provider_id ?? providers[0]?.id ?? "");
  const [dimensions, setDimensions] = useState(String(view.dimensions));
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function change() {
    setConfirming(false);
    const body: EmbeddingChange = backend === "local"
      ? { backend, model, confirm_reindex: true }
      : { backend, model, provider_id: providerId, dimensions: Number(dimensions), confirm_reindex: true };
    try {
      await models.setEmbedding(body);
      setError(null);
      await onSaved(t("models.embeddingSaved"));
    } catch (cause) {
      setError(t("models.failed", { reason: message(cause) }));
    }
  }

  return (
    <section className="fc-card" aria-label={t("models.embedding")}>
      <div className="fc-card-head"><h2 className="fc-card-title">{t("models.embedding")}</h2></div>
      <div className="fc-card-body fc-stack" style={{ gap: "var(--base-size-12)" }}>
        <p style={{ margin: 0 }}>
          {view.backend === "local"
            ? t("models.embeddingLocal", { model: view.model, dimensions: view.dimensions })
            : t("models.embeddingProvider", { provider: view.provider_id ?? "", model: view.model, dimensions: view.dimensions })}
        </p>
        {view.needs_reindex ? <WarningBanner tone="warning">{t("models.needsReindex")}</WarningBanner> : null}
        <div className="fc-row" style={{ gap: "var(--base-size-8)", alignItems: "flex-end", flexWrap: "wrap" }}>
          <div className="fc-field">
            <label className="fc-field-label" htmlFor="embedding-backend">{t("models.embeddingBackend")}</label>
            <select id="embedding-backend" className="fc-input" value={backend}
              onChange={(event) => {
                const next = event.target.value as EmbeddingChange["backend"];
                setBackend(next);
                setModel(next === "local" ? LOCAL_MODELS[0] : "");
              }}>
              <option value="local">{t("models.backend_local")}</option>
              <option value="provider" disabled={!providers.length}>{t("models.backend_provider")}</option>
            </select>
          </div>
          {backend === "local" ? (
            <div className="fc-field">
              <label className="fc-field-label" htmlFor="embedding-model">{t("models.embeddingModel")}</label>
              <select id="embedding-model" className="fc-input" value={model} onChange={(event) => setModel(event.target.value)}>
                {LOCAL_MODELS.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            </div>
          ) : (
            <>
              <div className="fc-field">
                <label className="fc-field-label" htmlFor="embedding-provider">{t("models.tierProvider")}</label>
                <select id="embedding-provider" className="fc-input" value={providerId} onChange={(event) => setProviderId(event.target.value)}>
                  {providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}
                </select>
              </div>
              <TextField label={t("models.embeddingModel")} value={model} onChange={(event) => setModel(event.target.value)} />
              <TextField label={t("models.dimensions")} inputMode="numeric" value={dimensions} onChange={(event) => setDimensions(event.target.value)} />
            </>
          )}
          <Button size="sm" disabled={!model || (backend === "local" && view.backend === "local" && model === view.model)}
            onClick={() => setConfirming(true)}>{t("models.changeEmbedding")}</Button>
        </div>
        {error ? <WarningBanner tone="danger">{error}</WarningBanner> : null}
      </div>
      <Dialog open={confirming} title={t("models.reindexTitle")} onClose={() => setConfirming(false)}
        actions={
          <>
            <Button onClick={() => setConfirming(false)}>{t("models.cancel")}</Button>
            <Button variant="primary" onClick={() => void change()}>{t("models.changeEmbedding")}</Button>
          </>
        }>
        {t("models.reindexText")}
      </Dialog>
    </section>
  );
}

function ClassifierCard({ models, status, onSaved }: { models: Models; status: ClassifierStatus; onSaved: (text: string) => Promise<void> }) {
  const { t } = useI18n();
  const [error, setError] = useState<string | null>(null);
  async function toggle() {
    try {
      await models.setClassifier(!status.enabled);
      setError(null);
      await onSaved(status.enabled ? t("models.turnOff") : t("models.turnOn"));
    } catch (cause) {
      setError(t("models.failed", { reason: message(cause) }));
    }
  }
  return (
    <section className="fc-card" aria-label={t("models.classifier")}>
      <div className="fc-card-head"><h2 className="fc-card-title">{t("models.classifier")}</h2></div>
      <div className="fc-card-body fc-stack" style={{ gap: "var(--base-size-12)" }}>
        <p style={{ margin: 0 }}>{status.enabled ? t("models.classifierOn") : t("models.classifierOff")}</p>
        {!status.model_present ? <WarningBanner tone="info">{t("models.classifierMissing", { command: FETCH_COMMAND })}</WarningBanner> : null}
        <div>
          <Button size="sm" disabled={!status.enabled && !status.model_present} onClick={() => void toggle()}>
            {status.enabled ? t("models.turnOff") : t("models.turnOn")}
          </Button>
        </div>
        {error ? <WarningBanner tone="danger">{error}</WarningBanner> : null}
      </div>
    </section>
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
  const [removing, setRemoving] = useState<ProviderView | null>(null);
  const [error, setError] = useState<string | null>(null);

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
      setError(t("models.failed", { reason: message(cause) }));
    }
  }

  return (
    <ListPage section="models" loading={!data} failed={failed} skeleton="page">
      {error ? <WarningBanner tone="danger">{error}</WarningBanner> : null}
      {data ? (
        <>
          <section className="fc-card" aria-label={t("models.providers")}>
            <div className="fc-card-head"><h2 className="fc-card-title">{t("models.providers")}</h2></div>
            <div className="fc-card-body fc-stack" style={{ gap: "var(--base-size-16)" }}>
              {data.providers.length ? (
                <ul className="fc-stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: "var(--base-size-16)" }}>
                  {data.providers.map((provider) => (
                    <ProviderRow key={provider.id} models={models} provider={provider} onChanged={changed} onRemove={() => setRemoving(provider)} />
                  ))}
                </ul>
              ) : <WarningBanner tone="info">{t("models.noProviders")}</WarningBanner>}
              <ProviderForm models={models} onAdded={(provider) => void changed(t("models.added", { name: provider.name }))} />
            </div>
          </section>
          <h2 style={{ margin: 0 }}>{t("models.tiers")}</h2>
          <div className="fc-role-grid">
            {data.tiers.tiers.map((tier) => (
              <TierRow key={`${tier.tier}-${tier.provider_id}-${tier.model}`} models={models} tier={tier} providers={data.providers} onSaved={changed} />
            ))}
          </div>
          <EmbeddingCard key={`${data.tiers.embedding.backend}-${data.tiers.embedding.model}`} models={models}
            view={data.tiers.embedding} providers={data.providers} onSaved={changed} />
          <ClassifierCard models={models} status={data.classifier} onSaved={changed} />
        </>
      ) : null}
      <Dialog open={!!removing} title={t("models.removeTitle", { name: removing?.name ?? "" })} onClose={() => setRemoving(null)}
        actions={
          <>
            <Button onClick={() => setRemoving(null)}>{t("models.cancel")}</Button>
            <Button variant="primary" onClick={() => void remove()}>{t("models.remove")}</Button>
          </>
        }>
        {t("models.removeText")}
      </Dialog>
    </ListPage>
  );
}
