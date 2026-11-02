"use client";

import { cx } from "@/lib/cx";
import { useI18n } from "@/lib/i18n/react";

/** How sure the drafter was of a pack item: five segments, marked low below 70%. */
export function ConfidenceMeter({ value }: { value: number }) {
  const { t } = useI18n();
  const clamped = Math.max(0, Math.min(1, value));
  const percent = Math.round(clamped * 100);
  const on = Math.round(clamped * 5);
  return (
    <span className={cx("fc-conf", clamped < 0.7 && "fc-conf-low")} role="img" aria-label={`${t("ui.confidence")} ${percent}%`}>
      <span className="fc-conf-track" aria-hidden>
        {[0, 1, 2, 3, 4].map((index) => <span key={index} className="fc-conf-seg" data-on={index < on ? "true" : "false"} />)}
      </span>
      <span aria-hidden>{percent}%</span>
    </span>
  );
}
