"use client";

import { useRef, type KeyboardEvent } from "react";

import { Icon } from "@/components/brand/Icon";
import { Tooltip } from "@/components/ui/feedback";
import type { ChartType } from "@/lib/contracts";
import { CHART_TYPES, UNSUITABLE_REASON } from "@/lib/chart/toEChartsOption";
import { useI18n } from "@/lib/i18n/react";

const ICON: Record<ChartType, string> = { grouped_bar: "chartGrouped", bar: "chartBar", line: "chartLine", pie: "chartPie", scatter: "chartScatter", kpi: "hash", table: "table" };
// The interface calls the contract's `pie` a donut (DECISIONS §8).
const LABEL: Record<ChartType, string> = { grouped_bar: "ui.t_grouped_bar", bar: "ui.t_bar", line: "ui.t_line", pie: "ui.t_donut", scatter: "ui.t_scatter", kpi: "ui.t_kpi", table: "ui.t_table" };

/** Every chart type, the unsuitable ones visible but disabled with the reason; switching never calls the api. */
export function TypeSwitcher({ value, allowed, onChange }: { value: ChartType; allowed: ChartType[]; onChange: (type: ChartType) => void }) {
  const { t } = useI18n();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  function onKey(event: KeyboardEvent, index: number) {
    const moves: Record<string, number> = {
      ArrowRight: (index + 1) % CHART_TYPES.length, ArrowDown: (index + 1) % CHART_TYPES.length,
      ArrowLeft: (index - 1 + CHART_TYPES.length) % CHART_TYPES.length, ArrowUp: (index - 1 + CHART_TYPES.length) % CHART_TYPES.length,
      Home: 0, End: CHART_TYPES.length - 1,
    };
    if (!(event.key in moves)) return;
    event.preventDefault();
    refs.current[moves[event.key]]?.focus();
  }
  return (
    <div className="fc-seg fc-seg-sm fc-seg-icon" role="radiogroup" aria-label={t("ui.chartType")}>
      {CHART_TYPES.map((type, index) => {
        const ok = type === "table" || allowed.includes(type);
        const label = t(LABEL[type]);
        return (
          <Tooltip key={type} label={ok ? label : `${label}: ${t(UNSUITABLE_REASON[type])}`}>
            <button
              ref={(element) => { refs.current[index] = element; }}
              type="button"
              role="radio"
              aria-checked={type === value}
              aria-disabled={ok ? undefined : true}
              aria-label={label}
              tabIndex={type === value ? 0 : -1}
              className="fc-seg-btn"
              onClick={() => ok && onChange(type)}
              onKeyDown={(event) => onKey(event, index)}
            >
              <Icon name={ICON[type]} />
            </button>
          </Tooltip>
        );
      })}
    </div>
  );
}
