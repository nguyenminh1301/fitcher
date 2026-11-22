"use client";

import { useRef, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { useI18n } from "@/lib/i18n/react";

/** The document types and size the Documents page accepts (DECISIONS §5). */
export const ALLOWED_EXTENSIONS = ["pdf", "docx", "md", "txt", "xlsx"];
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

/** Drop files or choose them; blocked while the pack compiles. */
export function UploadDropzone({ disabled, onFiles }: { disabled?: boolean; onFiles: (files: File[]) => void }) {
  const { t } = useI18n();
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const take = (files: FileList | null) => {
    if (!disabled && files?.length) onFiles(Array.from(files));
  };
  return (
    <div className="drop" data-state={over ? "drag" : undefined} aria-disabled={disabled ? "true" : undefined}
      onDragOver={(event) => { event.preventDefault(); if (!disabled) setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => { event.preventDefault(); setOver(false); take(event.dataTransfer.files); }}>
      <div className="drop-icon"><Icon name={disabled ? "lock" : "upload"} size="lg" /></div>
      {disabled ? <div>{t("ui.dropBlocked")}</div> : (
        <div className="drop-line">{t("ui.dropTitle")} <button type="button" className="fc-btn fc-btn-sm" onClick={() => input.current?.click()}>{t("ui.browse")}</button></div>
      )}
      <div className="fc-muted">{t("ui.dropSub")}</div>
      <input ref={input} type="file" multiple hidden aria-label={t("ui.browse")} accept={ALLOWED_EXTENSIONS.map((extension) => `.${extension}`).join(",")}
        onChange={(event) => { take(event.target.files); event.target.value = ""; }} />
    </div>
  );
}
