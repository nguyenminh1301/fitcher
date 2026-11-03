// ChartSpec + Result -> an ECharts option (DECISIONS §8). The only file that knows ECharts' option
// shape, so switching chart library rewrites this adapter only. Pure: no DOM, no network.

import type { OrientedChartSpec } from "@/lib/api/provisional";
import type { ChartType } from "@/lib/contracts";
import type { ColumnInfo, Result } from "@/lib/contracts";
import { formatNumber, type Locale } from "@/lib/i18n";

export const CHART_TYPES: ChartType[] = ["grouped_bar", "bar", "line", "pie", "scatter", "kpi", "table"];

/** The interface string that explains why a type does not suit a result. */
export const UNSUITABLE_REASON: Record<ChartType, string> = {
  grouped_bar: "ui.r_grouped", bar: "ui.r_bar", line: "ui.r_line", pie: "ui.r_donut_series", scatter: "ui.r_scatter", kpi: "ui.r_kpi", table: "ui.r_bar",
};

type Row = Record<string, unknown>;

function records(result: Result): Row[] {
  return result.rows.map((row) => Object.fromEntries(result.columns.map((column, index) => [column.name, row[index]])));
}

/** A cell for people: numbers by the column's format in the interface language, the rest as text. */
export function formatCell(value: unknown, column: Pick<ColumnInfo, "type" | "format"> | undefined, locale: Locale): string {
  if (value === null || value === undefined) return "";
  if (typeof value !== "number") return String(value);
  switch (column?.format) {
    case "percent":
      return `${formatNumber(value, locale, { maximumFractionDigits: 2 })}%`;
    case "ratio":
      return `${formatNumber(value * 100, locale, { maximumFractionDigits: 2 })}%`;
    case "currency":
      return formatNumber(value, locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    case "count":
      return formatNumber(value, locale, { maximumFractionDigits: 0 });
    default:
      return formatNumber(value, locale);
  }
}

/** An axis tick: compact (2.1M) to three significant digits, so small values (0.25) stay distinct; percentages and ratios keep their % sign. */
export function formatTick(value: number, column: Pick<ColumnInfo, "type" | "format"> | undefined, locale: Locale): string {
  if (column?.format === "percent" || column?.format === "ratio") return formatCell(value, column, locale);
  return formatNumber(value, locale, { notation: "compact", maximumSignificantDigits: 3 });
}

// The comparison series is grey with a 45° hatch, so the pair differs in lightness and texture.
const HATCH = { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [2, 4], rotation: Math.PI / 4, color: "rgba(107, 107, 112, 0.6)" };
const MARKERS = ["circle", "rect", "triangle", "diamond", "pin", "arrow"];
const DASHES = ["solid", "dashed", "dotted", "dashed", "dotted", "solid"];

function seriesStyle(index: number, palette: string[]) {
  const color = palette[index % palette.length];
  return index === 1 ? { color, decal: HATCH, borderColor: "#6b6b70", borderWidth: 1 } : { color };
}

/** The ECharts option for ``spec`` over ``result``; null for a KPI or a table, which are not ECharts charts. */
export function toEChartsOption(spec: OrientedChartSpec, result: Result, palette: string[], locale: Locale, gridColor = "#ececee"): Record<string, unknown> | null {
  if (spec.type === "kpi" || spec.type === "table") return null;
  const columns = Object.fromEntries(result.columns.map((column) => [column.name, column]));
  let rows = records(result);
  const measure = columns[spec.y[0]];
  const valueLabel = { formatter: (value: number) => formatTick(value, measure, locale) };

  if (spec.type === "pie") {
    return {
      tooltip: { trigger: "item" },
      legend: { bottom: 0 },
      series: [{
        type: "pie",
        radius: ["50%", "75%"],
        data: rows.map((row, index) => ({ name: String(row[spec.x]), value: row[spec.y[0]], itemStyle: seriesStyle(index, palette) })),
        label: { formatter: (item: { name: string; value: number }) => `${item.name}: ${formatCell(item.value, measure, locale)}` },
      }],
    };
  }

  if (spec.type === "scatter") {
    return {
      tooltip: { trigger: "item" },
      xAxis: { type: "value", name: spec.x, axisLabel: { formatter: (value: number) => formatTick(value, columns[spec.x], locale) } },
      yAxis: { type: "value", name: spec.y[0], axisLabel: valueLabel },
      series: [{ type: "scatter", data: rows.map((row) => [row[spec.x], row[spec.y[0]]]), itemStyle: seriesStyle(0, palette) }],
    };
  }

  if (spec.sort) {
    const key = spec.y[0];
    const direction = spec.sort === "asc" ? 1 : -1;
    rows = [...rows].sort((a, b) => direction * ((a[key] as number) - (b[key] as number)));
  }

  let categories: string[];
  let series: { name: string; data: unknown[] }[];
  if (spec.series) {
    categories = [...new Set(rows.map((row) => String(row[spec.x])))];
    const groups = [...new Set(rows.map((row) => String(row[spec.series as string])))].sort();
    series = groups.map((group) => ({
      name: group,
      data: categories.map((category) => rows.find((row) => String(row[spec.x]) === category && String(row[spec.series as string]) === group)?.[spec.y[0]] ?? null),
    }));
  } else {
    categories = rows.map((row) => String(row[spec.x]));
    series = spec.y.map((name) => ({ name, data: rows.map((row) => row[name]) }));
  }

  const kind = spec.type === "line" ? "line" : "bar";
  const horizontal = kind === "bar" && spec.orientation === "horizontal";
  const categoryAxis = { type: "category", data: categories, axisLabel: { hideOverlap: true } };
  const valueAxis = { type: "value", axisLabel: valueLabel, splitLine: { lineStyle: { color: gridColor } } };
  return {
    tooltip: { trigger: "axis", valueFormatter: (value: number) => formatCell(value, measure, locale) },
    legend: series.length > 1 ? { bottom: 0 } : undefined,
    grid: { left: 8, right: 16, top: 16, bottom: series.length > 1 ? 40 : 8, containLabel: true },
    xAxis: horizontal ? valueAxis : categoryAxis,
    yAxis: horizontal ? { ...categoryAxis, inverse: true } : valueAxis,
    series: series.map((item, index) => ({
      ...item,
      type: kind,
      itemStyle: seriesStyle(index, palette),
      ...(kind === "line" ? { lineStyle: { type: DASHES[index % DASHES.length] }, symbol: MARKERS[index % MARKERS.length], symbolSize: 7 } : {}),
    })),
  };
}

/** The result as CSV: a header row, then one line per row; commas, quotes and line breaks are quoted. */
export function toCsv(result: Result): string {
  const quote = (value: unknown) => {
    const text = value === null || value === undefined ? "" : String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [result.columns.map((column) => quote(column.name)).join(","), ...result.rows.map((row) => row.map(quote).join(","))].join("\n");
}

/** Start a download of ``blob`` as ``name`` in the browser. */
export function download(blob: Blob, name: string): void {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  document.body.appendChild(link);
  link.click();
  setTimeout(() => {
    URL.revokeObjectURL(link.href);
    link.remove();
  }, 0);
}
