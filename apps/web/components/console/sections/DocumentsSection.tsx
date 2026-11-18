"use client";

// Documents (DECISIONS §5, §11): turn company documents on or off (off on a new instance), upload, list and
// delete them, and draft pack items from an indexed document, which uses paid AI. Turning them off while some
// are stored asks first: the files stay but are no longer searched.

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { useConsole } from "@/components/console/ConsoleLayout";
import { Empty, StatusLabel } from "@/components/console/kit";
import { ListPage } from "@/components/console/ListPage";
import { ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES, UploadDropzone } from "@/components/console/UploadDropzone";
import { Switch } from "@/components/ui/controls";
import { Dialog } from "@/components/ui/overlay";
import type { DocumentSettings, DocumentView as Document } from "@/lib/contracts";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import { useI18n } from "@/lib/i18n/react";

// A processing document is checked again this often until it is indexed or fails.
const POLL_MS = 1000;

export function DocumentsSection() {
  const { api } = useChat();
  const [settings, setSettings] = useState<DocumentSettings | null>(null);
  const [settingsFailed, setSettingsFailed] = useState(false);
  useEffect(() => {
    api.documents.settings().then(setSettings).catch(() => setSettingsFailed(true));
  }, [api]);
  if (settingsFailed) return <ListPage section="documents" loading={false} failed />;
  if (!settings) return <ListPage section="documents" loading />;
  return <DocumentsSwitch settings={settings} onChange={setSettings} />;
}

function DocumentsSwitch({ settings, onChange }: { settings: DocumentSettings; onChange: (next: DocumentSettings) => void }) {
  const { t } = useI18n();
  const { api } = useChat();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function set(enabled: boolean, confirm = false) {
    setBusy(true);
    setError(null);
    try {
      onChange(await api.documents.setEnabled(enabled, confirm));
      setConfirming(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }
  const toggle = (
    <Switch label={t("ui.documentsUse")} checked={settings.enabled} disabled={busy}
      onChange={(enabled) => (!enabled && settings.documents > 0 ? setConfirming(true) : void set(enabled))} />
  );
  return (
    <>
      {settings.enabled ? <DocumentList actions={toggle} /> : (
        <ListPage section="documents" loading={false}>
          <section className="box"><div className="box-body">
            <p style={{ margin: 0 }}>{t("ui.documentsAbout")}</p>
            <div>{toggle}</div>
          </div></section>
        </ListPage>
      )}
      {error ? <div className="fc-banner fc-banner-danger" role="alert"><Icon name="alert" /><div>{error}</div></div> : null}
      <Dialog open={confirming} title={t("ui.documentsOffTitle")} closeLabel={t("common.close")} onClose={() => setConfirming(false)}
        actions={
          <>
            <button type="button" className="fc-btn" onClick={() => setConfirming(false)}>{t("ui.cancel")}</button>
            <button type="button" className="fc-btn fc-btn-primary" disabled={busy} onClick={() => void set(false, true)}>{t("ui.documentsOffButton")}</button>
          </>
        }>
        <p style={{ margin: 0 }}>{t("ui.documentsOffText", { n: settings.documents })}</p>
      </Dialog>
    </>
  );
}

function DocumentList({ actions }: { actions: ReactNode }) {
  const { t, formatNumber } = useI18n();
  const { api } = useChat();
  const { toast } = useConsole();
  const { data, failed, reload } = useLoad(useCallback(() => api.documents.list(), [api]));
  // One line per file that was refused or failed, kept until the next upload.
  const [errors, setErrors] = useState<string[]>([]);
  const [draftRunning, setDraftRunning] = useState(false);
  const [deleting, setDeleting] = useState<Document | null>(null);
  const [drafting, setDrafting] = useState<Document | null>(null);
  const documents = data?.documents ?? [];
  // Uploads and deletes wait while the pack compiles; drafting runs one document at a time.
  const compiling = (data?.compiling ?? false) || draftRunning;
  const processing = documents.some((document) => document.status === "processing");

  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(() => void reload(), POLL_MS);
    return () => clearInterval(timer);
  }, [processing, reload]);

  async function upload(files: File[]) {
    const refused: string[] = [];
    for (const file of files) {
      const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
      if (!ALLOWED_EXTENSIONS.includes(extension)) refused.push(t("ui.badType", { name: file.name }));
      else if (file.size > MAX_UPLOAD_BYTES) refused.push(t("ui.tooBig", { name: file.name }));
      else {
        try {
          await api.documents.upload(file, []);
          toast(t("ui.uploaded", { name: file.name }));
        } catch (reason) {
          refused.push(reason instanceof Error ? reason.message : String(reason));
        }
      }
    }
    setErrors(refused);
    await reload();
  }

  async function draft(document: Document) {
    setDraftRunning(true);
    toast(t("ui.drafting", { name: document.name }));
    try {
      await api.documents.draft(document.id);
    } catch (reason) {
      setErrors([reason instanceof Error ? reason.message : String(reason)]);
    } finally {
      setDraftRunning(false);
    }
  }

  const size = (bytes: number) => bytes >= 1024 * 1024
    ? `${formatNumber(bytes / 1024 / 1024, { maximumFractionDigits: 1 })} MB`
    : `${formatNumber(Math.max(1, Math.round(bytes / 1024)))} KB`;
  return (
    <ListPage section="documents" actions={actions} loading={!data} failed={failed}>
      {compiling ? <div className="fc-banner fc-banner-info" role="status"><Icon name="loader" /><div>{t("ui.compiling")}</div></div> : null}
      <UploadDropzone disabled={compiling} onFiles={(files) => void upload(files)} />
      {errors.map((line, index) => <div key={index} className="fc-field-error" role="alert"><Icon name="alert" />{line}</div>)}
      <section className="box files-box" aria-labelledby="documents-title">
        <div className="box-head"><h2 id="documents-title" className="box-title">{t("ui.nav_documents")}</h2><span className="fc-muted">{t("ui.files", { n: documents.length })}</span></div>
        {documents.length ? (
          <div style={{ overflowX: "auto" }}>
            <table className="tbl tbl-cards">
              <thead><tr><th>{t("ui.name")}</th><th>{t("documentsPage.size")}</th><th>{t("ui.status")}</th><th><span className="fc-sr">{t("ui.actions")}</span></th></tr></thead>
              <tbody>
                {documents.map((document) => (
                  <tr key={document.id} aria-label={document.name}>
                    <td><span className="src-cell"><Icon name="fileText" /><span className="doc-name">{document.name}</span></span></td>
                    <td data-label={t("documentsPage.size")}>{size(document.size)}</td>
                    <td data-label={t("ui.status")}>
                      <StatusLabel status={document.status}>{t(`documentsPage.status_${document.status}`)}</StatusLabel>
                      {document.status === "failed" && document.error ? <div className="fc-field-help">{document.error}</div> : null}
                    </td>
                    <td className="row-actions">
                      <button type="button" className="fc-btn fc-btn-sm" disabled={document.status !== "indexed" || compiling}
                        aria-describedby="paid-note" onClick={() => setDrafting(document)}>{t("ui.draftItems")}</button>
                      <span className="fc-paid" aria-hidden="true">{t("ui.paidAi")}</span>
                      <button type="button" className="fc-btn fc-btn-ghost fc-btn-icon fc-btn-sm" aria-label={`${t("ui.del")} ${document.name}`}
                        onClick={() => setDeleting(document)}><Icon name="trash" /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <span id="paid-note" className="fc-sr">{t("ui.paidAi")}</span>
          </div>
        ) : <Empty icon="fileText" title={t("documentsPage.empty")} />}
      </section>
      <Dialog open={!!drafting} title={t("documentsPage.draftTitle", { name: drafting?.name ?? "" })} closeLabel={t("common.close")} onClose={() => setDrafting(null)}
        actions={<>
          <button type="button" className="fc-btn" onClick={() => setDrafting(null)}>{t("ui.cancel")}</button>
          <button type="button" className="fc-btn fc-btn-primary" onClick={() => { const target = drafting; setDrafting(null); if (target) void draft(target); }}>{t("documentsPage.draftButton")}</button>
        </>}>
        <p style={{ margin: 0 }}>{t("documentsPage.draftText")}</p>
      </Dialog>
      <Dialog open={!!deleting} tone="danger" title={t("ui.deleteDocTitle", { name: deleting?.name ?? "" })} closeLabel={t("common.close")} onClose={() => setDeleting(null)}
        actions={
          <>
            <button type="button" className="fc-btn" onClick={() => setDeleting(null)}>{t("ui.cancel")}</button>
            <button type="button" className="fc-btn fc-btn-danger" onClick={async () => {
              if (!deleting) return;
              await api.documents.remove(deleting.id);
              toast(t("ui.deletedName", { name: deleting.name }));
              setDeleting(null);
              await reload();
            }}>{t("ui.del")}</button>
          </>
        }>
        <p style={{ margin: 0 }}>{t("ui.deleteDocText")}</p>
      </Dialog>
    </ListPage>
  );
}
