"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { cx } from "@/lib/cx";
import { useI18n } from "@/lib/i18n/react";

export type ComposerProps = { onSend: (text: string) => void; onStop?: () => void; running?: boolean; large?: boolean; meta?: ReactNode; id?: string };

/** The question box: Enter sends, Shift+Enter adds a line; while an answer streams the button stops it. */
export function Composer({ onSend, onStop, running, large, meta, id = "fc-composer" }: ComposerProps) {
  const { t } = useI18n();
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(200, element.scrollHeight)}px`;
  }, [value]);

  function submit() {
    const text = value.trim();
    if (!text || running) return;
    onSend(text);
    setValue("");
  }

  return (
    <div>
      <form className={cx("fc-composer", large && "fc-composer-lg")} onSubmit={(event) => { event.preventDefault(); submit(); }}>
        <label className="fc-sr" htmlFor={id}>{t("ui.composerLabel")}</label>
        <textarea
          id={id}
          ref={ref}
          rows={1}
          value={value}
          placeholder={t("ui.composerPlaceholder")}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <div className="fc-composer-bar">
          {meta ? <span className="fc-composer-meta">{meta}</span> : null}
          {running ? (
            <button type="button" className="fc-send fc-send-stop" aria-label={t("ui.stop")} title={t("ui.stop")} onClick={onStop}><Icon name="stop" /></button>
          ) : (
            <button type="submit" className="fc-send" aria-label={t("ui.send")} title={t("ui.send")} disabled={!value.trim()}><Icon name="arrowUp" /></button>
          )}
        </div>
      </form>
      <div className="fc-composer-hint">{t("ui.composerHint")}</div>
    </div>
  );
}

/** The active pack, shown inside the composer where the question goes. */
export function PackChip({ name }: { name: string }) {
  const { t } = useI18n();
  return <span className="fc-composer-pack" title={t("ui.activePack")}><Icon name="database" />{name}</span>;
}
