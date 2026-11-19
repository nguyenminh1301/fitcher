"use client";

// The provider list of the setup's Models step (DECISIONS §2, §15) as radio cards. The five most used
// providers show first; the rest open under "More providers", grouped as model services, servers on this
// computer and any other OpenAI-compatible endpoint. The chosen card opens its fields underneath: a key with
// a link to the page that creates it, the address of a server, and OpenRouter's note on free models.

import { useId, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { asksAddress, asksName, PRESETS, presetById, type ProviderPreset } from "@/components/models/presets";
import { ProviderLogo } from "@/components/models/ProviderLogo";
import { useI18n } from "@/lib/i18n/react";

const MAIN = ["openai", "anthropic", "gemini", "openrouter", "ollama"];
const MORE_GROUPS = ["service", "local", "other"] as const;

/** The card title of a preset; the api's kinds and the two generic presets are named in the interface language. */
export function presetName(preset: ProviderPreset, t: (key: string) => string): string {
  if (preset.id === "ollama") return t("onboarding.ollamaName");
  if (preset.id === "openai_compatible") return t("onboarding.otherName");
  return preset.name ?? t(`models.kind_${preset.kind}`);
}

function description(preset: ProviderPreset): string {
  if (preset.id === "openai" || preset.id === "anthropic") return "desc_billed";
  if (preset.id === "gemini") return "desc_gemini";
  if (preset.id === "openrouter") return "desc_openrouter";
  if (preset.id === "ollama") return "desc_ollama";
  return `desc_${preset.group}`;
}

type Props = {
  presetId: string;
  onPreset: (id: string) => void;
  apiKey: string;
  onApiKey: (value: string) => void;
  address: string;
  onAddress: (value: string) => void;
  /** The name the person gives an endpoint of their own; the presets of known services are named already. */
  name?: string;
  onName?: (value: string) => void;
  /** Why the last check failed, said under the key or address field. */
  error?: string | null;
  disabled?: boolean;
};

export function ProviderPicker({ presetId, onPreset, apiKey, onApiKey, address, onAddress, name, onName, error, disabled }: Props) {
  const { t } = useI18n();
  const chosen = presetById(presetId);
  const [more, setMore] = useState(!MAIN.includes(chosen.id));

  const card = (preset: ProviderPreset) => {
    const selected = preset.id === chosen.id;
    const button = (
      <button key={preset.id} type="button" className="opt" role="radio" aria-checked={selected} disabled={disabled}
        onClick={() => onPreset(preset.id)}>
        <span className="opt-icon"><ProviderLogo preset={preset} /></span>
        <span className="opt-body">
          <span className="opt-title">{presetName(preset, t)}</span>
          <span className="opt-desc">{t(`onboarding.${description(preset)}`)}</span>
        </span>
        {preset.id === "openrouter" ? <span className="fc-label fc-label-success">{t("onboarding.freeBadge")}</span> : null}
        <span className="opt-radio">{selected ? <Icon name="check" /> : null}</span>
      </button>
    );
    if (!selected) return button;
    return (
      <div key={preset.id} className="opt-group">
        {button}
        <div className="opt-more"><Fields preset={preset} apiKey={apiKey} onApiKey={onApiKey} address={address} onAddress={onAddress} name={name} onName={onName} error={error} disabled={disabled} /></div>
      </div>
    );
  };

  return (
    <div className="opt-list" role="radiogroup" aria-label={t("onboarding.providers")}>
      {MAIN.map((id) => card(presetById(id)))}
      <button type="button" className="fc-textlink" aria-expanded={more} onClick={() => setMore(!more)} style={{ alignSelf: "flex-start" }}>
        <Icon name={more ? "chevronUp" : "chevronDown"} />{more ? t("onboarding.fewerProviders") : t("onboarding.moreProviders")}
      </button>
      {more ? MORE_GROUPS.map((group) => (
        <div key={group} className="fc-field" role="group" aria-label={t(`onboarding.group_${group}`)}>
          <span className="fc-field-label">{t(`onboarding.group_${group}`)}</span>
          <span className="fc-field-help">{t(`onboarding.groupHelp_${group}`)}</span>
          <div className="opt-list">
            {PRESETS.filter((preset) => preset.group === group && !MAIN.includes(preset.id)).map(card)}
          </div>
        </div>
      )) : null}
    </div>
  );
}

function Fields({ preset, apiKey, onApiKey, address, onAddress, name, onName, error, disabled }: Omit<Props, "presetId" | "onPreset"> & { preset: ProviderPreset }) {
  const { t } = useI18n();
  const id = useId();
  const nameId = `${id}-name`;
  const keyId = `${id}-key`;
  const addressId = `${id}-address`;
  const errorId = `${id}-error`;
  const address_ = asksAddress(preset);
  const errorLine = error ? <span className="fc-field-error" id={errorId} role="alert"><Icon name="alert" />{t("onboarding.testFailed", { reason: error })}</span> : null;
  return (
    <>
      {onName && asksName(preset) ? (
        <div className="fc-field">
          <label className="fc-field-label" htmlFor={nameId}>{preset.group === "other" ? t("onboarding.providerName") : t("onboarding.providerNameOptional")}</label>
          <input id={nameId} className="fc-input" type="text" value={name ?? ""} maxLength={60} disabled={disabled}
            placeholder={preset.group === "other" ? t("onboarding.providerNamePlaceholder") : presetName(preset, t)}
            aria-describedby={`${nameId}-help`} onChange={(event) => onName(event.target.value)} />
          <span className="fc-field-help" id={`${nameId}-help`}>{t("onboarding.providerNameHelp")}</span>
        </div>
      ) : null}
      {address_ ? (
        <div className="fc-field">
          <label className="fc-field-label" htmlFor={addressId}>{t("onboarding.address")}</label>
          <input id={addressId} className="fc-input" type="text" value={address} placeholder={preset.suggestedUrl ?? "https://"} spellCheck={false}
            disabled={disabled} aria-invalid={error && preset.key === "none" ? true : undefined}
            aria-describedby={`${addressId}-help${error && preset.key === "none" ? ` ${errorId}` : ""}`}
            onChange={(event) => onAddress(event.target.value)} />
          <span className="fc-field-help" id={`${addressId}-help`}>{t("onboarding.addressHelp")}</span>
          {preset.key === "none" ? errorLine : null}
        </div>
      ) : null}
      {preset.key === "none" ? null : (
        <div className="fc-field">
          <div className="field-head">
            <label className="fc-field-label" htmlFor={keyId}>{preset.key === "required" ? t("onboarding.apiKey") : t("onboarding.apiKeyOptional")}</label>
            {preset.keyUrl ? (
              <a href={preset.keyUrl} target="_blank" rel="noopener noreferrer" className="field-link">
                {t("onboarding.getKey", { name: presetName(preset, t) })}<Icon name="externalLink" /><span className="fc-sr">{t("onboarding.newTab")}</span>
              </a>
            ) : null}
          </div>
          <div className="fc-input-wrap">
            <Icon name="key" />
            <input id={keyId} className="fc-input" type="password" value={apiKey} placeholder={t("onboarding.keyPlaceholder")}
              autoComplete="off" spellCheck={false} disabled={disabled} aria-invalid={error ? true : undefined}
              aria-describedby={`${error ? `${errorId} ` : ""}${keyId}-help`} onChange={(event) => onApiKey(event.target.value)} />
          </div>
          {errorLine}
          <span className="fc-field-help" id={`${keyId}-help`}>{t("onboarding.keyHelp")}</span>
        </div>
      )}
      {preset.id === "openrouter" ? (
        <p className="fc-field-help" style={{ margin: 0 }}>{t("models.openRouterFreeNote")}</p>
      ) : null}
    </>
  );
}
