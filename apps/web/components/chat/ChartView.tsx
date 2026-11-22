"use client";

// Draws a ChartSpec with ECharts, in the design's data colours read from the theme tokens; a KPI is a
// large number. Charts are images with a description; the data table below is their accessible equivalent.

import type { EChartsInstance, EChartsReactProps } from "echarts-for-react";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import { formatCell, toEChartsOption } from "@/lib/chart/toEChartsOption";
import type { ChartSpec, Result } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

// The chart component and the trimmed ECharts build load together, only when a chart is drawn.
const ReactECharts = dynamic(async () => {
  const [{ default: EChartsCore }, { echarts }] = await Promise.all([import("echarts-for-react/lib/core"), import("@/lib/chart/echarts")]);
  return function Chart(props: Omit<EChartsReactProps, "echarts">) {
    return <EChartsCore echarts={echarts} {...props} />;
  };
}, { ssr: false });

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

/**
 * The page's font family once its web fonts have loaded. ECharts measures axis labels with this name to leave room
 * for them; "inherit" is not a font it can measure, so it measured with a default font and a long label drawn in
 * Inter ran past the chart's left edge.
 */
function useFontFamily(): string {
  const [family, setFamily] = useState("sans-serif");
  useEffect(() => {
    let live = true;
    const read = () => { if (live) setFamily(getComputedStyle(document.body).fontFamily || "sans-serif"); };
    read();
    void document.fonts?.ready.then(read);
    return () => { live = false; };
  }, []);
  return family;
}

export function ChartView({ spec, result, onReady }: { spec: ChartSpec; result: Result; onReady?: (chart: EChartsInstance) => void }) {
  const { t, locale } = useI18n();
  const { palette, grid } = usePalette();
  const fontFamily = useFontFamily();

  if (spec.type === "kpi") {
    const column = result.columns.find((item) => item.name === spec.y[0]) ?? result.columns[0];
    const value = result.rows[0]?.[result.columns.indexOf(column)];
    return (
      <div className="fc-kpi" role="img" aria-label={`${column.label ?? column.name}: ${formatCell(value, column, locale)}`}>
        <div className="fc-kpi-value fc-num">{formatCell(value, column, locale)}</div>
        <div className={column.label ? "fc-kpi-label" : "fc-kpi-label fc-mono"} title={column.name}>{column.label ?? column.name}</div>
      </div>
    );
  }
  const option = toEChartsOption(spec, result, palette, locale, grid);
  if (!option) return null;
  const description = t("ui.chartAria", { type: spec.type, cols: [spec.x, ...spec.y].filter(Boolean).join(", ") });
  return (
    <div role="img" aria-label={description} style={{ width: "100%" }}>
      <ReactECharts
        option={{ ...option, textStyle: { fontFamily }, animationDuration: 300 }}
        notMerge
        style={{ height: 300, width: "100%" }}
        opts={{ renderer: "svg" }}
        onChartReady={onReady}
      />
    </div>
  );
}
