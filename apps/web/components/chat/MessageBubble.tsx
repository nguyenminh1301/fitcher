"use client";

import { useState } from "react";

import { Button } from "@/components/ui/controls";
import { useI18n } from "@/lib/i18n/react";

/** The user's own question, in the language it was written in, with copy and edit. */
export function MessageBubble({ children, lang, onEdit, disabled }: { children: string; lang?: string; onEdit?: (text: string) => void; disabled?: boolean }) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [copied, setCopied] = useState(false);

  if (editing)
    return (
      <form
        className="fc-msg-edit"
        onSubmit={(event) => {
          event.preventDefault();
          const text = draft.trim();
          if (!text) return;
          setEditing(false);
          onEdit?.(text);
        }}
      >
        <label className="fc-sr" htmlFor="fc-edit">{t("ui.editMessage")}</label>
        <textarea
          id="fc-edit"
          className="fc-input"
          rows={3}
          value={draft}
          autoFocus
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setEditing(false);
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <div className="fc-row" style={{ justifyContent: "flex-end" }}>
          <Button variant="ghost" onClick={() => setEditing(false)}>{t("ui.cancel")}</Button>
          <Button variant="primary" type="submit" disabled={!draft.trim()}>{t("ui.sendEdit")}</Button>
        </div>
      </form>
    );

  return (
    <div className="fc-uturn">
      <div className="fc-msg-user" lang={lang}>{children}</div>
      <div className="fc-msg-actions">
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          icon={copied ? "check" : "copy"}
          label={t("ui.copyMessage")}
          onClick={() => {
            void navigator.clipboard?.writeText(children).catch(() => undefined);
            setCopied(true);
            setTimeout(() => setCopied(false), 1600);
          }}
        />
        {onEdit ? (
          <Button variant="ghost" size="sm" iconOnly icon="pencil" label={t("ui.editMessage")} disabled={disabled} onClick={() => { setDraft(children); setEditing(true); }} />
        ) : null}
      </div>
    </div>
  );
}
