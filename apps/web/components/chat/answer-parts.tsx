"use client";

// The parts of an assistant turn (docs/design/web-app.md, Anatomy of an answer): progress steps, the
// summary, notices, clarify options and the feedback bar. Content keeps the language it was written in;
// labels and buttons follow the interface language.

import { Fragment, useState, type ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { Button, Chip, TextField } from "@/components/ui/controls";
import { cx } from "@/lib/cx";
import { DICTIONARIES, translate, type Locale } from "@/lib/i18n";
import { useI18n } from "@/lib/i18n/react";
import type { StepId } from "@/lib/steps";

import { SqlView } from "./SqlView";

export type Step = { id: StepId; attempt?: number; status: "done" | "active" | "failed" | "denied" };

/** A text in the language it was written in (en or vi), whatever the interface language is. */
function contentText(lang: string, key: string, vars?: Record<string, string | number>): string {
  const locale: Locale = lang === "vi" ? "vi" : "en";
  return translate(DICTIONARIES.en, DICTIONARIES[locale], key, vars);
}

/** The live step list while an answer streams, then a "How I got this" toggle. */
export function ProgressSteps({ steps, live, onStop }: { steps: Step[]; live: boolean; onStop?: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const icon = { done: "circleCheck", active: "loader", failed: "circleX", denied: "lock" } as const;
  const list = (
    <ol className="fc-steps" aria-live={live ? "polite" : undefined}>
      {live ? (
        <li className="fc-steps-head">
          <span>{t("ui.working")}</span>
          {onStop ? <Button size="sm" icon="stop" onClick={onStop}>{t("ui.stop")}</Button> : null}
        </li>
      ) : null}
      {steps.map((step, index) => {
        const status = step.id === "repair" && step.status === "active" ? "repair" : step.status;
        return (
          <li key={index} className={cx("fc-step", `fc-step-${status}`)} aria-current={step.status === "active" ? "step" : undefined}>
            <Icon name={step.id === "repair" ? "wrench" : icon[step.status]} spin={step.status === "active" && step.id !== "repair"} />
            <span>{t(`ui.step_${step.id}`, { n: step.attempt ?? 2 })}</span>
          </li>
        );
      })}
    </ol>
  );
  if (live) return list;
  return (
    <>
      <button type="button" className="fc-howto" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon name={open ? "chevronDown" : "chevronRight"} />
        <b>{t("ui.howIGotThis")}</b>
        <span>{`· ${t("ui.stepsCount", { n: steps.length })}`}</span>
      </button>
      {open ? list : null}
    </>
  );
}

/** The summary, with **figures** in bold, in the language the answer was written in. */
export function Summary({ text, lang }: { text: string; lang: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return (
    <p className="fc-answer-summary" lang={lang}>
      {parts.map((part, index) => (index % 2 ? <b key={index}>{part}</b> : <Fragment key={index}>{part}</Fragment>))}
    </p>
  );
}

const NOTICE = {
  denied: ["lock", "neutral", "deniedTitle"], failed: ["circleX", "danger", "failedTitle"], empty: ["searchX", "neutral", "emptyTitle"],
  network: ["wifiOff", "warning", "networkTitle"], stopped: ["stop", "neutral", "stoppedTitle"],
} as const;

type NoticeProps = {
  kind: keyof typeof NOTICE;
  lang: string;
  text?: string;
  blocked?: string[];
  sql?: string;
  error?: string;
  onRetry?: () => void;
  onRephrase?: () => void;
};

/** Denied, failed, empty, lost-connection and stopped answers: calm, specific, never a guessed result. */
export function NoticeCard({ kind, lang, text, blocked, sql, error, onRetry, onRephrase }: NoticeProps) {
  const { t } = useI18n();
  const [icon, tone, title] = NOTICE[kind];
  const fallback = { denied: "", failed: "failedText", empty: "emptyText", network: "networkText", stopped: "stoppedText" }[kind];
  return (
    <div className={cx("fc-notice", tone !== "neutral" && `fc-notice-${tone}`)} role={kind === "failed" || kind === "network" ? "alert" : "status"}>
      <div className="fc-notice-head" lang={lang}>
        <span className="fc-notice-badge"><Icon name={icon} /></span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h3 className="fc-notice-title">{contentText(lang, `ui.${title}`)}</h3>
          <p className="fc-notice-text">
            {text ?? contentText(lang, `ui.${fallback}`)}
            {kind === "denied" && blocked?.length ? (
              <span> {blocked.map((item, index) => <Fragment key={item}>{index ? ", " : ""}<code className="fc-code">{item}</code></Fragment>)}</span>
            ) : null}
          </p>
          {kind === "denied" ? <p className="fc-notice-text">{contentText(lang, "ui.deniedHint")}</p> : null}
        </div>
      </div>
      {kind === "failed" && sql ? <SqlView sql={sql} title={t("ui.lastSql")} badge={false} defaultOpen /> : null}
      {kind === "failed" && error ? (
        <div className="fc-answer-section">
          <span className="fc-field-label">{t("ui.dbError")}</span>
          <pre className="fc-dberr">{error}</pre>
        </div>
      ) : null}
      {kind === "empty" && sql ? <SqlView sql={sql} /> : null}
      {onRetry || onRephrase ? (
        <div className="fc-row">
          {onRetry ? <Button icon="refresh" onClick={onRetry}>{t("ui.retry")}</Button> : null}
          {onRephrase ? <Button variant="ghost" icon="pencil" onClick={onRephrase}>{t("ui.rephrase")}</Button> : null}
        </div>
      ) : null}
    </div>
  );
}

/** A clarifying question with its options; picking one sends it as the next question. */
export function ClarifyOptions({ question, options, lang, onPick }: { question: string; options: { id: string; label: string }[]; lang: string; onPick: (label: string) => void }) {
  const [picked, setPicked] = useState<string | null>(null);
  return (
    <div className="fc-clarify" role="group" aria-label={question} lang={lang}>
      <p>{question}</p>
      <div className="fc-clarify-opts">
        {options.map((option) => (
          <Chip
            key={option.id}
            selected={picked === null ? undefined : picked === option.id}
            disabled={picked !== null && picked !== option.id}
            onClick={() => {
              if (picked !== null) return;
              setPicked(option.id);
              onPick(option.label);
            }}
          >
            {option.label}
          </Chip>
        ))}
      </div>
    </div>
  );
}

/** Copy, like, dislike with an optional note, and retry. */
export function FeedbackBar({ onSubmit, onCopy, onRetry }: { onSubmit: (rating: "like" | "dislike", note?: string) => void; onCopy?: () => string; onRetry?: () => void }) {
  const { t } = useI18n();
  const [value, setValue] = useState<"like" | "dislike" | null>(null);
  const [note, setNote] = useState("");
  const [sent, setSent] = useState(false);
  const [copied, setCopied] = useState(false);

  function pick(rating: "like" | "dislike") {
    setValue(value === rating ? null : rating);
    setSent(false);
    if (rating === "like" && value !== "like") {
      onSubmit("like");
      setSent(true);
    }
  }

  let after: ReactNode = null;
  if (value === "dislike" && !sent)
    after = (
      <div className="fc-feedback-note">
        <TextField multiline rows={2} label={t("ui.noteLabel")} value={note} placeholder={t("ui.notePlaceholder")} onChange={(event) => setNote(event.target.value)} />
        <div className="fc-row">
          <Button variant="primary" onClick={() => { setSent(true); onSubmit("dislike", note.trim() || undefined); }}>{t("ui.sendFeedback")}</Button>
          <Button variant="ghost" onClick={() => { setSent(true); onSubmit("dislike"); }}>{t("ui.skip")}</Button>
        </div>
      </div>
    );
  else if (sent)
    after = <div className="fc-row fc-muted" role="status" style={{ fontSize: 12 }}><Icon name="check" />{t("ui.thanks")}</div>;

  return (
    <div className="fc-feedback">
      <div className="fc-feedback-row">
        {onCopy ? (
          <Button variant="ghost" size="sm" iconOnly icon={copied ? "check" : "copy"} label={copied ? t("ui.copiedAnswer") : t("ui.copyAnswer")}
            onClick={() => {
              void navigator.clipboard?.writeText(onCopy()).catch(() => undefined);
              setCopied(true);
              setTimeout(() => setCopied(false), 1600);
            }} />
        ) : null}
        <Button variant="ghost" size="sm" iconOnly icon="thumbsUp" label={t("ui.helpful")} aria-pressed={value === "like"} onClick={() => pick("like")} />
        <Button variant="ghost" size="sm" iconOnly icon="thumbsDown" label={t("ui.notHelpful")} aria-pressed={value === "dislike"} onClick={() => pick("dislike")} />
        {onRetry ? <Button variant="ghost" size="sm" iconOnly icon="refresh" label={t("ui.retryAnswer")} onClick={onRetry} /> : null}
      </div>
      {after}
    </div>
  );
}
