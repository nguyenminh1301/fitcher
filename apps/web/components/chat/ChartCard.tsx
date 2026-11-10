"use client";

import type { EChartsInstance } from "echarts-for-react";
import { useRef } from "react";

import { Icon } from "@/components/brand/Icon";
import { Button } from "@/components/ui/controls";
import type { ChartSpec, ChartType } from "@/lib/contracts";
import { chartPng } from "@/lib/chart/chartPng";
import { download, toCsv } from "@/lib/chart/toEChartsOption";
import type { Result } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

import { ChartView } from "./ChartView";
import { DataTable } from "./DataTable";
import { TypeSwitcher } from "./TypeSwitcher";

type Props = { spec: ChartSpec; result: Result; type: ChartType; onType: (type: ChartType) => void; orientation: "vertical" | "horizontal"; onOrientation: (value: "vertical" | "horizontal") => void };

/** The chart of an answer with the type switcher and export; switching type or orientation is local. */
export function ChartCard({ spec, result, type, onType, orientation, onOrientation }: Props) {
  const { t } = useI18n();
  const chart = useRef<EChartsInstance | null>(null);
  const shown: ChartSpec = { ...spec, type, orientation: type === "bar" ? orientation : spec.orientation };

  function exportPng() {
    const instance = chart.current;
    if (!instance) return;
    const background = getComputedStyle(document.documentElement).getPropertyValue("--bgColor-default").trim() || "#ffffff";
    chartPng(instance, background)
      .then((blob) => download(blob, "fitcher-chart.png"))
      .catch(() => undefined);
  }

  return (
    <section className="fc-card fc-chartcard" aria-label={t("ui.chartType")}>
      <div className="fc-card-head">
        <span className="fc-spacer" />
        <div className="fc-row">
          <TypeSwitcher value={type} allowed={spec.allowed_types} onChange={onType} />
          {type === "table" ? (
            <Button variant="ghost" size="sm" iconOnly icon="download" label={t("ui.exportCsv")} onClick={() => download(new Blob([toCsv(result)], { type: "text/csv" }), "fitcher-result.csv")} />
          ) : type !== "kpi" ? (
            <Button variant="ghost" size="sm" iconOnly icon="download" label={t("ui.exportPng")} onClick={exportPng} />
          ) : null}
        </div>
      </div>
      {type === "bar" ? (
        <div className="fc-row" style={{ padding: "var(--base-size-12) var(--base-size-16) 0" }}>
          <div className="fc-seg fc-seg-sm fc-seg-icon" role="radiogroup" aria-label={t("ui.orientation")}>
            {(["horizontal", "vertical"] as const).map((value) => (
              <button key={value} type="button" role="radio" aria-checked={orientation === value} aria-label={t(`ui.${value}`)} title={t(`ui.${value}`)} className="fc-seg-btn" onClick={() => onOrientation(value)}>
                <Icon name={value === "horizontal" ? "chartBarH" : "chartBar"} />
              </button>
            ))}
          </div>
        </div>
      ) : null}
      <div style={{ padding: type === "table" ? 0 : "var(--base-size-16)" }}>
        {type === "table" ? <DataTable result={result} title={false} /> : <ChartView spec={shown} result={result} onReady={(instance) => (chart.current = instance)} />}
      </div>
    </section>
  );
}
