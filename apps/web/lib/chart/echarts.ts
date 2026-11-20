// The ECharts build the app uses: the core with only the charts, components and renderers it draws, instead of the
// full library (about a third of its size). The chat draws with the SVG renderer; the PNG export redraws the same
// option on a canvas (chartPng.ts).

import { BarChart, LineChart, PieChart, ScatterChart } from "echarts/charts";
import { AriaComponent, GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { LabelLayout } from "echarts/features";
import { CanvasRenderer, SVGRenderer } from "echarts/renderers";

echarts.use([
  BarChart, LineChart, PieChart, ScatterChart, AriaComponent, GridComponent, LegendComponent, TooltipComponent,
  LabelLayout, CanvasRenderer, SVGRenderer,
]);

export { echarts };
