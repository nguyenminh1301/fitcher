import type { EChartsInstance } from "echarts-for-react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { chartPng } from "@/lib/chart/chartPng";

// One transparent pixel, so the helper has a real PNG data URL to turn into a file.
const PNG_URL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";

const canvasChart = { setOption: vi.fn(), getDataURL: vi.fn(() => PNG_URL), dispose: vi.fn() };
const init = vi.fn((..._args: unknown[]) => canvasChart);
vi.mock("echarts", () => ({ init: (...args: unknown[]) => init(...args) }));

function drawnChart(): EChartsInstance {
  const dom = document.createElement("div");
  dom.style.fontFamily = "Inter";
  document.body.appendChild(dom);
  return { getWidth: () => 640, getHeight: () => 300, getDom: () => dom, getOption: () => ({ series: [{ type: "bar", data: [1, 2] }] }) } as unknown as EChartsInstance;
}

afterEach(() => {
  vi.clearAllMocks();
  document.body.innerHTML = "";
});

describe("chart png export", () => {
  it("draws the chart's option on a canvas of the same size and returns a PNG file", async () => {
    const blob = await chartPng(drawnChart(), "#ffffff");

    expect(init.mock.calls[0][2]).toEqual({ renderer: "canvas", width: 640, height: 300 });
    expect(canvasChart.setOption).toHaveBeenCalledWith({ series: [{ type: "bar", data: [1, 2] }], animation: false, textStyle: { fontFamily: "Inter" } });
    expect(canvasChart.getDataURL).toHaveBeenCalledWith({ type: "png", pixelRatio: 2, backgroundColor: "#ffffff" });
    expect(blob.type).toBe("image/png");
    expect(blob.size).toBeGreaterThan(0);
  });

  it("releases the off-screen chart even when drawing fails", async () => {
    canvasChart.setOption.mockImplementationOnce(() => {
      throw new Error("bad option");
    });

    await expect(chartPng(drawnChart(), "#ffffff")).rejects.toThrow("bad option");
    expect(canvasChart.dispose).toHaveBeenCalledTimes(1);
  });
});
