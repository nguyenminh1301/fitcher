"use client";

// Documents (DECISIONS §5, §11): upload, list and delete company documents, choose the pack roles that
// may see each one, and draft pack items from an indexed document, which uses paid AI.

import { useCallback, useEffect, useState } from "react";

import { useConsole } from "@/components/console/ConsoleLayout";
import { DocumentRow } from "@/components/console/DocumentRow";
import { ListPage } from "@/components/console/ListPage";
import { PaidAiConfirm } from "@/components/console/PaidAiConfirm";
import { ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES, UploadDropzone } from "@/components/console/UploadDropzone";
import { Button } from "@/components/ui/controls";
import { WarningBanner } from "@/components/ui/feedback";
import { Dialog } from "@/components/ui/overlay";
import type { DocumentRow as Document } from "@/lib/api/provisional";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import { useI18n } from "@/lib/i18n/react";

// A processing document is checked again this often until it is indexed or fails.
const POLL_MS = 1000;

export function DocumentsSection() {
  const { t } = useI18n();
  const { api, pack } = useChat();
  const { toast } = useConsole();
  const { data, failed, reload } = useLoad(useCallback(() => api.documents.list(), [api]));
  const [error, setError] = useState<string | null>(null);
  const [compiling, setCompiling] = useState(false);
  const [deleting, setDeleting] = useState<Document | null>(null);
  const [drafting, setDrafting] = useState<Document | null>(null);
  const documents = data ?? [];
  const processing = documents.some((document) => document.status === "processing");

  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(() => void reload(), POLL_MS);
    return () => clearInterval(timer);
  }, [processing, reload]);

  async function upload(files: File[]) {
    for (const file of files) {
      const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
      if (documents.some((document) => document.name === file.name)) setError(t("ui.duplicate", { name: file.name }));
      else if (!ALLOWED_EXTENSIONS.includes(extension)) setError(t("ui.badType", { name: file.name }));
      else if (file.size > MAX_UPLOAD_BYTES) setError(t("ui.tooBig", { name: file.name }));
      else {
        setError(null);
        await api.documents.upload({ name: file.name, size: file.size }, []);
        toast(t("ui.uploaded", { name: file.name }));
      }
    }
    await reload();
  }

  async function draft(document: Document) {
    setCompiling(true);
    toast(t("ui.drafting", { name: document.name }));
    try {
      await api.documents.draft(document.id);
    } finally {
      setCompiling(false);
    }
  }

  return (
    <ListPage section="documents" loading={!data} failed={failed}>
      {compiling ? <WarningBanner tone="info" icon="loader">{t("ui.compiling")}</WarningBanner> : null}
      <UploadDropzone disabled={compiling} onFiles={(files) => void upload(files)} />
      {error ? <WarningBanner tone="danger" onDismiss={() => setError(null)}>{error}</WarningBanner> : null}
      <div className="fc-docs">
        <div className="fc-docs-head">{t("ui.files", { n: documents.length })}</div>
        <div role="list">
          {documents.map((document) => (
            <DocumentRow key={document.id} document={document} packRoles={pack?.roles ?? []} compiling={compiling}
              onRoles={async (roles) => { await api.documents.setRoles(document.id, roles); await reload(); }}
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
