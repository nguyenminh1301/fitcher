// Interface language (DECISIONS §15): the switch translates labels, steps, notices the app raises
// and number and date formats. Content (questions, answers, pack text, data) is never translated;
// every content block carries its own `lang`.

import en from "./en.json";
import vi from "./vi.json";

export type Locale = "en" | "vi";
export type Dictionary = { [key: string]: string | Dictionary };

export const DICTIONARIES: Record<Locale, Dictionary> = { en, vi };
export const LOCALES: Locale[] = ["en", "vi"];
const NUMBER_LOCALE: Record<Locale, string> = { en: "en-US", vi: "vi-VN" };

/** ``{"a": {"b": "x"}}`` -> ``{"a.b": "x"}``. */
export function flatten(dictionary: Dictionary, prefix = ""): Record<string, string> {
  return Object.entries(dictionary).reduce<Record<string, string>>((flat, [key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof value === "string" ? { ...flat, [path]: value } : { ...flat, ...flatten(value, path) };
  }, {});
}

function lookup(dictionary: Dictionary, key: string): string | undefined {
  let node: string | Dictionary | undefined = dictionary;
  for (const part of key.split(".")) {
    if (typeof node !== "object" || node === null) return undefined;
    node = node[part];
  }
  return typeof node === "string" ? node : undefined;
}

/** The ``key`` in ``primary``, else in ``fallback``, else the key itself; ``{name}`` slots are filled from ``vars``. */
export function translate(
  fallback: Dictionary,
  primary: Dictionary,
  key: string,
  vars: Record<string, string | number> = {},
): string {
  const text = lookup(primary, key) ?? lookup(fallback, key) ?? key;
  return text.replace(/\{(\w+)\}/g, (slot, name: string) => (name in vars ? String(vars[name]) : slot));
}

export function formatNumber(value: number, locale: Locale, options: Intl.NumberFormatOptions = {}): string {
  return new Intl.NumberFormat(NUMBER_LOCALE[locale], { maximumFractionDigits: 2, ...options }).format(value);
}

export function formatDate(iso: string, locale: Locale, options: Intl.DateTimeFormatOptions = { dateStyle: "medium" }): string {
  return new Intl.DateTimeFormat(NUMBER_LOCALE[locale], { timeZone: "UTC", ...options }).format(new Date(iso));
}
