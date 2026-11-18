"use client";

// A short animated walkthrough of creating an OpenRouter key, shown under the key field so nobody has to leave
// the setup for a help page. A plain drawing of a browser marks what to click at each step; it is not
// OpenRouter's own page, and its labels stay in English like the site's. The steps advance on their own unless
// the person pauses them, picks one, or asked the system for reduced motion.

import { useEffect, useState } from "react";

import { Icon } from "@/components/brand/Icon";
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

function Screen({ step }: { step: Step }) {
  if (step === "signIn") {
    return <><div><span className="fc-btn fc-btn-sm guide-ring">Sign in</span></div><span className="sk" /><span className="sk" /><span className="sk" /></>;
  }
  if (step === "keys") return <><span>API Keys</span><span className="sk" /><span className="sk" /></>;
  if (step === "create") {
    return (
      <>
        <span>Create key</span>
        <span className="fc-input fc-input-sm">fitcher</span>
        <span className="fc-input fc-input-sm">Credit limit (empty)</span>
        <span className="fc-btn fc-btn-primary fc-btn-sm guide-ring">Create</span>
      </>
    );
  }
  return (
    <>
      <span>Your new key</span>
      <span className="guide-key"><span className="fc-input fc-input-sm fc-mono">sk-or-v1-••••••••••••</span><span className="fc-btn fc-btn-sm guide-ring">Copy</span></span>
      <span className="fc-muted">Shown only once</span>
    </>
  );
}

export function OpenRouterKeyGuide({ intervalMs = 3500 }: { intervalMs?: number }) {
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
    <section className="guide" aria-label={t("guide.title")}>
      <div className="guide-bar"><span className="fc-sr">{t("guide.browser")}</span><span className="guide-url">{ADDRESS[step]}</span></div>
      <div className="guide-view" aria-hidden="true">
        <div className="guide-side">
          <span>Home</span><span>Models</span><span>Settings</span><span className={step === "keys" ? "guide-ring" : undefined}>Keys</span>
        </div>
        <div className="guide-main" key={step}><Screen step={step} /></div>
      </div>
      <p className="guide-caption" aria-live="polite">{t("guide.caption", { n: index + 1, text: t(`guide.step_${step}`) })}</p>
      <div className="guide-foot">
        <button type="button" className="fc-btn fc-btn-ghost fc-btn-icon fc-btn-sm" aria-label={playing ? t("guide.pause") : t("guide.play")}
          onClick={() => setPlaying(!playing)}>
          <Icon name={playing ? "pause" : "play"} />
        </button>
        <div className="guide-dots" role="group" aria-label={t("guide.pick")}>
          {STEPS.map((id, position) => (
            <button key={id} type="button" className="guide-dot" aria-current={position === index ? "step" : undefined}
              aria-label={`${t("guide.stepN", { n: position + 1 })}: ${t(`guide.step_${id}`)}`} onClick={() => pick(position)}>
              {position + 1}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
