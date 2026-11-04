"use client";

// Models (DECISIONS §2 Model tiers, §15): each model tier with its catalog alias, provider and the eval
// report that made the alias eligible. An admin maps a chat tier to another alias the gateway loaded; an
// alias whose latest eval report did not pass without regression is disabled, with the reason beside it.
// embed is shown but never changed here, because a new embedding model needs a full reindex.

import { useCallback, useState } from "react";

import { useConsole } from "@/components/console/ConsoleLayout";
import { ListPage } from "@/components/console/ListPage";
import { Button, Chip } from "@/components/ui/controls";
import { StatusPill, WarningBanner } from "@/components/ui/feedback";
import { Dialog } from "@/components/ui/overlay";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import type { AliasOption, ModelTier } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

type Change = { tier: ModelTier; option: AliasOption };

function TierCard({ tier, onChoose }: { tier: ModelTier; onChoose: (option: AliasOption) => void }) {
  const { t, formatDate } = useI18n();
  const options = tier.options ?? [];
  const blocked = options.filter((option) => !option.eligible && option.alias !== tier.alias);
  return (
    <section className="fc-card" aria-label={t("ui.tierLabel", { tier: tier.tier })}>
      <div className="fc-card-head">
        <h2 className="fc-card-title fc-mono">{tier.tier}</h2>
        <span style={{ marginRight: "var(--base-size-8)" }}>
          <StatusPill status={tier.eligible ? "eligible" : "ineligible"} />
        </span>
      </div>
      <div className="fc-card-body fc-stack" style={{ gap: "var(--base-size-12)" }}>
        <p style={{ margin: 0 }}>{t(`ui.tierDesc_${tier.tier.replace(/-/g, "_")}`)}</p>
        <dl className="fc-kv fc-kv-stack">
          <dt>{t("ui.currentAlias")}</dt>
          <dd><code className="fc-code">{tier.alias}</code> <span className="fc-muted">{tier.provider}</span></dd>
          <dt>{t("ui.defaultAlias")}</dt>
          <dd><code className="fc-code">{tier.default_alias}</code></dd>
          <dt>{t("ui.eligibility")}</dt>
          <dd>
            {tier.reason}
            {tier.report_id ? (
              <span className="fc-muted"> · {t("ui.evalReportRef", { id: tier.report_id, date: tier.report_ts ? formatDate(tier.report_ts) : "—" })}</span>
            ) : null}
          </dd>
        </dl>
        {tier.editable ? (
          <>
            <div className="fc-row" role="group" aria-label={t("ui.aliasesFor", { tier: tier.tier })} style={{ gap: "var(--base-size-4)" }}>
              {options.map((option) => (
                <Chip key={option.alias} size="sm" selected={option.alias === tier.alias}
                  disabled={!option.eligible || option.alias === tier.alias} title={option.reason}
                  onClick={() => onChoose(option)}>
                  {option.alias}
                </Chip>
              ))}
            </div>
            {blocked.length ? (
              <ul className="fc-muted" aria-label={t("ui.ineligibleAliases")} style={{ margin: 0, paddingLeft: "var(--base-size-16)" }}>
                {blocked.map((option) => <li key={option.alias}><code className="fc-code">{option.alias}</code>: {option.reason}</li>)}
              </ul>
            ) : null}
          </>
        ) : (
          <WarningBanner tone="info">{t("ui.embedLocked")}</WarningBanner>
        )}
      </div>
    </section>
  );
}

export function ModelsSection() {
  const { t } = useI18n();
  const { api } = useChat();
  const { toast } = useConsole();
  const { data, failed, reload } = useLoad(useCallback(() => api.models.list(), [api]));
  const [change, setChange] = useState<Change | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    const pending = change;
    setChange(null);
    if (!pending) return;
    try {
      await api.models.set(pending.tier.tier, pending.option.alias);
      setError(null);
      toast(t("ui.tierChanged", { tier: pending.tier.tier, alias: pending.option.alias }));
    } catch (refused) {
      setError(refused instanceof Error ? refused.message : String(refused));
    }
    await reload();
  }

  return (
    <ListPage section="models" loading={!data} failed={failed} skeleton="page">
      <WarningBanner tone="info">{t("ui.modelsNote")}</WarningBanner>
      {data?.catalog_error ? <WarningBanner tone="warning">{t("ui.catalogUnavailable", { reason: data.catalog_error })}</WarningBanner> : null}
      {error ? <WarningBanner tone="danger">{error}</WarningBanner> : null}
      <div className="fc-role-grid">
        {(data?.tiers ?? []).map((tier) => (
          <TierCard key={tier.tier} tier={tier} onChoose={(option) => setChange({ tier, option })} />
        ))}
      </div>
      <Dialog open={!!change} title={t("ui.changeTierTitle", { tier: change?.tier.tier ?? "" })} onClose={() => setChange(null)}
        actions={
          <>
            <Button onClick={() => setChange(null)}>{t("ui.cancel")}</Button>
            <Button variant="primary" onClick={() => void confirm()}>{t("ui.changeTier")}</Button>
          </>
        }>
        {t("ui.changeTierText", { tier: change?.tier.tier ?? "", from: change?.tier.alias ?? "", to: change?.option.alias ?? "" })}
      </Dialog>
    </ListPage>
  );
}
