// WCAG 2.2 contrast of the design's colour pairs, checked by a unit test in both themes.

type Theme = "light" | "dark";
type Tokens = { color: { themes: { id: string }[]; tokens: { name: string; value: string | Record<string, string> }[] } };

/** [foreground token, background token, minimum ratio]: 4.5 for text, 3 for borders, focus rings and chart marks. */
export const TEXT_PAIRS: [string, string, number][] = [
  ...["bgColor-default", "bgColor-muted", "bgColor-inset"].flatMap((bg): [string, string, number][] => [
    ["fgColor-default", bg, 4.5],
    ["fgColor-muted", bg, 4.5],
  ]),
  ["fgColor-default", "bgColor-neutral-muted", 4.5],
  // Mist carries muted icons only (the trace timeline dots): 4.33:1 in the light theme is enough for an
  // icon but not for text, so components never put muted text on bgColor-neutral-muted.
  ["fgColor-muted", "bgColor-neutral-muted", 3],
  ...["fgColor-accent", "fgColor-success", "fgColor-attention", "fgColor-danger", "fgColor-done"].map(
    (fg): [string, string, number] => [fg, "bgColor-default", 4.5],
  ),
  ["fgColor-accent", "bgColor-accent-muted", 4.5],
  ["fgColor-success", "bgColor-success-muted", 4.5],
  ["fgColor-attention", "bgColor-attention-muted", 4.5],
  ["fgColor-danger", "bgColor-danger-muted", 4.5],
  ["fgColor-done", "bgColor-done-muted", 4.5],
  ["fgColor-onEmphasis", "bgColor-emphasis", 4.5],
  ["button-primary-fgColor-rest", "button-primary-bgColor-rest", 4.5],
  ["fgColor-default", "button-default-bgColor-rest", 4.5],
  ["borderColor-emphasis", "bgColor-default", 3],
  ["borderColor-emphasis", "bgColor-muted", 3],
  ["focus-outlineColor", "bgColor-default", 3],
  ["data-1", "bgColor-default", 3],
  ["data-2-edge", "bgColor-default", 3],
];

/** Each colour token's value in ``theme``, falling back to the first theme as the design system does. */
export function themeValues(tokens: Tokens, theme: Theme): Record<string, string> {
  const first = tokens.color.themes[0].id;
  return Object.fromEntries(
    tokens.color.tokens.map((token) => [
      token.name,
      typeof token.value === "string" ? token.value : (token.value[theme] ?? token.value[first]),
    ]),
  );
}

function luminance(hex: string): number {
  const digits = hex.replace("#", "").slice(0, 6);
  const channels = [0, 2, 4].map((start) => parseInt(digits.slice(start, start + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(foreground: string, background: string): number {
  const [light, dark] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
}
