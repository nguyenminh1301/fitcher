// @vitest-environment node
// Without a DOM, ECharts measures text with its own estimate instead of a canvas jsdom cannot provide.
import { describe, expect, it } from "vitest";

import { echarts } from "@/lib/chart/echarts";
import { toEChartsOption } from "@/lib/chart/toEChartsOption";
import type { ChartSpec, Result } from "@/lib/contracts";

const PALETTE = ["#0969da", "#c9c9cf", "#bc4c00", "#1a7f37", "#8250df", "#bf3989"];
const RESULT: Result = {
  columns: [
    { name: "month", type: "string", role: "dimension" },
    { name: "sales_2025", type: "number", role: "measure", format: "currency", label: "Sales 2025" },
    { name: "sales_2024", type: "number", role: "measure", format: "currency" },
  ],
  rows: [["Jan", 10, 8], ["Feb", 30, 20], ["Mar", 20, 25]],
  row_count: 3,
};

/** Draw ``spec`` with the trimmed build as the server-side SVG renderer does, and return the SVG text. */
function draw(spec: ChartSpec): string {
  const chart = echarts.init(null, null, { renderer: "svg", ssr: true, width: 600, height: 300 });
  try {
    chart.setOption({ ...toEChartsOption(spec, RESULT, PALETTE, "en"), animation: false });
    return chart.renderToSVGString();
  } finally {
    chart.dispose();
  }
}

describe("the trimmed ECharts build", () => {
  it.each([
    ["bar", { type: "bar", x: "month", y: ["sales_2025"], orientation: "vertical" }],
    ["grouped bar with the hatched comparison", { type: "bar", x: "month", y: ["sales_2025", "sales_2024"], orientation: "horizontal" }],
    ["line", { type: "line", x: "month", y: ["sales_2025", "sales_2024"] }],
    ["pie", { type: "pie", x: "month", y: ["sales_2025"] }],
    ["scatter", { type: "scatter", x: "sales_2024", y: ["sales_2025"] }],
  ])("draws a %s chart", (_, partial) => {
    const svg = draw({ allowed_types: ["bar", "line", "pie", "scatter", "table"], ...partial } as ChartSpec);
    expect((svg.match(/<path/g) ?? []).length).toBeGreaterThan(3);
    if (partial.type !== "scatter") expect(svg).toContain("Jan");
  });

  it("names a series after the metric's display name in the legend", () => {
    expect(draw({ type: "line", x: "month", y: ["sales_2025", "sales_2024"], allowed_types: ["line"] } as ChartSpec)).toContain("Sales 2025");
  });
});
