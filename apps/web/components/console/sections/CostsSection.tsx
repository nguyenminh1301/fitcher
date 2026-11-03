"use client";

// Costs (DECISIONS §10, §15): estimated LLM spend by day, model alias and model, in the chat's chart
// style. Every figure is labelled as an estimate: it comes from token counts and list prices.

import { useCallback } from "react";

import { ChartView } from "@/components/chat/ChartView";
import { ListPage } from "@/components/console/ListPage";
import { StatusPill, WarningBanner } from "@/components/ui/feedback";
import type { CostRow } from "@/lib/api/provisional";
import type { ChartSpec, ChartType } from "@/lib/contracts";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import type { Result } from "@/lib/contracts";
import { useI18n } from "@/lib/i18n/react";

import { useUsd } from "./RunsSection";

/** Cost summed by one column of the cost rows, as a query result the chart can draw. */
function costBy(rows: CostRow[], key: "day" | "alias" | "model", time: boolean): Result {
  const totals = new Map<string, number>();
  for (const row of rows) totals.set(row[key], (totals.get(row[key]) ?? 0) + row.cost_usd);
  const entries = [...totals.entries()].sort(time ? ([a], [b]) => a.localeCompare(b) : ([, a], [, b]) => b - a);
  return {
    columns: [
      { name: key, type: time ? "date" : "string", role: time ? "time" : "dimension" },
      { name: "cost_usd", type: "number", role: "measure", format: "currency" },
    ],
    rows: entries.map(([name, cost]) => [name, Math.round(cost * 100) / 100]),
    row_count: entries.length,
  };
}

function CostChart({ title, result, type }: { title: string; result: Result; type: ChartType }) {
  const spec: ChartSpec = { type, x: result.columns[0].name, y: ["cost_usd"], allowed_types: [type] };
  return (
    <section className="fc-card" aria-label={title}>
      <div className="fc-card-head">
        <h2 className="fc-card-title">{title}</h2>
        <span style={{ marginRight: "var(--base-size-8)" }}><StatusPill status="estimate" /></span>
      </div>
      <div style={{ padding: "var(--base-size-16)" }}><ChartView spec={spec} result={result} /></div>
    </section>
  );
}

export function CostsSection() {
  const { t, formatNumber } = useI18n();
  const { api } = useChat();
  const usd = useUsd();
  const { data, failed } = useLoad(useCallback(async () => ({ costs: await api.costs.list(), runs: await api.runs.list() }), [api]));
  const costs = data?.costs ?? [];
  const total = costs.reduce((sum, row) => sum + row.cost_usd, 0);
  const runs = data?.runs.length ?? 0;
  const stat = (label: string, value: string, estimate: boolean) => (
    <div className="fc-card fc-stat">
      <span className="fc-stat-label">{label}{estimate ? <StatusPill status="estimate" /> : null}</span>
      <span className="fc-stat-value">{value}</span>
    </div>
  );
  return (
    <ListPage section="costs" loading={!data} failed={failed} skeleton="page">
      <WarningBanner tone="info">{t("ui.costsNote")}</WarningBanner>
      <div className="fc-stat-grid">
        {stat(t("ui.costTotal"), usd(total, 2), true)}
        {stat(t("ui.runsTotal"), formatNumber(runs), false)}
        {stat(t("ui.avgCost"), runs ? usd(total / runs) : "—", true)}
      </div>
      {costs.length ? (
        <>
          <CostChart title={t("ui.costByDay")} result={costBy(costs, "day", true)} type="line" />
          <div className="fc-chart-grid">
            <CostChart title={t("ui.costByModel")} result={costBy(costs, "model", false)} type="pie" />
            <CostChart title={t("ui.costByAlias")} result={costBy(costs, "alias", false)} type="bar" />
          </div>
        </>
      ) : null}
    </ListPage>
  );
}
