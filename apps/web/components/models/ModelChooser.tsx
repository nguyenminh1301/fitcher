"use client";

// Choosing the model of a provider that proposes none (an OpenAI-compatible service or server, DECISIONS §2):
// the provider's own model list, searchable, with OpenRouter's free models first and only them by default. The
// chosen model answers every chat tier; each tier can be changed later on the Models page.

import { useEffect, useMemo, useState } from "react";

import { FREE_SUFFIX, isOpenRouter } from "@/components/models/presets";
import { Button, Chip, TextField } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import type { FitcherApi } from "@/lib/api/client";
import { errorText } from "@/lib/api/errorText";
import type { ProviderView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

const message = errorText;

export function ModelChooser({ models, provider, tiers, onChosen }: {
  models: FitcherApi["models"];
  provider: ProviderView;
  /** The chat tiers the chosen model answers. */
  tiers: string[];
  onChosen: (model: string) => void;
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
      .catch((cause) => setError(message(cause)));
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
      onChosen(model);
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fc-stack" style={{ gap: "var(--base-size-12)" }}>
      <p style={{ margin: 0 }}>{t("models.chooseHint", { name: provider.name })}</p>
      {listed === null && !error ? <p className="fc-muted" role="status" style={{ margin: 0 }}>{t("models.loadingModels")}</p> : null}
      {listed ? (
        <>
          <div className="fc-row" style={{ gap: "var(--base-size-8)", flexWrap: "wrap", alignItems: "flex-end" }}>
            <div style={{ flex: "1 1 220px" }}>
              <TextField label={t("models.searchModels")} value={search} onChange={(event) => setSearch(event.target.value)} />
            </div>
            {openRouter ? (
              <Chip selected={freeOnly} icon={freeOnly ? "check" : undefined} onClick={() => setFreeOnly(!freeOnly)}>{t("models.freeOnly")}</Chip>
            ) : null}
          </div>
          <div className="fc-field">
            <label className="fc-field-label" htmlFor="chosen-model">{t("models.tierModel")}</label>
            <select id="chosen-model" className="fc-input" size={Math.min(8, Math.max(shown.length, 2))} style={{ height: "auto" }}
              value={model} onChange={(event) => setModel(event.target.value)}>
              {shown.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
            <span className="fc-field-help">
              {shown.length ? t("models.shownCount", { shown: shown.length, total: listed.length }) : t("models.noneShown")}
            </span>
          </div>
          {openRouter && freeOnly ? <p className="fc-field-help" style={{ margin: 0 }}>{t("guide.freeNote")}</p> : null}
          <div>
            <Button variant="primary" disabled={busy || !model} onClick={() => void use()}>{t("models.useForAll")}</Button>
          </div>
        </>
      ) : null}
      {error ? <WarningBanner tone="danger">{error}</WarningBanner> : null}
    </div>
  );
}
