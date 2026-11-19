// Which models suit each chat task, from the providers' catalogs (DECISIONS §2). The ranking mirrors the api's
// automatic choice (app/llm/auto.py): the quick tasks (`fast`, `sql-small`) want small, fast models that answer in
// seconds and leave out models that reason, see or write code first; the SQL tasks want the best benchmark. The
// Models page uses it to mark recommended models and to sort the picker; it never limits the choice.

import type { CatalogEntry } from "@/lib/contracts";

export const QUICK_TIERS = new Set(["fast", "sql-small"]);
/** Size words of small, fast chat models, smallest first (the api's `defaults.SMALL_WORDS`). */
export const SMALL_WORDS = ["flash-lite", "lite", "nano", "mini", "instant", "flash", "small", "air", "haiku", "turbo", "20b", "8b", "7b"];
const SLOW = /reason|thinking|omni|(^|[-/])vl($|[-:])|code/;

export type ModelFilter = {
  search: string;
  /** "" for every provider. */
  providerId: string;
  freeOnly: boolean;
  structuredOnly: boolean;
};

export const NO_FILTER: ModelFilter = { search: "", providerId: "", freeOnly: false, structuredOnly: false };

function escape(word: string): string {
  return word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** The place of the model's size word among SMALL_WORDS, or null without one. */
export function smallRank(name: string): number | null {
  const lowered = name.toLowerCase();
  const index = SMALL_WORDS.findIndex((word) => new RegExp(`(^|[-/_.:])${escape(word)}($|[-:_.])`).test(lowered));
  return index === -1 ? null : index;
}

export function slowModel(name: string): boolean {
  return SLOW.test(name.toLowerCase());
}

/** Whether the task can use the model at all: a chat model, and for `fast` one known to answer in a JSON schema. */
export function suits(tier: string, model: CatalogEntry): boolean {
  if (model.kind !== "chat") return false;
  return tier === "fast" ? model.structured_output !== false : true;
}

function benchmarkKey(model: CatalogEntry): number {
  return -(model.benchmark ?? -1);
}

function latencyKey(model: CatalogEntry): number {
  return model.median_latency_ms ?? Number.POSITIVE_INFINITY;
}

function compare(a: (number | boolean)[], b: (number | boolean)[]): number {
  for (let index = 0; index < a.length; index += 1) {
    const left = Number(a[index]);
    const right = Number(b[index]);
    if (left !== right) return left < right ? -1 : 1;
  }
  return 0;
}

/** The sort key of a model for the task: lower comes first. */
function rankKey(tier: string, model: CatalogEntry): (number | boolean)[] {
  const paid = model.free === "none";
  if (QUICK_TIERS.has(tier)) {
    const size = smallRank(model.id);
    return [slowModel(model.id), paid, size ?? SMALL_WORDS.length, latencyKey(model), benchmarkKey(model)];
  }
  return [paid, benchmarkKey(model), latencyKey(model)];
}

/** The task's usable models, best first. */
export function ranked(tier: string, models: CatalogEntry[]): CatalogEntry[] {
  return models.filter((model) => suits(tier, model))
    .sort((a, b) => compare(rankKey(tier, a), rankKey(tier, b)) || a.id.localeCompare(b.id));
}

/** The models to recommend for the task: the best of each provider, three in all. */
export function recommended(tier: string, models: CatalogEntry[], count = 3): Set<string> {
  const picks: CatalogEntry[] = [];
  for (const model of ranked(tier, models)) {
    if (picks.length >= count) break;
    if (!picks.some((pick) => pick.provider_id === model.provider_id)) picks.push(model);
  }
  return new Set(picks.map(key));
}

export function key(model: { provider_id: string; id?: string; model?: string }): string {
  return `${model.provider_id}\u0000${model.id ?? model.model}`;
}

/** The models a filter keeps, chat models only, in the task's order. */
export function filtered(tier: string, models: CatalogEntry[], filter: ModelFilter): CatalogEntry[] {
  const query = filter.search.trim().toLowerCase();
  return ranked(tier, models).filter((model) =>
    (!filter.providerId || model.provider_id === filter.providerId)
    && (!filter.freeOnly || model.free !== "none")
    && (!filter.structuredOnly || model.structured_output === true)
    && (!query || model.id.toLowerCase().includes(query)));
}

/** A price per million tokens, input / output, or null when the catalog does not know it. */
export function priceText(model: CatalogEntry): string | null {
  if (model.input_price === null || model.output_price === null) return null;
  const format = (value: number) => (value < 0.01 && value > 0 ? value.toFixed(3) : value.toFixed(2));
  return `$${format(model.input_price)} / $${format(model.output_price)}`;
}

/** A context length in thousands of tokens. */
export function contextText(model: CatalogEntry): string | null {
  if (!model.context) return null;
  return model.context >= 1_000_000 ? `${(model.context / 1_000_000).toFixed(1)}M` : `${Math.round(model.context / 1000)}K`;
}

/** A measured median latency in seconds. */
export function speedText(model: CatalogEntry): string | null {
  return model.median_latency_ms === null ? null : `${(model.median_latency_ms / 1000).toFixed(1)} s`;
}
