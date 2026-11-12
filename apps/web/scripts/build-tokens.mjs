// Generate app/styles/tokens.css from the design system's tokens.json.
// Run with `npm run tokens` after replacing tokens.json; a test fails while the two disagree.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HEADER = "/* fitcher design tokens, generated from tokens.json by scripts/build-tokens.mjs; do not edit. */";

function themed(family, theme, first) {
  return (family?.tokens ?? []).flatMap((token) => {
    if (typeof token.value === "string") return theme === first ? [[token.name, token.value]] : [];
    const value = token.value[theme] ?? (theme === first ? undefined : null);
    return value ? [[token.name, value]] : [];
  });
}

function block(selector, entries, scheme) {
  const lines = entries.map(([name, value]) => `  --${name}: ${value};`);
  return `${selector} {\n  color-scheme: ${scheme};\n${lines.join("\n")}\n}`;
}

/** The CSS custom properties of every token: light on :root, dark under [data-theme="dark"] and the system setting. */
export function buildTokensCss(tokens) {
  const first = tokens.color.themes[0].id;
  const plain = ["spacing", "radius", "size", "breakpoint"].flatMap((family) =>
    (tokens[family]?.tokens ?? []).map((token) => [token.name, token.value]),
  );
  const fonts = Object.entries(tokens.type.families).map(([name, stack]) => [`font-${name}`, stack]);
  const light = [...themed(tokens.color, "light", first), ...themed(tokens.shadow, "light", first), ...plain, ...fonts];
  const dark = [...themed(tokens.color, "dark", first), ...themed(tokens.shadow, "dark", first)];
  return [
    HEADER,
    block(":root,\n[data-theme=\"light\"]", light, "light"),
    block("[data-theme=\"dark\"]", dark, "dark"),
    `@media (prefers-color-scheme: dark) {\n${block(":root:not([data-theme=\"light\"])", dark, "dark")
      .split("\n")
      .map((line) => `  ${line}`)
      .join("\n")}\n}`,
    "",
  ].join("\n\n");
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const styles = join(dirname(fileURLToPath(import.meta.url)), "..", "app", "styles");
  const tokens = JSON.parse(readFileSync(join(styles, "tokens.json"), "utf-8"));
  writeFileSync(join(styles, "tokens.css"), buildTokensCss(tokens));
}
