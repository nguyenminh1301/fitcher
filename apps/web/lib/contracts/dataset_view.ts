// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Id = string;
export type Description = string;
export type Grain = string;
export type TimeColumn = string;
export type ReadableRoles = string[];
export type Name = string;
export type Type = string;
export type Role = string;
export type Description1 = string;
export type Columns = DatasetColumnView[];

export interface DatasetView {
  id: Id;
  description: Description;
  grain: Grain;
  time_column: TimeColumn;
  readable_roles: ReadableRoles;
  columns: Columns;
}
export interface DatasetColumnView {
  name: Name;
  type: Type;
  role: Role;
  description: Description1;
}
