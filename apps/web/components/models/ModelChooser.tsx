"use client";

// Choosing the model of a provider that proposes none (an OpenAI-compatible service or server, DECISIONS §2):
// the provider's own model list, searchable, with only OpenRouter's free models shown by default. The chosen
// model answers every chat tier; each tier can be changed later on the Models page. In the setup the action
// sits in the step's footer with a way to choose later; on the Models page it is a plain button.

import { useEffect, useMemo, useState, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { FREE_SUFFIX, isOpenRouter } from "@/components/models/presets";
import type { FitcherApi } from "@/lib/api/client";
import { errorText } from "@/lib/api/errorText";
import type { ProviderView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

export function ModelChooser({ models, provider, tiers, onChosen, onLater, meta, setup = false }: {
  models: FitcherApi["models"];
  provider: ProviderView;
  /** The chat tiers the chosen model answers. */
  tiers: string[];
  /** Called once every tier uses the chosen model; it may run the provider's test and reject with its reason. */
  onChosen: (model: string) => void | Promise<void>;
  /** The setup's "Choose later". */
  onLater?: () => void;
  /** A line under the setup's footer, such as the step count. */
  meta?: ReactNode;
  setup?: boolean;
}) {
  const { t } = useI18n();
  const [listed, setListed] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const openRouter = isOpenRouter(provider.base_url);
  const [freeOnly, setFreeOnly] = useState(openRouter);
  const [search, setSearch] = useState("");
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    models.providerModels(provider.id)
      .then((reply) => setListed([...reply.models].sort()))
      .catch((cause) => setError(errorText(cause)));
  }, [models, provider.id]);

  const shown = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (listed ?? []).filter((name) => (!freeOnly || name.endsWith(FREE_SUFFIX)) && (!query || name.toLowerCase().includes(query)));
  }, [listed, freeOnly, search]);
  // The first model shown is chosen until another one is, so a filter that leaves one model is enough.
  useEffect(() => {
    if (!shown.includes(model)) setModel(shown[0] ?? "");
  }, [shown, model]);

  async function use() {
    setBusy(true);
    setError(null);
    try {
      for (const tier of tiers) await models.setTier(tier, { provider_id: provider.id, model });
      await onChosen(model);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }

  const action = (
    <button type="button" className={setup ? "fc-btn fc-btn-primary fc-btn-xl fc-btn-block" : "fc-btn fc-btn-primary"}
      disabled={busy || !model} aria-busy={busy || undefined} onClick={() => void use()}>
      {busy ? <span className="fc-spin fc-spinning" aria-hidden="true" /> : null}{t("onboarding.useModel")}
    </button>
  );
  return (
    <>
      <div className="box">
        <div className="box-head">
          <div className="fc-input-wrap" style={{ flex: 1 }}>
            <Icon name="search" />
            <input className="fc-input fc-input-sm" placeholder={t("onboarding.searchModels")} aria-label={t("onboarding.searchModels")}
              value={search} disabled={listed === null} onChange={(event) => setSearch(event.target.value)} />
          </div>
          {openRouter ? (
            <button type="button" className="chip" aria-pressed={freeOnly} onClick={() => setFreeOnly(!freeOnly)}>
              {freeOnly ? <Icon name="check" /> : null}{t("onboarding.freeOnly")}
            </button>
          ) : null}
        </div>
        {listed === null && !error ? (
          <>
            <div role="status" className="fc-muted chooser-loading"><span className="fc-spin fc-spinning" aria-hidden="true" />{t("onboarding.loadingModels")}</div>
            {[0, 1, 2, 3].map((row) => <div key={row} className="row-link"><span className="sk" /></div>)}
          </>
        ) : null}
        {listed && shown.length ? (
          <div role="radiogroup" aria-label={t("onboarding.model")} className="chooser-list">
            {shown.map((name) => (
              <label key={name} className="row-link">
                <input type="radio" name={`model-${provider.id}`} className="fc-check" checked={model === name} onChange={() => setModel(name)} />
                <span className="fc-mono">{name}</span>
              </label>
            ))}
          </div>
        ) : null}
        {listed && !shown.length ? (
          <div className="empty">
            <div className="empty-icon"><Icon name="searchX" size="lg" /></div>
            <p className="empty-title">{t("onboarding.noMatch")}</p>
            <p className="empty-text">{openRouter && freeOnly ? t("onboarding.noMatchFree") : t("onboarding.noMatchPlain")}</p>
          </div>
        ) : null}
        {listed ? <div className="pager"><span aria-live="polite">{t("onboarding.modelCount", { shown: shown.length, total: listed.length })}</span></div> : null}
      </div>
      {openRouter && freeOnly && !setup ? <p className="fc-field-help" style={{ margin: 0 }}>{t("guide.freeNote")}</p> : null}
      {error ? <span className="fc-field-error" role="alert"><Icon name="alert" />{error}</span> : null}
      {setup ? (
        <div className="ob-foot">
          {action}
          {onLater ? <div><button type="button" className="fc-textlink" onClick={onLater}>{t("onboarding.chooseLater")}</button></div> : null}
          {meta}
        </div>
      ) : <div>{action}</div>}
    </>
  );
}
