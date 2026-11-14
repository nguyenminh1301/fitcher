// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Name = string | null;
export type Name1 = string;
export type Type = string;
export type Columns = FileColumn[];

export interface FileLoad {
  name?: Name;
  columns: Columns;
}
export interface FileColumn {
  name: Name1;
  type: Type;
}
