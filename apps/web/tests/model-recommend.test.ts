import { describe, expect, it } from "vitest";

import type { CatalogEntry } from "@/lib/contracts";
import { filtered, NO_FILTER, priceText, ranked, recommended, slowModel } from "@/lib/models/recommend";

function model(provider_id: string, id: string, change: Partial<CatalogEntry> = {}): CatalogEntry {
  return { id, provider_id, kind: "chat", free: "free_tier", input_price: null, output_price: null, context: null,
           structured_output: true, benchmark: null, median_latency_ms: null, ...change };
}

const MODELS = [
  model("gemini", "gemini-3.8-flash", { benchmark: 60 }),
  model("gemini", "gemini-flash-lite-latest", { benchmark: 35 }),
  model("groq", "openai/gpt-oss-20b", { benchmark: 30, median_latency_ms: 400 }),
  model("router", "nvidia/nemotron-nano-reasoning:free", { free: "free", benchmark: 50 }),
  model("router", "anthropic/claude-opus-5.5", { free: "none", benchmark: 90, input_price: 5, output_price: 25 }),
  model("gemini", "gemini-embedding-001", { kind: "embedding" }),
];

describe("model recommendations", () => {
  it("puts capable free models first for quick tasks and reasoning models last", () => {
    const order = ranked("fast", MODELS).map((entry) => entry.id);

    expect(order[0]).toBe("gemini-3.8-flash");
    expect(order.at(-1)).toBe("nvidia/nemotron-nano-reasoning:free");
    expect(order).not.toContain("gemini-embedding-001");
  });

  it("puts the best free benchmark first for SQL tasks and billed models after free ones", () => {
    const order = ranked("sql-gen", MODELS).map((entry) => entry.id);

    expect(order[0]).toBe("gemini-3.8-flash");
    expect(order.at(-1)).toBe("anthropic/claude-opus-5.5");
  });

  it("recommends the best model of each provider", () => {
    expect([...recommended("fast", MODELS)].map((key) => key.split("\u0000")[1]))
      .toEqual(["gemini-3.8-flash", "openai/gpt-oss-20b", "anthropic/claude-opus-5.5"]);
  });

  it("filters by search, provider, free and JSON answers", () => {
    expect(filtered("sql-gen", MODELS, { ...NO_FILTER, search: "OSS" }).map((entry) => entry.id)).toEqual(["openai/gpt-oss-20b"]);
    expect(filtered("sql-gen", MODELS, { ...NO_FILTER, providerId: "router", freeOnly: true }).map((entry) => entry.id))
      .toEqual(["nvidia/nemotron-nano-reasoning:free"]);
    expect(filtered("sql-gen", [model("x", "a", { structured_output: null })], { ...NO_FILTER, structuredOnly: true })).toEqual([]);
  });

  it("knows the models that think before answering and formats prices", () => {
    expect(slowModel("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")).toBe(true);
    expect(slowModel("openai/gpt-oss-120b")).toBe(false);
    expect(priceText(model("x", "a", { input_price: 0.25, output_price: 2 }))).toBe("$0.25 / $2.00");
  });
});
