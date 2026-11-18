"use client";

// Costs (DECISIONS §10, §15): the estimated model spend for the last 24 hours, 7 days or 30 days, as totals,
// one bar per day, and tables by task and by model. Every figure is an estimate from token counts and list
// prices; the provider's invoice is the exact amount, and the page says so.

import { useCallback, useMemo, useState } from "react";

import { allRuns } from "@/components/console/sections/OverviewSection";
import { ListPage } from "@/components/console/ListPage";
import { Segmented } from "@/components/ui/controls";
import type { CostRow } from "@/lib/contracts";
import { useChat } from "@/lib/chat/ChatContext";
import { useLoad } from "@/lib/console/useLoad";
import { useI18n } from "@/lib/i18n/react";

import { useUsd } from "./RunsSection";

type Range = "24h" | "7d" | "30d";
const DAYS: Record<Range, number> = { "24h": 1, "7d": 7, "30d": 30 };

function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function sum<T extends string>(rows: CostRow[], key: (row: CostRow) => T): [T, { cost: number; calls: number }][] {
  const totals = new Map<T, { cost: number; calls: number }>();
  for (const row of rows) {
    const current = totals.get(key(row)) ?? { cost: 0, calls: 0 };
    totals.set(key(row), { cost: current.cost + row.cost_usd, calls: current.calls + row.calls });
  }
  return [...totals.entries()].sort(([, a], [, b]) => b.cost - a.cost);
}

function Bars({ days, label }: { days: [string, number][]; label: string }) {
  const { formatNumber } = useI18n();
  const max = Math.max(...days.map(([, cost]) => cost), 0);
  const top = max > 0 ? max : 1;
  const ticks = [top, (top * 2) / 3, top / 3, 0];
  return (
    <div className="bars" role="img" aria-label={label}>
      <div className="bars-y" aria-hidden="true">{ticks.map((tick, index) => <span key={index}>{formatNumber(tick, { maximumFractionDigits: tick < 1 ? 2 : 0 })}</span>)}</div>
      <div className="bars-plot">
        {days.map(([day, cost]) => <span key={day} title={`${day}: ${formatNumber(cost, { maximumFractionDigits: 4 })}`} style={{ height: `${(cost / top) * 100}%` }} />)}
      </div>
      <div className="bars-x" aria-hidden="true">{days.map(([day]) => <span key={day}>{Number(day.slice(8, 10))}</span>)}</div>
    </div>
  );
}

export function CostsSection() {
  const { t, formatNumber } = useI18n();
  const { api } = useChat();
  const usd = useUsd();
  const [range, setRange] = useState<Range>("7d");
  const [today] = useState(() => new Date());
  const from30 = isoDay(new Date(today.getTime() - 29 * 86_400_000));
  const { data, failed } = useLoad(useCallback(async () => ({ costs: await api.costs.list(), runs: await allRuns(api, from30) }), [api, from30]));

  const start = isoDay(new Date(today.getTime() - (DAYS[range] - 1) * 86_400_000));
  const costs = useMemo(() => (data?.costs ?? []).filter((row) => row.day >= start), [data, start]);
  const runs = (data?.runs ?? []).filter((run) => run.ts.slice(0, 10) >= start).length;
  const total = costs.reduce((total_, row) => total_ + row.cost_usd, 0);
  // One bar per day of the period, a day without calls included.
  const days: [string, number][] = Array.from({ length: DAYS[range] }, (_, index) => {
    const day = isoDay(new Date(today.getTime() - (DAYS[range] - 1 - index) * 86_400_000));
    return [day, costs.filter((row) => row.day === day).reduce((total_, row) => total_ + row.cost_usd, 0)];
  });

  return (
    <ListPage section="costs" loading={!data} failed={failed} skeleton="page"
      actions={<Segmented label={t("overview.period")} value={range} onChange={(value) => setRange(value as Range)}
        options={[["24h", t("overview.range_24h")], ["7d", t("overview.range_7d")], ["30d", t("overview.range_30d")]]} />}>
      <section className="stats stats-3" aria-label={t("costsPage.totals")}>
        <div className="stat"><span className="stat-label">{t("overview.cost")}</span><span className="stat-value">{usd(total, 2)}</span></div>
        <div className="stat"><span className="stat-label">{t("costsPage.runs")}</span><span className="stat-value">{formatNumber(runs)}</span></div>
        <div className="stat"><span className="stat-label">{t("ui.avgCost")}</span><span className="stat-value">{runs ? usd(total / runs) : "—"}</span></div>
      </section>
      <section className="box" aria-labelledby="by-day-title">
        <div className="box-head"><h2 id="by-day-title" className="box-title">{t("costsPage.byDay")}</h2></div>
        <div className="box-pad"><Bars days={days} label={t("costsPage.byDayLabel", { n: DAYS[range] })} /></div>
      </section>
      <div className="split">
        <div className="split-main">
          <section className="box" aria-labelledby="by-task-title">
            <div className="box-head"><h2 id="by-task-title" className="box-title">{t("costsPage.byTask")}</h2></div>
            <table className="tbl">
              <thead><tr><th>{t("modelsPage.task")}</th><th className="num">{t("costsPage.calls")}</th><th className="num">{t("overview.cost")}</th></tr></thead>
              <tbody>
                {sum(costs, (row) => row.tier || row.alias).map(([tier, value]) => (
                  <tr key={tier}><td><span className="fc-mono">{tier}</span></td><td className="num">{formatNumber(value.calls)}</td><td className="num">{usd(value.cost, 2)}</td></tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
        <div className="split-side">
          <section className="box" aria-labelledby="by-model-title">
            <div className="box-head"><h2 id="by-model-title" className="box-title">{t("costsPage.byModel")}</h2></div>
            <table className="tbl">
              <thead><tr><th>{t("models.tierModel")}</th><th className="num">{t("overview.cost")}</th></tr></thead>
              <tbody>
                {sum(costs, (row) => row.model).map(([model, value]) => (
                  <tr key={model}><td><span className="fc-mono">{model}</span></td><td className="num">{usd(value.cost, 2)}</td></tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      </div>
      <p className="fc-field-help" style={{ margin: 0 }}>{t("ui.costsNote")}</p>
    </ListPage>
  );
}
