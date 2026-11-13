// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Id = string;
export type Name = string;
export type Kind = "openai" | "anthropic" | "gemini" | "ollama" | "openai_compatible";
export type BaseUrl = string | null;
export type KeySet = boolean;
export type KeyLast4 = string | null;
export type Hosted = boolean;
export type InUse = boolean;

export interface ProviderView {
  id: Id;
  name: Name;
  kind: Kind;
  base_url: BaseUrl;
  key_set: KeySet;
  key_last4: KeyLast4;
  hosted: Hosted;
  in_use: InUse;
}
