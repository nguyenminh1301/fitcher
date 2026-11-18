"use client";

// Documents (DECISIONS §5, §11): turn company documents on or off (off on a new instance), upload, list and
// delete them, and draft pack items from an indexed document, which uses paid AI. Turning them off while some
// are stored asks first: the files stay but are no longer searched.

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { useConsole } from "@/components/console/ConsoleLayout";
import { DocumentRow } from "@/components/console/DocumentRow";
import { ListPage } from "@/components/console/ListPage";
import { PaidAiConfirm } from "@/components/console/PaidAiConfirm";
import { ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES, UploadDropzone } from "@/components/console/UploadDropzone";
import { Button, Switch } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
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
          <div className="fc-card"><div className="fc-card-body fc-stack">
            <p style={{ margin: 0 }}>{t("ui.documentsAbout")}</p>
            <div>{toggle}</div>
          </div></div>
        </ListPage>
      )}
      {error ? <WarningBanner tone="danger" onDismiss={() => setError(null)}>{error}</WarningBanner> : null}
      <Dialog open={confirming} title={t("ui.documentsOffTitle")} onClose={() => setConfirming(false)}
        actions={
          <>
            <Button onClick={() => setConfirming(false)}>{t("ui.cancel")}</Button>
            <Button variant="primary" disabled={busy} onClick={() => void set(false, true)}>{t("ui.documentsOffButton")}</Button>
          </>
        }>
        {t("ui.documentsOffText", { n: settings.documents })}
      </Dialog>
    </>
  );
}

function DocumentList({ actions }: { actions: ReactNode }) {
  const { t } = useI18n();
  const { api } = useChat();
  const { toast } = useConsole();
  const { data, failed, reload } = useLoad(useCallback(() => api.documents.list(), [api]));
  const [error, setError] = useState<string | null>(null);
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
    for (const file of files) {
      const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
      if (!ALLOWED_EXTENSIONS.includes(extension)) setError(t("ui.badType", { name: file.name }));
      else if (file.size > MAX_UPLOAD_BYTES) setError(t("ui.tooBig", { name: file.name }));
      else {
        setError(null);
        try {
          // Every pack role may read a new document until the reviewer narrows it with the role chips.
          await api.documents.upload(file, []);
          toast(t("ui.uploaded", { name: file.name }));
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      }
    }
    await reload();
  }

  async function draft(document: Document) {
    setDraftRunning(true);
    toast(t("ui.drafting", { name: document.name }));
    try {
      await api.documents.draft(document.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setDraftRunning(false);
    }
  }

  return (
    <ListPage section="documents" actions={actions} loading={!data} failed={failed}>
      {compiling ? <WarningBanner tone="info" icon="loader">{t("ui.compiling")}</WarningBanner> : null}
      <UploadDropzone disabled={compiling} onFiles={(files) => void upload(files)} />
      {error ? <WarningBanner tone="danger" onDismiss={() => setError(null)}>{error}</WarningBanner> : null}
      <div className="fc-docs">
        <div className="fc-docs-head">{t("ui.files", { n: documents.length })}</div>
        <div role="list">
          {documents.map((document) => (
            <DocumentRow key={document.id} document={document} compiling={compiling}
              onDraft={() => setDrafting(document)}
              onDelete={() => setDeleting(document)} />
          ))}
        </div>
      </div>
      <PaidAiConfirm open={!!drafting} text={t("ui.draftConfirmText", { name: drafting?.name ?? "" })}
        onClose={() => setDrafting(null)} onConfirm={() => drafting && void draft(drafting)} />
      <Dialog open={!!deleting} tone="danger" title={t("ui.deleteDocTitle", { name: deleting?.name ?? "" })} onClose={() => setDeleting(null)}
        actions={
          <>
            <Button onClick={() => setDeleting(null)}>{t("ui.cancel")}</Button>
            <Button variant="danger" icon="trash" onClick={async () => {
              if (!deleting) return;
              await api.documents.remove(deleting.id);
              toast(t("ui.deletedName", { name: deleting.name }));
              setDeleting(null);
              await reload();
            }}>{t("ui.del")}</Button>
          </>
        }>
        {t("ui.deleteDocText")}
      </Dialog>
    </ListPage>
  );
}
