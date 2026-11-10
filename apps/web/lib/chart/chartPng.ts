// A drawn chart as a PNG file. Charts are drawn with the SVG renderer, whose own export is an SVG
// document whatever type is asked for, so the chart's option is drawn once more on an off-screen canvas.

import type { EChartsInstance } from "echarts-for-react";

/** The PNG of ``chart`` at its on-screen size times ``pixelRatio``, on ``background``, in the chart's own font. */
export async function chartPng(chart: EChartsInstance, background: string, pixelRatio = 2): Promise<Blob> {
  const echarts = await import("echarts");
  const canvasChart = echarts.init(document.createElement("div"), null, { renderer: "canvas", width: chart.getWidth(), height: chart.getHeight() });
  try {
    // "inherit" means nothing on a canvas, so the font the page resolved for the chart is named outright.
    const fontFamily = getComputedStyle(chart.getDom()).fontFamily;
    canvasChart.setOption({ ...chart.getOption(), animation: false, textStyle: { fontFamily } });
    const response = await fetch(canvasChart.getDataURL({ type: "png", pixelRatio, backgroundColor: background }));
    return await response.blob();
  } finally {
    canvasChart.dispose();
  }
}
