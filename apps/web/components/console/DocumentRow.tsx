"use client";

import { Icon } from "@/components/brand/Icon";
import { Button } from "@/components/ui/controls";
import { StatusPill } from "@/components/ui/feedback";
import type { DocumentView as Document } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

type Props = {
  document: Document;
  compiling: boolean;
  onDraft: () => void;
  onDelete: () => void;
};

/** One uploaded document: its file, its status and actions. A pack has one reader role (DECISIONS §9), which reads
 * every document, so there is no choice of roles. */
export function DocumentRow({ document, compiling, onDraft, onDelete }: Props) {
  const { t, formatNumber, formatDate } = useI18n();
  const size = document.size >= 1024 * 1024
    ? `${formatNumber(document.size / 1024 / 1024, { maximumFractionDigits: 1 })} MB`
    : `${formatNumber(Math.max(1, Math.round(document.size / 1024)))} KB`;
  return (
    <div className="fc-doc" role="listitem">
      <div className="fc-doc-file">
        <Icon name="fileText" />
        <div style={{ minWidth: 0 }}>
          <div className="fc-doc-name" title={document.name}>{document.name}</div>
          <div className="fc-doc-meta">{`${size} · ${formatDate(document.uploaded_at)}`}</div>
        </div>
      </div>
      <div className="fc-doc-status"><StatusPill status={document.status} /></div>
      <div className="fc-doc-actions">
        <Button size="sm" icon="fileText" meta={t("ui.paidAi")} disabled={document.status !== "indexed" || compiling} onClick={onDraft}>{t("ui.draftItems")}</Button>
        <Button size="sm" variant="ghost" iconOnly icon="trash" label={`${t("ui.del")} ${document.name}`} onClick={onDelete} />
      </div>
      {document.status === "failed" && document.error ? <div className="fc-doc-err">{document.error}</div> : null}
    </div>
  );
}
