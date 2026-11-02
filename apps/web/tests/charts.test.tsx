import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TypeSwitcher } from "@/components/chat/TypeSwitcher";
import { DataTable } from "@/components/chat/DataTable";
import type { ChartSpec } from "@/lib/api/provisional";
import { formatTick, toCsv, toEChartsOption } from "@/lib/chart/toEChartsOption";
import type { Result } from "@/lib/contracts";
import { I18nProvider } from "@/lib/i18n/react";

const PALETTE = ["#0969da", "#c9c9cf", "#bc4c00", "#1a7f37", "#8250df", "#bf3989"];
const BRANDS: Result = {
  columns: [
    { name: "brand", type: "string", role: "dimension" },
    { name: "sales_2025", type: "number", role: "measure", format: "currency" },
    { name: "sales_2024", type: "number", role: "measure", format: "currency" },
  ],
  rows: [["B", 10, 8], ["A", 30, 20], ["C", 20, 25]],
  row_count: 3,
};
const spec = (overrides: Partial<ChartSpec>): ChartSpec => ({ type: "bar", x: "brand", y: ["sales_2025"], allowed_types: ["bar", "table"], ...overrides });

type Axis = { type: string; data?: unknown[] };
type Option = { xAxis: Axis; yAxis: Axis; series: { type: string; data: unknown[]; radius?: string[]; itemStyle?: { color?: string; decal?: unknown }; lineStyle?: { type?: string }; symbol?: string }[] };
const option = (chart: ChartSpec, result: Result = BRANDS) => toEChartsOption(chart, result, PALETTE, "en") as unknown as Option;

describe("chart adapter", () => {
  it("draws a vertical bar on a category x axis", () => {
    const bar = option(spec({ orientation: "vertical" }));
    expect(bar.xAxis.type).toBe("category");
    expect(bar.series[0]).toMatchObject({ type: "bar" });
  });

  it("labels value-axis ticks compactly, without the cents a table shows", () => {
    const currency = BRANDS.columns[1];
    expect(formatTick(2_100_000, currency, "en")).toBe("2.1M");
    expect([0.05, 0.1, 0.15, 0.2, 0.25].map((value) => formatTick(value, currency, "en"))).toEqual(["0.05", "0.1", "0.15", "0.2", "0.25"]);
    expect(formatTick(0.25, { type: "number", format: "ratio" }, "en")).toBe("25%");
  });

  it("swaps the axes for a horizontal bar", () => {
    const bar = option(spec({ orientation: "horizontal" }));
    expect(bar.yAxis.type).toBe("category");
    expect(bar.xAxis.type).toBe("value");
  });

  it("sorts the categories the way the spec says", () => {
    expect(option(spec({ sort: "desc", orientation: "vertical" })).xAxis.data).toEqual(["A", "C", "B"]);
    expect(option(spec({ sort: "asc", orientation: "vertical" })).xAxis.data).toEqual(["B", "C", "A"]);
  });

  it("draws one series per measure for a grouped bar, the comparison grey with a hatch", () => {
    const grouped = option(spec({ type: "grouped_bar", y: ["sales_2025", "sales_2024"], orientation: "vertical" }));
    expect(grouped.series).toHaveLength(2);
    expect(grouped.series[0].itemStyle?.color).toBe(PALETTE[0]);
    expect(grouped.series[1].itemStyle?.color).toBe(PALETTE[1]);
    expect(grouped.series[1].itemStyle?.decal).toBeTruthy();
  });

  it("splits a grouped bar by the series column when the spec names one", () => {
    const long: Result = {
      columns: [{ name: "brand", type: "string", role: "dimension" }, { name: "period", type: "string", role: "dimension" }, { name: "sales", type: "number", role: "measure" }],
      rows: [["A", "2025", 1], ["A", "2024", 2], ["B", "2025", 3]],
      row_count: 3,
    };
    const grouped = option(spec({ type: "grouped_bar", y: ["sales"], series: "period", orientation: "vertical" }), long);
    expect(grouped.series.map((series) => series.data)).toEqual([[2, null], [1, 3]]);
  });

  it("tells lines apart by dash and marker as well as colour", () => {
    const line = option(spec({ type: "line", y: ["sales_2025", "sales_2024"] }));
    expect(line.series.map((series) => series.lineStyle?.type)).toEqual(["solid", "dashed"]);
    expect(line.series[0].symbol).not.toBe(line.series[1].symbol);
  });

  it("draws pie as a donut", () => {
    expect(option(spec({ type: "pie" })).series[0]).toMatchObject({ type: "pie", radius: ["50%", "75%"] });
  });

  it("draws scatter from two numeric columns", () => {
    const scatter = option(spec({ type: "scatter", x: "sales_2024", y: ["sales_2025"] }));
    expect(scatter.series[0].data).toEqual([[8, 10], [20, 30], [25, 20]]);
  });

  it("has no ECharts option for a KPI or a table", () => {
    expect(toEChartsOption(spec({ type: "kpi" }), BRANDS, PALETTE, "en")).toBeNull();
    expect(toEChartsOption(spec({ type: "table" }), BRANDS, PALETTE, "en")).toBeNull();
  });

  it("writes CSV with quoted commas, quotes and line breaks", () => {
    const tricky: Result = { columns: [{ name: "name", type: "string", role: "dimension" }, { name: "n", type: "number", role: "measure" }], rows: [['A, "B"\nC', 1]], row_count: 1 };
    expect(toCsv(tricky)).toBe('name,n\n"A, ""B""\nC",1');
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("type switcher", () => {
  it("switches the chart locally and never calls the network", () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const onChange = vi.fn();
    render(<I18nProvider><TypeSwitcher value="bar" allowed={["bar", "pie", "table"]} onChange={onChange} /></I18nProvider>);

    fireEvent.click(screen.getByRole("radio", { name: /Pie \/ donut/ }));

    expect(onChange).toHaveBeenCalledWith("pie");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps unsuitable types visible but disabled with the reason", () => {
    const onChange = vi.fn();
    render(<I18nProvider><TypeSwitcher value="bar" allowed={["bar", "table"]} onChange={onChange} /></I18nProvider>);

    const line = screen.getByRole("radio", { name: "Line" });
    fireEvent.click(line);

    expect(line.getAttribute("aria-disabled")).toBe("true");
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("tooltip", { name: /Line needs a date or ordered axis/ })).toBeTruthy();
  });
});

describe("data table", () => {
  const many: Result = {
    columns: [{ name: "id", type: "number", role: "dimension" }],
    rows: Array.from({ length: 45 }, (_, i) => [i + 1]),
    row_count: 120,
    truncated: true,
  };

  it("shows 20 rows a page and says when the result was cut", () => {
    render(<I18nProvider><DataTable result={many} /></I18nProvider>);

    expect(screen.getAllByRole("row")).toHaveLength(21);
    expect(screen.getByText("Showing first 45 of 120 rows")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("21")).toBeTruthy();
  });

  it("sorts by a column when its header is clicked", () => {
    render(<I18nProvider><DataTable result={BRANDS} /></I18nProvider>);

    fireEvent.click(screen.getByRole("button", { name: /brand/ }));

    const cells = screen.getAllByRole("row").slice(1).map((row) => row.querySelector("td")?.textContent);
    expect(cells).toEqual(["A", "B", "C"]);
  });
});
