// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

/**
 * @minItems 1
 */
export type Columns = [ColumnInfo, ...ColumnInfo[]];
export type Name = string;
export type Type = "string" | "number" | "date" | "datetime" | "boolean";
export type Role = "dimension" | "measure" | "time";
export type Format = ("currency" | "count" | "ratio" | "percent" | "days" | "number") | null;
/**
 * @maxItems 5000
 */
export type Rows = (string | number | boolean | null)[][];
export type RowCount = number;
export type Truncated = boolean;

export interface Result {
  columns: Columns;
  rows: Rows;
  row_count: RowCount;
  truncated?: Truncated;
}
export interface ColumnInfo {
  name: Name;
  type: Type;
  role: Role;
  format?: Format;
}
