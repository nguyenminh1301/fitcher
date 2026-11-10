// The Review page edits a proposal's spec as plain text fields (DECISIONS §6 step 7): lists are comma-separated
// and each filter is one line, "column = value", "column != value", "column in a, b" or "column not in a, b".

import type { ReviewedSpec, SpecFilter } from "@/lib/contracts";

export type SpecFields = { metrics: string; dataset: string; dimensions: string; filters: string; topN: string; rankBy: string };

const FILTER = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s+(not in|in|!=|=)\s+(.+?)\s*$/i;
const list = (text: string) => text.split(",").map((part) => part.trim()).filter(Boolean);

export function specFields(spec: ReviewedSpec | null | undefined): SpecFields {
  return {
    metrics: (spec?.metric_ids ?? []).join(", "),
    dataset: spec?.dataset ?? "",
    dimensions: (spec?.dimensions ?? []).join(", "),
    filters: (spec?.filters ?? []).map((item) => `${item.column} ${item.op} ${item.values.join(", ")}`).join("\n"),
    topN: spec?.top_n == null ? "" : String(spec.top_n),
    rankBy: spec?.rank_by ?? "",
  };
}

/** The spec the fields describe, or the first line or field that does not parse. */
export function parseSpec(fields: SpecFields): { spec: ReviewedSpec } | { error: string } {
  const filters: SpecFilter[] = [];
  for (const line of fields.filters.split("\n").filter((text) => text.trim())) {
    const match = FILTER.exec(line);
    if (!match) return { error: line.trim() };
    const op = match[2].toLowerCase() as SpecFilter["op"];
    const values = op === "in" || op === "not in" ? list(match[3]) : [match[3]];
    const [value, ...more] = values;
    if (value === undefined) return { error: line.trim() };
    filters.push({ column: match[1], op, values: [value, ...more] });
  }
  const topN = fields.topN.trim();
  if (topN && !/^[1-9][0-9]*$/.test(topN)) return { error: topN };
  const [first, ...rest] = list(fields.metrics);
  if (first === undefined) return { error: fields.metrics };
  if (!fields.dataset.trim()) return { error: fields.dataset };
  return {
    spec: {
      metric_ids: [first, ...rest], dataset: fields.dataset.trim(), dimensions: list(fields.dimensions), filters,
      top_n: topN ? Number(topN) : null, rank_by: fields.rankBy.trim() || null,
    },
  };
}
