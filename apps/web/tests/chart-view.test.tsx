import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// The chart component loads on demand; here it only records the option ChartView hands to ECharts.
const drawn = vi.hoisted(() => ({ options: [] as Record<string, unknown>[] }));
vi.mock("next/dynamic", () => ({
  default: () => (props: { option: Record<string, unknown> }) => {
    drawn.options.push(props.option);
    return <div data-testid="echarts" />;
  },
}));

import { ChartView } from "@/components/chat/ChartView";
import { I18nProvider } from "@/lib/i18n/react";
import type { ChartSpec, Result } from "@/lib/contracts";

const RESULT: Result = {
  columns: [{ name: "item", type: "String", role: "dimension" }, { name: "amount", type: "Float64", role: "measure" }],
  rows: [["A long category name", 3], ["Short", 1]], row_count: 2, truncated: false,
} as unknown as Result;
const SPEC = { type: "bar", x: "item", y: ["amount"], orientation: "horizontal", allowed_types: ["bar"] } as unknown as ChartSpec;

window.matchMedia ??= ((query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} })) as never;

afterEach(() => {
  cleanup();
  document.body.style.fontFamily = "";
  drawn.options = [];
});

describe("chart view", () => {
  it("measures labels with the page's font family, not 'inherit'", async () => {
    document.body.style.fontFamily = "Inter, sans-serif";

    render(<I18nProvider initial="en"><ChartView spec={SPEC} result={RESULT} /></I18nProvider>);

    await waitFor(() => expect((drawn.options.at(-1)?.textStyle as { fontFamily: string }).fontFamily).toContain("Inter"));
    expect(drawn.options.every((option) => (option.textStyle as { fontFamily: string }).fontFamily !== "inherit")).toBe(true);
  });
});
