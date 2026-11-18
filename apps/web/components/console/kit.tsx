"use client";

// Small pieces the console pages share, in the console design: a status label, a confidence bar and the empty
// state of a box.

import type { ReactNode } from "react";

import { Icon } from "@/components/brand/Icon";
import { cx } from "@/lib/cx";
import { useI18n } from "@/lib/i18n/react";

export type Tone = "success" | "danger" | "attention" | "accent" | "done" | null;

/** The colour of a status word the api uses across runs, review items, documents and syncs. */
const TONES: Record<string, Tone> = {
  succeeded: "success", approved: "success", indexed: "success", passed: "success", like: "success",
  failed: "danger", error: "danger", denied: "attention", rejected: "attention", dislike: "attention",
  unreviewed: "attention", processing: "accent", running: "accent",
};

export function StatusLabel({ status, tone, children }: { status?: string; tone?: Tone; children: ReactNode }) {
  const chosen = tone !== undefined ? tone : status ? TONES[status] ?? null : null;
  return (
    <span className={cx("fc-label", chosen && `fc-label-${chosen}`)}>
      {chosen === "accent" ? <span className="fc-spin fc-spinning" aria-hidden="true" /> : null}{children}
    </span>
  );
}

/** How sure the drafter was of a pack item, as a bar and a percentage. */
export function Meter({ value }: { value: number }) {
  const { t } = useI18n();
  const percent = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <span className="meter-row">
      <span className="meter" role="img" aria-label={`${t("ui.confidence")} ${percent}%`}><span style={{ width: `${percent}%` }} /></span>
      <span className="fc-muted" aria-hidden>{percent}%</span>
    </span>
  );
}

export function Empty({ icon = "searchX", title, text, action }: { icon?: string; title: string; text?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-icon"><Icon name={icon} size="lg" /></div>
      <p className="empty-title">{title}</p>
      {text ? <p className="empty-text">{text}</p> : null}
      {action ?? null}
    </div>
  );
}
