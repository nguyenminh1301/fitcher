// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Type = "bar" | "line" | "pie" | "scatter" | "kpi" | "table" | "grouped_bar";
export type X = string;
export type Y = string[];
export type Series = string | null;
export type Sort = ("asc" | "desc") | null;
export type Format = ("currency" | "count" | "ratio" | "percent" | "days" | "number") | null;
/**
 * @minItems 1
 */
export type AllowedTypes = [
  "bar" | "line" | "pie" | "scatter" | "kpi" | "table" | "grouped_bar",
  ...("bar" | "line" | "pie" | "scatter" | "kpi" | "table" | "grouped_bar")[]
];

export interface ChartSpec {
  type: Type;
  x: X;
  y: Y;
  series?: Series;
  sort?: Sort;
  format?: Format;
  allowed_types: AllowedTypes;
}
