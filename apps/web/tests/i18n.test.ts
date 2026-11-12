import { describe, expect, it } from "vitest";

import en from "../lib/i18n/en.json";
import vi from "../lib/i18n/vi.json";
import { flatten, formatNumber, translate } from "../lib/i18n";

describe("interface strings", () => {
  it("english and vietnamese dictionaries have the same keys", () => {
    expect(Object.keys(flatten(vi)).sort()).toEqual(Object.keys(flatten(en)).sort());
  });

  it("falls back to english, then to the key", () => {
    expect(translate({ a: { b: "English" } }, {}, "a.b")).toBe("English");
    expect(translate({}, {}, "missing.key")).toBe("missing.key");
  });

  it("fills named values", () => {
    expect(translate({ steps: { repair: "Repairing SQL (attempt {n} of {max})" } }, {}, "steps.repair", { n: 2, max: 3 })).toBe(
      "Repairing SQL (attempt 2 of 3)",
    );
  });

  it("formats numbers for the interface language", () => {
    expect(formatNumber(184320.5, "en")).toBe("184,320.5");
    expect(formatNumber(184320.5, "vi")).toBe("184.320,5");
  });
});
