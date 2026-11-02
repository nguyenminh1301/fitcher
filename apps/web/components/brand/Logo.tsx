import { cx } from "@/lib/cx";

import { FINCH_BEAK, FINCH_BODY, SYMBOL, SYMBOL_SMALL, WORD, type Shapes } from "./geometry";

function shapes(group: Shapes) {
  return [
    ...(group.r ?? []).map(([x, y, width, height, rx], i) => <rect key={`r${i}`} x={x} y={y} width={width} height={height} rx={rx} />),
    ...(group.c ?? []).map(([cx, cy, r], i) => <circle key={`c${i}`} cx={cx} cy={cy} r={r} />),
    ...(group.p ?? []).map((d, i) => <path key={`p${i}`} d={d} />),
  ];
}

const ART = {
  symbol: { viewBox: "0 0 256 256", ratio: 1 },
  wordmark: { viewBox: "0 60 693 140", ratio: 693 / 140 },
  horizontal: { viewBox: "0 0 893.6 200", ratio: 893.6 / 200 },
} as const;

export type LogoProps = { variant?: keyof typeof ART; height?: number; label?: string; className?: string };

/** The brand mark, one colour (Ink on light, Paper on dark); below 32px the symbol uses its small-size cut. */
export function Logo({ variant = "horizontal", height = 24, label = "fitcher", className }: LogoProps) {
  const art = ART[variant];
  let content;
  if (variant === "symbol") content = shapes(height < 32 ? SYMBOL_SMALL : SYMBOL);
  else if (variant === "wordmark") content = shapes(WORD);
  else
    content = [
      <g key="s" transform="translate(-28,-28)">{shapes(SYMBOL)}</g>,
      <g key="w" transform="translate(256,-19.6) scale(0.92)">{shapes(WORD)}</g>,
    ];
  return (
    <span className={cx("fc-logo", className)} role="img" aria-label={label} style={{ height }}>
      <svg viewBox={art.viewBox} width={Math.round(height * art.ratio)} height={height} aria-hidden focusable="false">
        {content}
      </svg>
    </span>
  );
}

export type FinchProps = { size?: number; live?: boolean; label?: string; className?: string };

/** The assistant's face: next to every assistant turn, bobbing while an answer streams. */
export function Finch({ size = 28, live, label, className }: FinchProps) {
  const glyph = Math.round(size * 0.68);
  return (
    <span
      className={cx("fc-finch", className)}
      data-live={live ? "true" : undefined}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      style={{ width: size, height: size }}
    >
      <svg viewBox="0 0 256 256" width={glyph} height={glyph} aria-hidden focusable="false">
        <g transform="translate(-3,-12)">
          <path fillRule="evenodd" d={FINCH_BODY} />
          <path d={FINCH_BEAK} />
        </g>
      </svg>
    </span>
  );
}
