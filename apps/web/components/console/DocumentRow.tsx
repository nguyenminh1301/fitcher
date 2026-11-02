"use client";

import { Icon } from "@/components/brand/Icon";
import { Button, Chip } from "@/components/ui/controls";
import { StatusPill } from "@/components/ui/feedback";
import type { DocumentRow as Document } from "@/lib/api/provisional";
import { useI18n } from "@/lib/i18n/react";

type Props = {
  document: Document;
  /** The pack's roles; the chips choose which of them may see the document in search. */
  packRoles: string[];
  compiling: boolean;
  onRoles: (roles: string[]) => void;
  onDraft: () => void;
  onDelete: () => void;
};

/** One uploaded document: its file, the roles that may see it, its status and actions. */
export function DocumentRow({ document, packRoles, compiling, onRoles, onDraft, onDelete }: Props) {
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
      <div className="fc-doc-roles" role="group" aria-label={`${t("ui.visibleTo")} · ${document.name}`}>
        {packRoles.map((role) => {
          const on = document.roles.includes(role);
          return (
            <Chip key={role} size="sm" selected={on} onClick={() => onRoles(on ? document.roles.filter((item) => item !== role) : [...document.roles, role])}>
              {role}
            </Chip>
          );
        })}
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
