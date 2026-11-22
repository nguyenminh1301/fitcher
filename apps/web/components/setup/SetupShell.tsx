"use client";

// The frame of the first-run setup: the logo, a bar per step (an answered step is a button that opens it
// again) and the language switch on the grey page, and the step itself on a paper panel.

import type { ReactNode } from "react";

import { Logo } from "@/components/brand/Logo";
import { Preferences } from "@/components/ui/Preferences";
import { cx } from "@/lib/cx";
import { useI18n } from "@/lib/i18n/react";

export type ShellStep = { id: string; state: "done" | "current" | "todo"; onOpen?: () => void };

export function SetupShell({ steps, wide = false, children }: { steps: ShellStep[]; wide?: boolean; children: ReactNode }) {
  const { t } = useI18n();
  const at = steps.findIndex((step) => step.state === "current");
  return (
    <div className="fc-app ob">
      <header className="ob-top">
        <Logo height={20} />
        <div className="ob-progress">
        <ol className="ob-steps" aria-label={t("onboarding.progress")}>
          {steps.map((step, index) => {
            const name = t("onboarding.stepLabel", { n: index + 1, name: t(`onboarding.step_${step.id}`) });
            return (
              <li key={step.id} data-state={step.state} aria-current={step.state === "current" ? "step" : undefined}>
                {step.state === "done" && step.onOpen ? (
                  <button type="button" className="ob-step" title={name}
                    aria-label={t("onboarding.reopenStep", { name: t(`onboarding.step_${step.id}`) })} onClick={step.onOpen}>
                    <span />
                  </button>
                ) : <span className="fc-sr">{name}</span>}
              </li>
            );
          })}
        </ol>
        {/* The bars alone do not say which step this is; its name is shown under them. */}
        {at >= 0 ? (
          <span className="ob-progress-name" aria-hidden="true">
            {t("onboarding.stepOf", { n: at + 1, total: steps.length })} · {t(`onboarding.step_${steps[at].id}`)}
          </span>
        ) : null}
        </div>
        <div className="ob-top-end"><Preferences languageOnly /></div>
      </header>
      <main className="ob-panel">
        <div className={cx("ob-col", wide && "ob-col-wide")}>{children}</div>
      </main>
    </div>
  );
}

/** The centred icon tile, title and one-line explanation at the top of a step. */
export function StepHead({ icon, title, children, tone }: { icon: ReactNode; title: string; children?: ReactNode; tone?: "success" }) {
  return (
    <div className="ob-head">
      <div className={cx("ob-tile", tone === "success" && "ob-tile-success")}>{icon}</div>
      <h1 className="ob-title">{title}</h1>
      {children ? <p className="ob-sub">{children}</p> : null}
    </div>
  );
}
