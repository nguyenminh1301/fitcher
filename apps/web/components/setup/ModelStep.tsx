"use client";

// The setup's Models step (DECISIONS §2, §15). "Check the key" adds the chosen provider and tests it at once.
// A provider that proposes no model for the tiers (an OpenAI-compatible service or server) first asks which of
// its models to use, then tests that one. A failed check removes the provider again and says why under the
// field, so the next try starts clean; "Change provider" does the same after a success. A model that answers
// without structured output stays usable, with a warning.

import { useEffect, useState, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { ModelChooser } from "@/components/models/ModelChooser";
import { billing, presetById, presetIncomplete, providerCreate } from "@/components/models/presets";
import { presetName, ProviderPicker } from "@/components/models/ProviderPicker";
import { StepHead } from "@/components/setup/SetupShell";
import type { FitcherApi } from "@/lib/api/client";
import { errorText } from "@/lib/api/errorText";
import type { ModelTiersView, ProviderTestResult, ProviderView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

type Phase =
  | { kind: "form" }
  | { kind: "choose"; provider: ProviderView; tiers: string[] }
  | { kind: "done"; provider: ProviderView; tiers: ModelTiersView | null; warning?: string };

class CheckFailed extends Error {}

export function ModelStep({ models, meta, onNext, onSkip, disabled = false }: {
  models: FitcherApi["models"];
  /** The "Step 1 of 3" line under the footer. */
  meta: ReactNode;
  /** Go on to the Data step; adding a provider already answered this one. */
  onNext: () => void;
  onSkip: () => void;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  // OpenRouter is chosen first: it has free models, so a first setup costs nothing.
  const [presetId, setPresetId] = useState("openrouter");
  const [apiKey, setApiKey] = useState("");
  const [address, setAddress] = useState("");
  const [providerName, setProviderName] = useState("");
  const [phase, setPhase] = useState<Phase>({ kind: "form" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const preset = presetById(presetId);
  const name = presetName(preset, t);
  // Each phase starts at the top of the page, like a new step.
  useEffect(() => { document.scrollingElement?.scrollTo?.({ top: 0 }); }, [phase.kind]);

  function choose(id: string) {
    setPresetId(id);
    setAddress(presetById(id).suggestedUrl ?? "");
    setError(null);
  }

  // The outcome of a test call: done (with a warning when the model gave no structured output) or a failure.
  function outcome(result: ProviderTestResult): string | undefined {
    if (result.structured_output) return undefined;
    if (result.model && result.models.length) return t("onboarding.noStructured", { model: result.model, reason: result.error ?? "" });
    throw new CheckFailed(result.error ?? t("onboarding.noReply"));
  }

  async function check() {
    setBusy(true);
    setError(null);
    let provider: ProviderView | null = null;
    try {
      provider = await models.addProvider(providerCreate(preset, apiKey, address, providerName));
      const tiers = await models.tiers();
      const proposed = tiers.tiers.some((tier) => tier.provider_id === provider?.id && tier.model);
      if (!proposed) {
        setPhase({ kind: "choose", provider, tiers: tiers.tiers.map((tier) => tier.tier) });
        return;
      }
      const warning = outcome(await models.testProvider(provider.id));
      setApiKey("");
      setPhase({ kind: "done", provider, tiers, warning });
    } catch (cause) {
      if (provider) await models.removeProvider(provider.id).catch(() => undefined);
      setError(cause instanceof CheckFailed ? cause.message : errorText(cause));
    } finally {
      setBusy(false);
    }
  }

  async function chosen(provider: ProviderView, model: string) {
    try {
      const warning = outcome(await models.testProvider(provider.id, model));
      setApiKey("");
      setPhase({ kind: "done", provider, tiers: await models.tiers().catch(() => null), warning });
    } catch (cause) {
      throw new Error(t("onboarding.testFailed", { reason: cause instanceof Error ? cause.message : String(cause) }));
    }
  }

  async function changeProvider(provider: ProviderView) {
    setBusy(true);
    await models.removeProvider(provider.id).catch(() => undefined);
    setBusy(false);
    setError(null);
    setPhase({ kind: "form" });
  }

  if (phase.kind === "choose") {
    return (
      <>
        <StepHead icon={<Icon name="cpu" size="xl" />} title={t("onboarding.chooseTitle")}>{t("onboarding.chooseSub", { name: phase.provider.name })}</StepHead>
        <ModelChooser setup models={models} provider={phase.provider} tiers={phase.tiers} meta={meta}
          onChosen={(model) => chosen(phase.provider, model)} onLater={onNext} />
      </>
    );
  }

  if (phase.kind === "done") {
    return (
      <>
        <StepHead icon={<Icon name="check" size="xl" />} tone="success" title={t("onboarding.connected", { name: phase.provider.name })}>
          {t("onboarding.connectedSub")}
        </StepHead>
        {phase.warning ? (
          <div className="fc-banner fc-banner-attention" role="status"><Icon name="alert" /><div>{phase.warning}</div></div>
        ) : null}
        {phase.tiers ? (
          <div className="box">
            <table className="tbl">
              <caption className="fc-sr">{t("onboarding.tierCaption")}</caption>
              <thead><tr><th>{t("onboarding.tierTask")}</th><th>{t("onboarding.tierModel")}</th></tr></thead>
              <tbody>
                {phase.tiers.tiers.map((tier) => (
                  <tr key={tier.tier}>
                    <td><span>{t(`onboarding.tier_${tier.tier}`)}</span> <span className="fc-mono fc-muted">{tier.tier}</span></td>
                    <td>{tier.model ? <span className="fc-mono">{tier.model}</span> : <span className="fc-muted">{t("onboarding.noModel")}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <div className="ob-foot">
          <button type="button" className="fc-btn fc-btn-primary fc-btn-xl fc-btn-block" disabled={busy} onClick={onNext}>{t("onboarding.toData")}</button>
          <div><button type="button" className="fc-textlink" disabled={busy} onClick={() => void changeProvider(phase.provider)}>{t("onboarding.changeProvider")}</button></div>
          {meta}
        </div>
      </>
    );
  }

  const usesKey = preset.key === "required";
  const cost = billing(preset);
  return (
    <>
      <StepHead icon={<Icon name="cpu" size="xl" />} title={t("onboarding.modelTitle")}>{t("onboarding.modelSub")}</StepHead>
      <ProviderPicker presetId={presetId} onPreset={choose} apiKey={apiKey} onApiKey={setApiKey} address={address} onAddress={setAddress}
        name={providerName} onName={setProviderName} error={error} disabled={busy || disabled} />
      <div className="ob-foot">
        <button type="button" className="fc-btn fc-btn-primary fc-btn-xl fc-btn-block" aria-busy={busy || undefined}
          disabled={busy || disabled || presetIncomplete(preset, apiKey, address, providerName)} onClick={() => void check()}>
          {busy ? <span className="fc-spin fc-spinning" aria-hidden="true" /> : null}
          {busy ? t(usesKey ? "onboarding.testingKey" : "onboarding.testingConnection") : t(usesKey ? "onboarding.testKey" : "onboarding.testConnection")}
        </button>
        {cost === "billed" ? <p className="ob-meta">{t("onboarding.paidCheck", { name })}</p> : null}
        {cost === "maybe" ? <p className="ob-meta">{t("onboarding.paidCheckOther")}</p> : null}
        <div><button type="button" className="fc-textlink" disabled={busy || disabled} onClick={onSkip}>{t("onboarding.later")}</button></div>
        {meta}
      </div>
    </>
  );
}
