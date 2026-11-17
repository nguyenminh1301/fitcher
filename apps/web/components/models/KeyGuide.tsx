"use client";

// A short animated walkthrough of creating an OpenRouter key, shown next to the key field so nobody has to leave
// the setup for a help page. A small drawing of the OpenRouter pages marks what to click at each step; the steps
// advance on their own unless the person pauses them, picks one, or asked the system for reduced motion.

import { useEffect, useState } from "react";

import { Icon } from "@/components/brand/Icon";
import { Button } from "@/components/ui/controls";
import { useI18n } from "@/lib/i18n/react";

const STEPS = ["signIn", "keys", "create", "paste"] as const;
type Step = (typeof STEPS)[number];
const ADDRESS: Record<Step, string> = {
  signIn: "openrouter.ai",
  keys: "openrouter.ai/settings/keys",
  create: "openrouter.ai/settings/keys",
  paste: "openrouter.ai/settings/keys",
};

function reducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** The drawing of one step; its labels are OpenRouter's own and stay in English. */
function Screen({ step }: { step: Step }) {
  if (step === "signIn") {
    return (
      <div className="fc-guide-bar">
        <span className="fc-guide-brand">OpenRouter</span>
        <span className="fc-guide-chip">Models</span>
        <span className="fc-guide-chip fc-guide-target">Sign in</span>
      </div>
    );
  }
  if (step === "keys") {
    return (
      <div className="fc-guide-split">
        <ul className="fc-guide-nav">
          <li>Credits</li>
          <li className="fc-guide-target">Keys</li>
          <li>Activity</li>
          <li>Preferences</li>
        </ul>
        <div className="fc-guide-lines"><span /><span /><span /></div>
      </div>
    );
  }
  if (step === "create") {
    return (
      <div className="fc-guide-form">
        <span className="fc-guide-field">Name: fitcher</span>
        <span className="fc-guide-field fc-guide-muted">Credit limit: (empty)</span>
        <span className="fc-guide-button fc-guide-target">Create</span>
      </div>
    );
  }
  return (
    <div className="fc-guide-form">
      <span className="fc-guide-field fc-guide-mono">sk-or-v1-••••••••••••</span>
      <span className="fc-guide-button fc-guide-target"><Icon name="copy" /> Copy</span>
      <span className="fc-guide-arrow"><Icon name="arrowLeft" /> fitcher</span>
    </div>
  );
}

export function OpenRouterKeyGuide({ intervalMs = 4000 }: { intervalMs?: number }) {
  const { t } = useI18n();
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(() => !reducedMotion());
  const step = STEPS[index];

  useEffect(() => {
    if (!playing) return;
    const timer = setTimeout(() => setIndex((current) => (current + 1) % STEPS.length), intervalMs);
    return () => clearTimeout(timer);
  }, [playing, index, intervalMs]);

  const pick = (next: number) => { setPlaying(false); setIndex(next); };
  return (
    <section className="fc-guide" aria-label={t("guide.title")}>
      <div className="fc-guide-head">
        <strong>{t("guide.title")}</strong>
        <Button size="sm" variant="ghost" onClick={() => setPlaying(!playing)}>{playing ? t("guide.pause") : t("guide.play")}</Button>
      </div>
      <div className="fc-guide-window" aria-hidden="true">
        <div className="fc-guide-address"><Icon name="lock" /> {ADDRESS[step]}</div>
        <div className="fc-guide-screen" key={step}><Screen step={step} /></div>
      </div>
      <ol className="fc-guide-steps">
        {STEPS.map((id, position) => (
          <li key={id}>
            <button type="button" className="fc-guide-step" aria-current={position === index ? "step" : undefined} onClick={() => pick(position)}>
              <span className="fc-guide-num">{position + 1}</span>
              <span>{t(`guide.step_${id}`)}</span>
            </button>
          </li>
        ))}
      </ol>
      <p className="fc-field-help" style={{ margin: 0 }}>{t("guide.freeNote")}</p>
    </section>
  );
}
