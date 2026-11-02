"use client";

// Draws a ChartSpec with ECharts, in the design's data colours read from the theme tokens; a KPI is a
// large number. Charts are images with a description; the data table below is their accessible equivalent.

import type { EChartsInstance } from "echarts-for-react";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import type { ChartSpec } from "@/lib/api/provisional";
import { formatCell, toEChartsOption } from "@/lib/chart/toEChartsOption";
import type { Result } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

const FALLBACK = ["#0969da", "#c9c9cf", "#bc4c00", "#1a7f37", "#8250df", "#bf3989"];

/** The series colours and the grid-line colour of the current theme, re-read when the theme changes. */
function usePalette(): { palette: string[]; grid: string } {
  const [palette, setPalette] = useState({ palette: FALLBACK, grid: "#ececee" });
  useEffect(() => {
    const read = () => {
      const styles = getComputedStyle(document.documentElement);
      setPalette({
        palette: FALLBACK.map((fallback, index) => styles.getPropertyValue(`--data-${index + 1}`).trim() || fallback),
        grid: styles.getPropertyValue("--borderColor-muted").trim() || "#ececee",
      });
    };
    read();
    const observer = new MutationObserver(read);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", read);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", read);
    };
  }, []);
  return palette;
}

export function ChartView({ spec, result, onReady }: { spec: ChartSpec; result: Result; onReady?: (chart: EChartsInstance) => void }) {
  const { t, locale } = useI18n();
  const { palette, grid } = usePalette();

  if (spec.type === "kpi") {
    const column = result.columns.find((item) => item.name === spec.y[0]) ?? result.columns[0];
    const value = result.rows[0]?.[result.columns.indexOf(column)];
    return (
      <div className="fc-kpi" role="img" aria-label={`${column.name}: ${formatCell(value, column, locale)}`}>
        <div className="fc-kpi-value fc-num">{formatCell(value, column, locale)}</div>
        <div className="fc-kpi-label fc-mono">{column.name}</div>
      </div>
    );
  }
  const option = toEChartsOption(spec, result, palette, locale, grid);
  if (!option) return null;
  const description = t("ui.chartAria", { type: spec.type, cols: [spec.x, ...spec.y].filter(Boolean).join(", ") });
  return (
    <div role="img" aria-label={description} style={{ width: "100%" }}>
      <ReactECharts
        option={{ ...option, textStyle: { fontFamily: "inherit" }, animationDuration: 300 }}
        notMerge
        style={{ height: 300, width: "100%" }}
        opts={{ renderer: "svg" }}
        onChartReady={onReady}
      />
    </div>
  );
}
