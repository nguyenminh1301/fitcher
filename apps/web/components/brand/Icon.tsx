import { cx } from "@/lib/cx";

import { ICONS } from "./geometry";

export type IconProps = { name: string; size?: "lg"; spin?: boolean; label?: string; className?: string };

/** A Lucide line icon from the design system; decorative unless it has a label. */
export function Icon({ name, size, spin, label, className }: IconProps) {
  const parts = ICONS[name] ?? ICONS.circle;
  return (
    <svg
      className={cx("fc-icon", size === "lg" && "fc-icon-lg", spin && "fc-spin", className)}
      viewBox="0 0 24 24"
      aria-hidden={label ? undefined : true}
      role={label ? "img" : undefined}
      aria-label={label}
      focusable="false"
    >
      {parts.map((part, index) => {
        const [kind, rest] = [part.slice(0, 2), part.slice(2).split(",")];
        if (kind === "c:") return <circle key={index} cx={rest[0]} cy={rest[1]} r={rest[2]} />;
        if (kind === "r:") return <rect key={index} x={rest[0]} y={rest[1]} width={rest[2]} height={rest[3]} rx={rest[4]} />;
        if (kind === "e:") return <ellipse key={index} cx={rest[0]} cy={rest[1]} rx={rest[2]} ry={rest[3]} />;
        if (kind === "p:") return <polygon key={index} points={part.slice(2)} />;
        return <path key={index} d={part} />;
      })}
    </svg>
  );
}
