// A provider's logo where one ships with the app (public/providers), else the icon of its group. A one-color
// logo is drawn as a mask in the text color so it follows the light and dark themes; a colored one keeps its colors.

import type { CSSProperties } from "react";

import { Icon } from "@/components/brand/Icon";
import { COLORED_LOGOS, LOGOS, presetOf, type ProviderPreset } from "@/components/models/presets";
import type { ProviderView } from "@/lib/contracts";

export function ProviderLogo({ preset, small = false }: { preset: ProviderPreset | null; small?: boolean }) {
  const size = small ? " prov-logo-sm" : "";
  if (preset && LOGOS.has(preset.id)) {
    const src = `/providers/${preset.id}.svg`;
    if (COLORED_LOGOS.has(preset.id)) return <img className={`prov-logo${size}`} src={src} alt="" aria-hidden="true" />;
    const mask = { "--logo": `url(${src})` } as CSSProperties;
    return <span className={`prov-logo prov-logo-mono${size}`} style={mask} aria-hidden="true" />;
  }
  const group = preset?.group ?? "other";
  return <Icon name={group === "hosted" ? "sparkles" : group === "local" ? "laptop" : "cloud"} />;
}

/** A provider's small logo and name, as the model picker shows which provider a model belongs to. */
export function ProviderTag({ providers, id }: { providers: ProviderView[]; id: string }) {
  const provider = providers.find((item) => item.id === id);
  return <span className="prov-tag"><ProviderLogo small preset={provider ? presetOf(provider) : null} />{provider?.name ?? id}</span>;
}
