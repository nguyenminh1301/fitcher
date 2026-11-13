"use client";

// Adding a model provider (DECISIONS §2, §15), shared by the setup's Models step and the Models page. A
// hosted provider takes a key; a model server takes a base URL, and an OpenAI-compatible endpoint an optional
// key. The key is sent once and never shown again: the api answers with its last four characters only.

import { useState } from "react";

import { Button, TextField } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import type { FitcherApi } from "@/lib/api/client";
import type { ProviderCreate, ProviderTestResult, ProviderView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

type Kind = ProviderCreate["kind"];
export const KINDS: Kind[] = ["openai", "anthropic", "gemini", "ollama", "openai_compatible"];
const HOSTED: Kind[] = ["openai", "anthropic", "gemini"];

function message(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

export function ProviderForm({ models, onAdded }: { models: FitcherApi["models"]; onAdded: (provider: ProviderView) => void }) {
  const { t } = useI18n();
  const [kind, setKind] = useState<Kind>("openai");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hosted = HOSTED.includes(kind);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      const body: ProviderCreate = { kind };
      if (apiKey) body.api_key = apiKey;
      if (!hosted) body.base_url = baseUrl;
      const provider = await models.addProvider(body);
      setApiKey("");
      onAdded(provider);
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="fc-stack" style={{ gap: "var(--base-size-12)" }} onSubmit={(event) => { event.preventDefault(); void add(); }}>
      <div className="fc-field">
        <label className="fc-field-label" htmlFor="provider-kind">{t("models.kind")}</label>
        <select id="provider-kind" className="fc-input" value={kind} disabled={busy} onChange={(event) => setKind(event.target.value as Kind)}>
          {KINDS.map((option) => <option key={option} value={option}>{t(`models.kind_${option}`)}</option>)}
        </select>
      </div>
      {hosted || kind === "openai_compatible" ? (
        <TextField label={hosted ? t("models.apiKey") : t("models.apiKeyOptional")} type="password" autoComplete="off"
          value={apiKey} disabled={busy} onChange={(event) => setApiKey(event.target.value)} />
      ) : null}
      {!hosted ? (
        <TextField label={t("models.baseUrl")} value={baseUrl} disabled={busy} help={t("models.hostHint")}
          placeholder={kind === "ollama" ? "http://host.docker.internal:11434" : "http://host.docker.internal:1234/v1"}
          onChange={(event) => setBaseUrl(event.target.value)} />
      ) : null}
      {error ? <WarningBanner tone="danger">{error}</WarningBanner> : null}
      <div>
        <Button variant="primary" type="submit" disabled={busy || (hosted ? !apiKey : !baseUrl)}>
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

/** Runs one provider's test call, labelled as billed for a hosted provider. */
export function ProviderTestButton({ models, provider, onResult }: {
  models: FitcherApi["models"];
  provider: ProviderView;
  onResult: (result: ProviderTestResult | null, error?: string) => void;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    try {
      onResult(await models.testProvider(provider.id));
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
