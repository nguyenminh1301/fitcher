"use client";

// Choosing the chain of models a chat task tries in order (DECISIONS §2). The picker reads every provider's
// catalog, keeps chat models only, and lets the owner search, keep one provider, keep free models or models known
// to answer in a JSON schema. Each model shows its price, context, measured speed and benchmark; the models that
// suit the task best are marked as recommended, from the same ranking as the automatic choice. The chain is
// ordered: the first model answers, the next ones answer when it is slow, limited, out of quota or down.

import { useEffect, useMemo, useState, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { Chip } from "@/components/ui/controls";
import { Dialog } from "@/components/ui/overlay";
import type { FitcherApi } from "@/lib/api/client";
import { errorText } from "@/lib/api/errorText";
import type { CatalogEntry, ProviderView, TierChange, TierView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";
import {
  contextText, filtered, key, NO_FILTER, priceText, QUICK_TIERS, recommended, speedText, type ModelFilter,
} from "@/lib/models/recommend";

/** The longest chain the api takes. */
export const MAX_CHAIN = 6;

type Models = FitcherApi["models"];
type ChainLink = NonNullable<TierChange["chain"]>[number];

/** Every provider's catalog, read once per page; a provider that cannot list its models adds none. */
export function useCatalogs(models: Models, providers: ProviderView[]): { entries: CatalogEntry[] | null; failed: string[] } {
  const [state, setState] = useState<{ entries: CatalogEntry[] | null; failed: string[] }>({ entries: null, failed: [] });
  const ids = providers.map((provider) => provider.id).join(",");
  useEffect(() => {
    let live = true;
    const list = ids ? ids.split(",") : [];
    Promise.allSettled(list.map((id) => models.catalog(id))).then((replies) => {
      if (!live) return;
      const entries: CatalogEntry[] = [];
      const failed: string[] = [];
      replies.forEach((reply, index) => {
        if (reply.status === "fulfilled") entries.push(...reply.value.models);
        else failed.push(list[index]);
      });
      setState({ entries, failed });
    });
    return () => { live = false; };
  }, [models, ids]);
  return state;
}

function providerName(providers: ProviderView[], id: string): string {
  return providers.find((provider) => provider.id === id)?.name ?? id;
}

function FreeLabel({ model }: { model: CatalogEntry }) {
  const { t } = useI18n();
  if (model.free === "free") return <span className="fc-label fc-label-success">{t("modelPicker.free")}</span>;
  if (model.free === "free_tier") return <span className="fc-label fc-label-success">{t("modelPicker.freeTier")}</span>;
  const price = priceText(model);
  return price ? <span className="fc-label" title={t("modelPicker.priceHelp")}>{price}</span> : <span className="fc-label">{t("modelPicker.paid")}</span>;
}

/** One model's facts in a line: what it costs, its context, measured speed, JSON answers and benchmark. */
export function ModelFacts({ model, best }: { model: CatalogEntry; best?: boolean }) {
  const { t } = useI18n();
  const context = contextText(model);
  const speed = speedText(model);
  return (
    <span className="mp-facts">
      {best ? <span className="fc-label fc-label-accent"><Icon name="sparkles" />{t("modelPicker.recommended")}</span> : null}
      <FreeLabel model={model} />
      {context ? <span className="fc-label" title={t("modelPicker.contextHelp")}>{t("modelPicker.context", { size: context })}</span> : null}
      {speed ? <span className="fc-label" title={t("modelPicker.speedHelp")}>{t("modelPicker.speed", { seconds: speed })}</span> : null}
      {model.structured_output === true ? <span className="fc-label" title={t("modelPicker.jsonHelp")}>{t("modelPicker.json")}</span> : null}
      {model.benchmark !== null ? <span className="fc-label" title={t("modelPicker.benchmarkHelp")}>{t("modelPicker.benchmark", { score: Math.round(model.benchmark) })}</span> : null}
    </span>
  );
}

/** The dialog that builds a task's chain. */
export function TierChainDialog({ models, tier, providers, entries, onClose, onSaved }: {
  models: Models; tier: TierView; providers: ProviderView[]; entries: CatalogEntry[];
  onClose: () => void; onSaved: (text: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const [chain, setChain] = useState<ChainLink[]>(() => tier.chain?.length
    ? tier.chain
    : tier.provider_id && tier.model ? [{ provider_id: tier.provider_id, model: tier.model }] : []);
  const [filter, setFilter] = useState<ModelFilter>(NO_FILTER);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const best = useMemo(() => recommended(tier.tier, entries), [tier.tier, entries]);
  const shown = useMemo(() => filtered(tier.tier, entries, filter), [tier.tier, entries, filter]);
  const inChain = new Set(chain.map(key));
  const byKey = useMemo(() => new Map(entries.map((entry) => [key(entry), entry])), [entries]);

  function move(index: number, step: number) {
    setChain((links) => {
      const next = [...links];
      const [link] = next.splice(index, 1);
      next.splice(index + step, 0, link);
      return next;
    });
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await models.setTier(tier.tier, { chain });
      await onSaved(t("modelPicker.saved", { tier: t(`onboarding.tier_${tier.tier}`), count: chain.length }));
      onClose();
    } catch (cause) {
      setError(errorText(cause));
      setBusy(false);
    }
  }

  const set = (change: Partial<ModelFilter>) => setFilter((current) => ({ ...current, ...change }));
  return (
    <Dialog open wide title={t("modelPicker.title", { tier: t(`onboarding.tier_${tier.tier}`) })} closeLabel={t("common.close")} onClose={onClose}
      actions={<>
        <span className="fc-muted dlg-status">{t("modelPicker.manualNote")}</span>
        <button type="button" className="fc-btn" onClick={onClose}>{t("common.cancel")}</button>
        <button type="button" className="fc-btn fc-btn-primary" disabled={busy || !chain.length} onClick={() => void save()}>
          {busy ? <span className="fc-spin fc-spinning" aria-hidden="true" /> : null}{t("modelPicker.save")}
        </button>
      </>}>
      <p className="fc-muted" style={{ margin: 0 }}>{t(`modelPicker.advice_${QUICK_TIERS.has(tier.tier) ? "quick" : "sql"}`)}</p>
      <section aria-label={t("modelPicker.chainTitle")}>
        <h3 className="mp-heading">{t("modelPicker.chainTitle")}</h3>
        {chain.length ? (
          <ol className="mp-chain">
            {chain.map((link, index) => {
              const entry = byKey.get(key(link));
              return (
                <li key={key(link)} className="mp-link">
                  <span className="mp-order">{index + 1}</span>
                  <span className="mp-name">
                    <span className="fc-mono">{link.model}</span>
                    <span className="fc-muted"> · {providerName(providers, link.provider_id)}{index === 0 ? ` · ${t("modelPicker.answersFirst")}` : ` · ${t("modelPicker.fallback")}`}</span>
                  </span>
                  {entry ? <ModelFacts model={entry} /> : null}
                  <span className="mp-actions">
                    <button type="button" className="fc-btn fc-btn-ghost fc-btn-icon fc-btn-sm" aria-label={t("modelPicker.up", { model: link.model })}
                      disabled={index === 0} onClick={() => move(index, -1)}><Icon name="chevronUp" /></button>
                    <button type="button" className="fc-btn fc-btn-ghost fc-btn-icon fc-btn-sm" aria-label={t("modelPicker.down", { model: link.model })}
                      disabled={index === chain.length - 1} onClick={() => move(index, 1)}><Icon name="chevronDown" /></button>
                    <button type="button" className="fc-btn fc-btn-ghost fc-btn-icon fc-btn-sm" aria-label={t("modelPicker.remove", { model: link.model })}
                      onClick={() => setChain((links) => links.filter((_, at) => at !== index))}><Icon name="x" /></button>
                  </span>
                </li>
              );
            })}
          </ol>
        ) : <p className="fc-muted" style={{ margin: 0 }}>{t("modelPicker.chainEmpty")}</p>}
      </section>
      <section aria-label={t("modelPicker.allModels")}>
        <h3 className="mp-heading">{t("modelPicker.allModels")}</h3>
        <div className="mp-filters">
          <div className="fc-input-wrap" style={{ flex: "1 1 220px" }}>
            <Icon name="search" />
            <input className="fc-input fc-input-sm" placeholder={t("modelPicker.search")} aria-label={t("modelPicker.search")}
              value={filter.search} onChange={(event) => set({ search: event.target.value })} />
          </div>
          <div className="sel">
            <select className="fc-input fc-input-sm" aria-label={t("modelPicker.provider")} value={filter.providerId}
              onChange={(event) => set({ providerId: event.target.value })}>
              <option value="">{t("modelPicker.everyProvider")}</option>
              {providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.name}</option>)}
            </select>
            <Icon name="chevronDown" />
          </div>
          <Chip size="sm" selected={filter.freeOnly} onClick={() => set({ freeOnly: !filter.freeOnly })}>{t("modelPicker.freeOnly")}</Chip>
          <Chip size="sm" selected={filter.structuredOnly} onClick={() => set({ structuredOnly: !filter.structuredOnly })}>{t("modelPicker.jsonOnly")}</Chip>
        </div>
        <p className="fc-field-help" style={{ margin: "8px 0" }}>{t("modelPicker.count", { shown: shown.length, total: entries.filter((entry) => entry.kind === "chat").length })}</p>
        <ul className="mp-list" aria-label={t("modelPicker.allModels")}>
          {shown.slice(0, 200).map((model) => {
            const id = key(model);
            const added = inChain.has(id);
            return (
              <li key={id} className="mp-row">
                <span className="mp-name">
                  <span className="fc-mono">{model.id}</span>
                  <span className="fc-muted"> · {providerName(providers, model.provider_id)}</span>
                </span>
                <ModelFacts model={model} best={best.has(id)} />
                <button type="button" className="fc-btn fc-btn-sm" disabled={added || chain.length >= MAX_CHAIN}
                  aria-label={t("modelPicker.addTo", { model: model.id })}
                  onClick={() => setChain((links) => [...links, { provider_id: model.provider_id, model: model.id }])}>
                  {added ? <><Icon name="check" />{t("modelPicker.added")}</> : <><Icon name="plus" />{t("modelPicker.add")}</>}
                </button>
              </li>
            );
          })}
        </ul>
        {shown.length > 200 ? <p className="fc-field-help">{t("modelPicker.more", { count: shown.length - 200 })}</p> : null}
      </section>
      {error ? <span className="fc-field-error" role="alert"><Icon name="alert" />{error}</span> : null}
    </Dialog>
  );
}

/** A task's row on the Models page: what it does, the chain it tries, and the button that changes it. */
export function TierChainRow({ tier, providers, entries, onChange, extra }: {
  tier: TierView; providers: ProviderView[]; entries: CatalogEntry[] | null; onChange: () => void;
  /** Shown next to the task's name, such as the latest evaluation. */
  extra?: ReactNode;
}) {
  const { t } = useI18n();
  const chain = tier.chain?.length ? tier.chain : tier.provider_id && tier.model ? [{ provider_id: tier.provider_id, model: tier.model }] : [];
  const byKey = new Map((entries ?? []).map((entry) => [key(entry), entry]));
  return (
    <li className="mp-tier" aria-label={t(`onboarding.tier_${tier.tier}`)}>
      <div className="mp-tier-head">
        <div>
          <div className="mp-tier-name">{t(`onboarding.tier_${tier.tier}`)} <span className="fc-mono fc-muted">{tier.tier}</span> {extra}</div>
          <div className="fc-muted mp-tier-help">{t(`modelPicker.does_${tier.tier}`)}</div>
        </div>
        <button type="button" className="fc-btn fc-btn-sm" onClick={onChange} disabled={entries === null}
          aria-label={t("modelPicker.changeFor", { tier: t(`onboarding.tier_${tier.tier}`) })}>
          {entries === null ? <span className="fc-spin fc-spinning" aria-hidden="true" /> : <Icon name="pencil" />}{t("modelPicker.change")}
        </button>
      </div>
      {chain.length ? (
        <ol className="mp-chain mp-chain-compact">
          {chain.map((link, index) => {
            const entry = byKey.get(key(link));
            return (
              <li key={key(link)} className="mp-link">
                <span className="mp-order">{index + 1}</span>
                <span className="mp-name">
                  <span className="fc-mono">{link.model}</span>
                  <span className="fc-muted"> · {providerName(providers, link.provider_id)}</span>
                </span>
                {entry ? <ModelFacts model={entry} /> : null}
              </li>
            );
          })}
        </ol>
      ) : <p className="fc-muted" style={{ margin: 0 }}>{t("modelPicker.noModel")}</p>}
    </li>
  );
}
