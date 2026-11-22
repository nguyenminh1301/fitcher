// The providers offered when adding one (DECISIONS §2, §15). Each preset is one of the api's provider kinds with
// what a person would otherwise have to look up: the display name, the endpoint of a hosted OpenAI-compatible
// service, the usual address of a model server on this computer and the page where its key is created. Every
// OpenAI-compatible service goes through the same `openai_compatible` kind; "Other" takes any endpoint.

import type { ProviderCreate, ProviderView } from "@/lib/contracts";

export type ProviderKind = ProviderCreate["kind"];
export type PresetGroup = "hosted" | "service" | "local" | "other";

export type ProviderPreset = {
  id: string;
  kind: ProviderKind;
  /** The display name sent to the api; the api names the hosted kinds itself. */
  name?: string;
  group: PresetGroup;
  /** The endpoint of a hosted OpenAI-compatible service; fixed, so it is not asked. */
  baseUrl?: string;
  /** The usual address of a server on this computer, as seen from inside the container; it can be changed. */
  suggestedUrl?: string;
  /** The page where the key is created. */
  keyUrl?: string;
  /** Whether a key is required, optional or not taken at all. */
  key: "required" | "optional" | "none";
};

/** The presets with a logo in `public/providers/<id>.svg` (lobe-icons, MIT); the colored ones keep their own colors. */
export const LOGOS = new Set(["openai", "anthropic", "gemini", "openrouter", "groq", "zai", "mistral", "deepseek", "xai",
  "together", "fireworks", "cerebras", "ollama", "lmstudio", "vllm"]);
export const COLORED_LOGOS = new Set(["gemini", "mistral", "deepseek", "together", "fireworks", "vllm"]);

export const PRESETS: ProviderPreset[] = [
  { id: "openai", kind: "openai", group: "hosted", key: "required", keyUrl: "https://platform.openai.com/api-keys" },
  { id: "anthropic", kind: "anthropic", group: "hosted", key: "required", keyUrl: "https://console.anthropic.com/settings/keys" },
  { id: "gemini", kind: "gemini", group: "hosted", key: "required", keyUrl: "https://aistudio.google.com/apikey" },
  {
    id: "openrouter", kind: "openai_compatible", name: "OpenRouter", group: "service", key: "required",
    baseUrl: "https://openrouter.ai/api/v1", keyUrl: "https://openrouter.ai/settings/keys",
  },
  {
    id: "groq", kind: "openai_compatible", name: "Groq", group: "service", key: "required",
    baseUrl: "https://api.groq.com/openai/v1", keyUrl: "https://console.groq.com/keys",
  },
  {
    id: "zai", kind: "openai_compatible", name: "Z.ai", group: "service", key: "required",
    baseUrl: "https://api.z.ai/api/paas/v4", keyUrl: "https://z.ai/manage-apikey/apikey-list",
  },
  {
    id: "mistral", kind: "openai_compatible", name: "Mistral", group: "service", key: "required",
    baseUrl: "https://api.mistral.ai/v1", keyUrl: "https://console.mistral.ai/api-keys",
  },
  {
    id: "deepseek", kind: "openai_compatible", name: "DeepSeek", group: "service", key: "required",
    baseUrl: "https://api.deepseek.com/v1", keyUrl: "https://platform.deepseek.com/api_keys",
  },
  {
    id: "xai", kind: "openai_compatible", name: "xAI", group: "service", key: "required",
    baseUrl: "https://api.x.ai/v1", keyUrl: "https://console.x.ai",
  },
  {
    id: "together", kind: "openai_compatible", name: "Together AI", group: "service", key: "required",
    baseUrl: "https://api.together.xyz/v1", keyUrl: "https://api.together.ai/settings/api-keys",
  },
  {
    id: "fireworks", kind: "openai_compatible", name: "Fireworks", group: "service", key: "required",
    baseUrl: "https://api.fireworks.ai/inference/v1", keyUrl: "https://fireworks.ai/account/api-keys",
  },
  {
    id: "cerebras", kind: "openai_compatible", name: "Cerebras", group: "service", key: "required",
    baseUrl: "https://api.cerebras.ai/v1", keyUrl: "https://cloud.cerebras.ai",
  },
  { id: "ollama", kind: "ollama", group: "local", key: "none", suggestedUrl: "http://host.docker.internal:11434" },
  {
    id: "lmstudio", kind: "openai_compatible", name: "LM Studio", group: "local", key: "none",
    suggestedUrl: "http://host.docker.internal:1234/v1",
  },
  {
    id: "vllm", kind: "openai_compatible", name: "vLLM", group: "local", key: "optional",
    suggestedUrl: "http://host.docker.internal:8000/v1",
  },
  { id: "openai_compatible", kind: "openai_compatible", group: "other", key: "optional" },
];

export const PRESET_GROUPS: PresetGroup[] = ["hosted", "service", "local", "other"];

export function presetById(id: string): ProviderPreset {
  return PRESETS.find((preset) => preset.id === id) ?? PRESETS[0];
}

/** Whether a provider's models are OpenRouter's, whose free models end in ":free". */
export function isOpenRouter(baseUrl: string | null | undefined): boolean {
  if (!baseUrl) return false;
  try {
    return new URL(baseUrl).hostname.endsWith("openrouter.ai");
  } catch {
    return false;
  }
}

export const FREE_SUFFIX = ":free";

/** Where a check of the provider is billed: by the provider, never, or only if the endpoint bills requests. */
export function billing(preset: ProviderPreset): "billed" | "free" | "maybe" {
  if (preset.group === "local" || preset.id === "openrouter") return "free";
  if (preset.group === "other") return "maybe";
  return "billed";
}

/** Whether the preset asks for the address of its server. */
export function asksAddress(preset: ProviderPreset): boolean {
  return !preset.baseUrl && preset.kind !== "openai" && preset.kind !== "anthropic" && preset.kind !== "gemini";
}

/** Whether the person names the provider: an endpoint they choose themselves, which no preset names. */
export function asksName(preset: ProviderPreset): boolean {
  return preset.group === "other" || preset.group === "local";
}

/** The api request that adds the preset with what the person typed; a name they typed replaces the preset's. */
export function providerCreate(preset: ProviderPreset, apiKey: string, address: string, name = ""): ProviderCreate {
  const body: ProviderCreate = { kind: preset.kind };
  const typed = asksName(preset) ? name.trim() : "";
  if (typed || preset.name) body.name = typed || preset.name;
  if (apiKey && preset.key !== "none") body.api_key = apiKey;
  if (preset.baseUrl) body.base_url = preset.baseUrl;
  else if (asksAddress(preset)) body.base_url = address.trim();
  return body;
}

/** Whether something the preset needs is still empty. */
export function presetIncomplete(preset: ProviderPreset, apiKey: string, address: string, name = ""): boolean {
  return (preset.key === "required" && !apiKey.trim()) || (asksAddress(preset) && !address.trim())
    || (preset.group === "other" && !name.trim());
}

/** The preset a stored provider came from: its kind, the service its address belongs to, or a local server's port. */
export function presetOf(provider: Pick<ProviderView, "kind" | "name" | "base_url">): ProviderPreset | null {
  if (provider.kind !== "openai_compatible") return PRESETS.find((preset) => preset.kind === provider.kind) ?? null;
  return PRESETS.find((preset) => preset.baseUrl && preset.baseUrl === provider.base_url)
    ?? PRESETS.find((preset) => preset.name === provider.name)
    ?? PRESETS.find((preset) => preset.suggestedUrl && preset.suggestedUrl === provider.base_url) ?? null;
}
