import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { buildTokensCss } from "../scripts/build-tokens.mjs";
import { contrast, TEXT_PAIRS, themeValues } from "../lib/theme-contrast";

const STYLES = join(__dirname, "..", "app", "styles");
const tokens = JSON.parse(readFileSync(join(STYLES, "tokens.json"), "utf-8"));
const css = readFileSync(join(STYLES, "tokens.css"), "utf-8");

describe("design tokens", () => {
  it("tokens.css is generated from tokens.json", () => {
    expect(css).toBe(buildTokensCss(tokens));
  });

  it("defines the font families the component stylesheet reads", () => {
    expect(css).toContain("--font-sans:");
    expect(css).toContain("--font-mono:");
  });

  for (const theme of ["light", "dark"] as const) {
    it(`every text token pair meets WCAG AA in the ${theme} theme`, () => {
      const values = themeValues(tokens, theme);
      const failing = TEXT_PAIRS.filter(([fg, bg, minimum]) => contrast(values[fg], values[bg]) < minimum).map(
        ([fg, bg, minimum]) => `${fg} on ${bg}: ${contrast(values[fg], values[bg]).toFixed(2)} < ${minimum}`,
      );
      expect(failing).toEqual([]);
    });
  }
});
