"use client";

// The setup's Documents step (DECISIONS §5, §15): whether fitcher reads company documents, with upload in
// place once a pack is active. Off hides the Documents page; documents already kept stay stored, so turning
// them off then asks for confirmation, and turning them on again indexes them at the next compile.

import { useEffect, useState } from "react";

import { ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES, UploadDropzone } from "@/components/console/UploadDropzone";
import { Button } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import type { FitcherApi } from "@/lib/api/client";
import { errorText } from "@/lib/api/errorText";
import { useI18n } from "@/lib/i18n/react";

export type DocumentsStepProps = {
  documents: FitcherApi["documents"];
  /** The active pack's roles; it rejects without an active pack. */
  packRoles: () => Promise<string[]>;
  disabled: boolean;
  onDone: () => void;
  onSkip: () => void;
  /** The step was answered before and is open again: leaving it keeps that answer. */
  answered?: boolean;
};

export function DocumentsStep({ documents, packRoles, disabled, onDone, onSkip, answered = false }: DocumentsStepProps) {
  const { t } = useI18n();
  const [enabled, setEnabled] = useState(true);
  const [roles, setRoles] = useState<string[] | null>(null);
  const [kept, setKept] = useState<number | null>(null);
  const [uploaded, setUploaded] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    documents.settings().then((current) => setEnabled(current.enabled)).catch(() => null);
    packRoles().then(setRoles).catch(() => setRoles(null));
  }, [documents, packRoles]);

  async function save(confirm = false) {
    setBusy(true);
    setError(null);
    try {
      await documents.setEnabled(enabled, confirm);
      onDone();
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      if (message.includes("409")) setKept((await documents.settings().catch(() => null))?.documents ?? 0);
      else setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }

  async function upload(files: File[]) {
    for (const file of files) {
      const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
      if (!ALLOWED_EXTENSIONS.includes(extension)) setError(t("ui.badType", { name: file.name }));
      else if (file.size > MAX_UPLOAD_BYTES) setError(t("ui.tooBig", { name: file.name }));
      else {
        setError(null);
        try {
          // Every pack role may read a document uploaded here; the Documents page narrows it later.
          await documents.upload(file, roles ?? []);
          setUploaded((names) => [...names, file.name]);
        } catch (cause) {
          setError(errorText(cause));
        }
      }
    }
  }

  const locked = disabled || busy;
  return (
    <section className="fc-card" aria-label={t("setup.step_documents")}>
      <div className="fc-card-head"><h2 className="fc-card-title">{t("setup.documentsQuestion")}</h2></div>
      <div className="fc-card-body fc-stack">
        <p className="fc-muted" style={{ margin: 0 }}>{t("setup.documentsHint")}</p>
        <fieldset disabled={locked} style={{ border: 0, padding: 0, margin: 0 }} className="fc-stack">
          <legend className="fc-muted" style={{ padding: 0 }}>{t("setup.documentsQuestion")}</legend>
          {[true, false].map((option) => (
            <label key={String(option)} className="fc-row" style={{ alignItems: "flex-start", gap: "var(--base-size-12)" }}>
              <input type="radio" name="documents" checked={enabled === option}
                onChange={() => { setEnabled(option); setKept(null); }} />
              <strong>{t(option ? "setup.documentsOn" : "setup.documentsOff")}</strong>
            </label>
          ))}
        </fieldset>
        {enabled && !disabled ? (
          roles?.length ? (
            <>
              <p className="fc-muted" style={{ margin: 0 }}>{t("setup.documentsUpload")}</p>
              <UploadDropzone disabled={locked} onFiles={(files) => void upload(files)} />
              {uploaded.length ? (
                <ul aria-label={t("setup.documentsUploaded")} style={{ margin: 0 }}>
                  {uploaded.map((name) => <li key={name}>{name}</li>)}
                </ul>
              ) : null}
            </>
          ) : <p className="fc-muted" style={{ margin: 0 }}>{t("setup.documentsNoPack")}</p>
        ) : null}
        {kept !== null ? (
          <WarningBanner tone="warning">
            {t("setup.documentsKept", { count: kept })}{" "}
            <Button variant="danger" disabled={locked} onClick={() => void save(true)}>{t("setup.documentsConfirmOff")}</Button>
          </WarningBanner>
        ) : null}
        {error ? <WarningBanner tone="danger">{error}</WarningBanner> : null}
        <div className="fc-row" style={{ gap: "var(--base-size-8)" }}>
          <Button variant="primary" disabled={locked} onClick={() => void save()}>{t("setup.continue")}</Button>
          {disabled ? null : <Button onClick={onSkip}>{answered ? t("setup.keepAnswer") : t("setup.skip")}</Button>}
        </div>
      </div>
    </section>
  );
}
