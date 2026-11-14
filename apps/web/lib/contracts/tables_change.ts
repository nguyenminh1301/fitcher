// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Name = string;
export type Selected = boolean | null;
export type Mode = ("live" | "copy") | null;
export type IntervalSeconds = number | null;
export type CursorColumn = string | null;
/**
 * @maxItems 5000
 */
export type Tables = TableChangeInput[];

export interface TablesChange {
  tables: Tables;
}
export interface TableChangeInput {
  name: Name;
  selected?: Selected;
  mode?: Mode;
  interval_seconds?: IntervalSeconds;
  cursor_column?: CursorColumn;
}
