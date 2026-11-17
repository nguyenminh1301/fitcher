"use client";

// Adding a model provider (DECISIONS §2, §15), shared by the setup's Models step and the Models page. The
// person picks a provider from a curated list (presets.ts): a hosted provider or service takes a key, a model
// server on this computer takes its address, and any other OpenAI-compatible endpoint both. Each one links to
// the page where its key is created; OpenRouter also shows a short walkthrough. The key is sent once and never
// shown again: the api answers with its last four characters only.

import { useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { OpenRouterKeyGuide } from "@/components/models/KeyGuide";
import { PRESET_GROUPS, PRESETS, presetById } from "@/components/models/presets";
import { Button, TextField } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import type { FitcherApi } from "@/lib/api/client";
import { errorText } from "@/lib/api/errorText";
import type { ProviderCreate, ProviderTestResult, ProviderView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

const message = errorText;

export function ProviderForm({ models, onAdded }: { models: FitcherApi["models"]; onAdded: (provider: ProviderView) => void }) {
  const { t } = useI18n();
  const [presetId, setPresetId] = useState(PRESETS[0].id);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const preset = presetById(presetId);
  const asksUrl = !preset.baseUrl && preset.kind !== "openai" && preset.kind !== "anthropic" && preset.kind !== "gemini";
  const url = preset.baseUrl ?? baseUrl.trim();

  function choose(id: string) {
    setPresetId(id);
    setBaseUrl(presetById(id).suggestedUrl ?? "");
    setError(null);
  }

  async function add() {
    setBusy(true);
    setError(null);
    try {
      const body: ProviderCreate = { kind: preset.kind };
      if (preset.name) body.name = preset.name;
      if (apiKey && preset.key !== "none") body.api_key = apiKey;
      if (preset.baseUrl || asksUrl) body.base_url = url;
      const provider = await models.addProvider(body);
      setApiKey("");
      onAdded(provider);
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }

  const missing = (preset.key === "required" && !apiKey) || (asksUrl && !url);
  return (
    <form className="fc-stack" style={{ gap: "var(--base-size-12)" }} onSubmit={(event) => { event.preventDefault(); void add(); }}>
      <div className="fc-field">
        <label className="fc-field-label" htmlFor="provider-kind">{t("models.kind")}</label>
        <select id="provider-kind" className="fc-input" value={presetId} disabled={busy} onChange={(event) => choose(event.target.value)}>
          {PRESET_GROUPS.map((group) => (
            <optgroup key={group} label={t(`models.group_${group}`)}>
              {PRESETS.filter((option) => option.group === group).map((option) => (
                <option key={option.id} value={option.id}>{option.name ?? t(`models.kind_${option.kind}`)}</option>
              ))}
            </optgroup>
          ))}
        </select>
        <span className="fc-field-help">{t(`models.about_${preset.group}`)}</span>
      </div>
      {preset.id === "openrouter" ? <OpenRouterKeyGuide /> : null}
      {preset.key === "none" ? null : (
        <div className="fc-field">
          <TextField label={preset.key === "required" ? t("models.apiKey") : t("models.apiKeyOptional")} type="password" autoComplete="off"
            value={apiKey} disabled={busy} onChange={(event) => setApiKey(event.target.value)} />
          {preset.keyUrl ? (
            <a className="fc-field-help fc-link" href={preset.keyUrl} target="_blank" rel="noopener noreferrer">
              {t("models.getKey", { name: preset.name ?? t(`models.kind_${preset.kind}`) })} <Icon name="chevronRight" />
            </a>
          ) : null}
        </div>
      )}
      {asksUrl ? (
        <TextField label={t("models.baseUrl")} value={baseUrl} disabled={busy} help={t("models.hostHint")}
          placeholder={preset.suggestedUrl ?? "https://"} onChange={(event) => setBaseUrl(event.target.value)} />
      ) : null}
      {error ? <WarningBanner tone="danger">{error}</WarningBanner> : null}
      <div>
        <Button variant="primary" type="submit" disabled={busy || missing}>
          {busy ? t("models.adding") : t("models.add")}
        </Button>
      </div>
    </form>
  );
}

/** The outcome of a provider's test call; a model that fails structured output stays usable, with a warning. */
export function TestOutcome({ result }: { result: ProviderTestResult }) {
  const { t } = useI18n();
  if (result.structured_output) {
    return <WarningBanner tone="success">{t("models.testPassed", { model: result.model ?? "", count: result.models.length })}</WarningBanner>;
  }
  if (result.model && result.models.length) {
    return <WarningBanner tone="warning">{t("models.testNoStructured", { model: result.model, reason: result.error ?? "" })}</WarningBanner>;
  }
  return <WarningBanner tone="danger">{t("models.testFailed", { reason: result.error ?? "" })}</WarningBanner>;
}

/** Runs one provider's test call, labelled as billed for a hosted provider; `model` tests that model. */
export function ProviderTestButton({ models, provider, model, onResult }: {
  models: FitcherApi["models"];
  provider: ProviderView;
  model?: string;
  onResult: (result: ProviderTestResult | null, error?: string) => void;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    try {
      onResult(await (model ? models.testProvider(provider.id, model) : models.testProvider(provider.id)));
    } catch (cause) {
      onResult(null, message(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <span className="fc-row" style={{ gap: "var(--base-size-8)" }}>
      <Button size="sm" disabled={busy} onClick={() => void run()}>{busy ? t("models.testing") : t("models.test")}</Button>
      {provider.hosted ? <span className="fc-muted">{t("models.paidTest", { name: provider.name })}</span> : null}
    </span>
  );
}
