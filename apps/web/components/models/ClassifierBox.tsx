"use client";

// The prompt-injection filter of the Models page (DECISIONS §9). The English and Vietnamese rules always screen
// every question; the classifier adds a model's score and, once on, stops a question it cannot score. It runs
// through a provider that hosts Llama Prompt Guard (Groq does, free) or on this computer from a model downloaded
// here. The page finds the providers that list a Prompt Guard model, so turning it on is one click when one is
// added, and otherwise offers the download with its progress.

import { useCallback, useEffect, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { Segmented, Switch } from "@/components/ui/controls";
import type { FitcherApi } from "@/lib/api/client";
import { errorText } from "@/lib/api/errorText";
import type { ClassifierChange, ClassifierDownload, ClassifierStatus, ProviderView } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

type Models = FitcherApi["models"];
type Engine = NonNullable<ClassifierChange["engine"]>;
/** A provider that hosts a Prompt Guard model, and its models of that kind. */
type Host = { provider: ProviderView; models: string[] };

const GUARD = /prompt-guard/i;
const POLL_MS = 1000;

/** The providers whose model list holds a Prompt Guard model; a provider that cannot list its models is left out. */
export function useGuardHosts(models: Models, providers: ProviderView[]): Host[] | null {
  const [hosts, setHosts] = useState<Host[] | null>(null);
  useEffect(() => {
    let live = true;
    Promise.allSettled(providers.map((provider) => models.providerModels(provider.id))).then((replies) => {
      if (!live) return;
      setHosts(replies.flatMap((reply, index) => {
        if (reply.status !== "fulfilled") return [];
        const guards = reply.value.models.filter((name) => GUARD.test(name)).sort((a, b) => b.localeCompare(a));
        return guards.length ? [{ provider: providers[index], models: guards }] : [];
      }));
    });
    return () => { live = false; };
  }, [models, providers]);
  return hosts;
}

function megabytes(bytes: number): string {
  return `${Math.round(bytes / 1_000_000)} MB`;
}

export function ClassifierBox({ models, status, providers, onChanged }: {
  models: Models; status: ClassifierStatus; providers: ProviderView[]; onChanged: (text: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const hosts = useGuardHosts(models, providers);
  const [engine, setEngine] = useState<Engine>(status.engine ?? "provider");
  const [hostId, setHostId] = useState(status.provider_id ?? "");
  const [model, setModel] = useState(status.model ?? "");
  const [download, setDownload] = useState<ClassifierDownload | null>(status.download ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The first host and its first (largest) Prompt Guard model are chosen until the owner picks another.
  useEffect(() => {
    if (!hosts?.length) return;
    const host = hosts.find((item) => item.provider.id === hostId) ?? hosts[0];
    if (host.provider.id !== hostId) setHostId(host.provider.id);
    if (!host.models.includes(model)) setModel(host.models[0]);
  }, [hosts, hostId, model]);

  const downloading = download?.state === "downloading" || download?.state === "checking";
  const follow = useCallback(async () => {
    try {
      setDownload(await models.classifierDownload());
    } catch (cause) {
      setError(errorText(cause));
    }
  }, [models]);
  useEffect(() => {
    if (!downloading) return undefined;
    const timer = window.setInterval(() => void follow(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [downloading, follow]);
  // A finished download makes the model present; the page reads the status again once.
  useEffect(() => {
    if (download?.state === "done" && !status.model_present) void onChanged(t("classifier.downloaded"));
  }, [download?.state, status.model_present, onChanged, t]);

  const host = hosts?.find((item) => item.provider.id === hostId);
  const ready = engine === "provider" ? !!host && !!model : status.model_present;

  async function apply(enabled: boolean) {
    setBusy(true);
    setError(null);
    try {
      const change: ClassifierChange = engine === "provider"
        ? { enabled, engine, provider_id: hostId || null, model: model || null }
        : { enabled, engine };
      await models.changeClassifier(change);
      await onChanged(enabled ? t("modelsPage.classifierOn") : t("modelsPage.classifierOff"));
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }

  async function startDownload() {
    setError(null);
    try {
      setDownload(await models.startClassifierDownload());
    } catch (cause) {
      setError(errorText(cause));
    }
  }

  async function cancelDownload() {
    try {
      setDownload(await models.cancelClassifierDownload());
    } catch (cause) {
      setError(errorText(cause));
    }
  }

  const where = status.enabled
    ? status.engine === "local_onnx" ? t("classifier.runsHere") : t("classifier.runsOn", {
      model: status.model ?? "", provider: providers.find((provider) => provider.id === status.provider_id)?.name ?? status.provider_id ?? "",
    })
    : null;
  return (
    <section className="box" aria-labelledby="classifier-title">
      <div className="box-head"><h2 id="classifier-title" className="box-title">{t("models.classifier")}</h2></div>
      <div className="box-body">
        <p className="fc-muted" style={{ margin: 0 }}>{t("classifier.rulesAlways")}</p>
        <div>
          <Switch label={t("models.classifier")} checked={status.enabled} disabled={busy || (!status.enabled && !ready)}
            onChange={(on) => void apply(on)} />
        </div>
        {where ? <div className="fc-banner fc-banner-success" role="status"><Icon name="shieldCheck" /><div>{where}</div></div> : null}
        <p className="fc-muted" style={{ margin: 0 }}>{t("models.classifierOn")}</p>
        <div className="fc-field">
          <span className="fc-field-label">{t("classifier.whereLabel")}</span>
          <div style={{ alignSelf: "flex-start" }}>
            <Segmented label={t("classifier.whereLabel")} value={engine} onChange={(next) => setEngine(next as Engine)}
              options={[["provider", t("classifier.engine_provider")], ["local_onnx", t("classifier.engine_local")]]} />
          </div>
        </div>
        {engine === "provider" ? (
          hosts === null ? <p className="fc-muted" style={{ margin: 0 }}><span className="fc-spin fc-spinning" aria-hidden="true" /> {t("classifier.looking")}</p>
          : hosts.length ? (
            <div className="mp-filters">
              <div className="sel">
                <select className="fc-input fc-input-sm" aria-label={t("classifier.provider")} value={hostId} onChange={(event) => setHostId(event.target.value)}>
                  {hosts.map((item) => <option key={item.provider.id} value={item.provider.id}>{item.provider.name}</option>)}
                </select>
                <Icon name="chevronDown" />
              </div>
              <div className="sel">
                <select className="fc-input fc-input-sm" aria-label={t("classifier.model")} value={model} onChange={(event) => setModel(event.target.value)}>
                  {(host?.models ?? []).map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
                <Icon name="chevronDown" />
              </div>
              {status.enabled && (status.engine !== engine || status.provider_id !== hostId || status.model !== model) ? (
                <button type="button" className="fc-btn fc-btn-sm" disabled={busy} onClick={() => void apply(true)}>{t("classifier.use")}</button>
              ) : null}
            </div>
          ) : <div className="fc-banner fc-banner-info" role="status"><Icon name="info" /><div>{t("classifier.noHost")}</div></div>
        ) : (
          <div className="box-body" style={{ padding: 0 }}>
            {status.model_present ? (
              <p style={{ margin: 0 }}><Icon name="circleCheck" /> {t("classifier.downloadedNote", { version: status.version ?? "" })}</p>
            ) : downloading && download ? (
              <div className="mp-filters">
                <progress max={download.bytes_total || 1} value={download.bytes_done} aria-label={t("classifier.progress")} />
                <span className="fc-muted">{download.state === "checking" ? t("classifier.checking") : `${megabytes(download.bytes_done)} / ${megabytes(download.bytes_total)}`}</span>
                <button type="button" className="fc-btn fc-btn-sm" onClick={() => void cancelDownload()}>{t("common.cancel")}</button>
              </div>
            ) : (
              <div className="mp-filters">
                <button type="button" className="fc-btn fc-btn-sm" onClick={() => void startDownload()}>
                  <Icon name="download" />{t("classifier.download", { size: download?.bytes_total ? megabytes(download.bytes_total) : "" })}
                </button>
                {download?.state === "failed" ? <span className="fc-field-error" role="alert"><Icon name="alert" />{download.error ?? t("classifier.downloadFailed")}</span> : null}
              </div>
            )}
            {status.license ? <p className="fc-field-help" style={{ margin: 0 }}>{t("classifier.license", { source: status.download_source ?? "", license: status.license })}</p> : null}
            {status.enabled && status.engine !== engine && status.model_present ? (
              <div><button type="button" className="fc-btn fc-btn-sm" disabled={busy} onClick={() => void apply(true)}>{t("classifier.use")}</button></div>
            ) : null}
          </div>
        )}
        {error ? <span className="fc-field-error" role="alert"><Icon name="alert" />{error}</span> : null}
      </div>
    </section>
  );
}
