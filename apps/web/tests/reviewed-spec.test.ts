import { describe, expect, it } from "vitest";

import { parseSpec, specFields } from "@/lib/console/reviewedSpec";
import type { ReviewedSpec } from "@/lib/contracts";

const FIELDS = { metrics: "total", dataset: "lines", dimensions: "buyer, region", filters: "", topN: "10", rankBy: "total" };

describe("reviewed spec fields", () => {
  it("parses lists, filter lines and the top N", () => {
    const parsed = parseSpec({ ...FIELDS, filters: "region = West\ncategory in A, B C\nstatus not in cancelled" });

    expect(parsed).toEqual({ spec: {
      metric_ids: ["total"], dataset: "lines", dimensions: ["buyer", "region"], top_n: 10, rank_by: "total",
      filters: [
        { column: "region", op: "=", values: ["West"] },
        { column: "category", op: "in", values: ["A", "B C"] },
        { column: "status", op: "not in", values: ["cancelled"] },
      ],
    } });
  });

  it("names the part that does not parse", () => {
    expect(parseSpec({ ...FIELDS, filters: "region West" })).toEqual({ error: "region West" });
    expect(parseSpec({ ...FIELDS, topN: "ten" })).toEqual({ error: "ten" });
    expect(parseSpec({ ...FIELDS, metrics: " " })).toEqual({ error: " " });
  });

  it("round-trips a spec through the fields", () => {
    const spec: ReviewedSpec = { metric_ids: ["a"], dataset: "d", dimensions: [], filters: [{ column: "c", op: "in", values: ["x", "y"] }], top_n: null, rank_by: null };

    expect(parseSpec(specFields(spec))).toEqual({ spec });
  });
});
