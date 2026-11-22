// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Pack = string | null;
export type Table = string;
export type Added = string[];
export type Removed = string[];
export type Column = string;
export type Before = string;
export type After = string;
export type Retyped = ColumnRetype[];
export type Missing = boolean;
export type Changes = TableDrift[];

export interface SourceDrift {
  pack: Pack;
  changes: Changes;
}
export interface TableDrift {
  table: Table;
  added: Added;
  removed: Removed;
  retyped: Retyped;
  missing: Missing;
}
export interface ColumnRetype {
  column: Column;
  before: Before;
  after: After;
}
