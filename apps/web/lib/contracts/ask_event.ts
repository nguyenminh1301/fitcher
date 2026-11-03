// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

/**
 * Any one event of the stream; its JSON Schema is the discriminated union the web app parses.
 */
export type AskEvent =
  | StatusEvent
  | ClarifyEvent
  | DenyEvent
  | SqlEvent
  | ResultEvent
  | ChartSpecEvent
  | SummaryEvent
  | DoneEvent
  | ErrorEvent;
export type TraceId = string;
export type Event = "status";
export type Node = string;
export type Phase = "start" | "end";
export type Attempt = number | null;
export type TraceId1 = string;
export type Event1 = "clarify";
export type Question = string;
export type Id = string;
export type Label = string;
export type Options = ClarifyOption[];
export type Lang = string;
export type TraceId2 = string;
export type Event2 = "deny";
export type Message = string;
export type Role = string;
export type Blocked = string[];
export type Lang1 = string;
export type TraceId3 = string;
export type Event3 = "sql";
export type Sql = string;
export type Attempt1 = number;
export type TraceId4 = string;
export type Event4 = "result";
/**
 * @minItems 1
 */
export type Columns = [ColumnInfo, ...ColumnInfo[]];
export type Name = string;
export type Type = "string" | "number" | "date" | "datetime" | "boolean";
export type Role1 = "dimension" | "measure" | "time";
export type Format = ("currency" | "count" | "ratio" | "percent" | "days" | "number") | null;
/**
 * @maxItems 5000
 */
export type Rows = (string | number | boolean | null)[][];
export type RowCount = number;
export type Truncated = boolean;
export type TraceId5 = string;
export type Event5 = "chart_spec";
export type Type1 = "bar" | "line" | "pie" | "scatter" | "kpi" | "table" | "grouped_bar";
export type X = string;
export type Y = string[];
export type Series = string | null;
export type Sort = ("asc" | "desc") | null;
export type Format1 = ("currency" | "count" | "ratio" | "percent" | "days" | "number") | null;
export type Orientation = ("vertical" | "horizontal") | null;
/**
 * @minItems 1
 */
export type AllowedTypes = [
  "bar" | "line" | "pie" | "scatter" | "kpi" | "table" | "grouped_bar",
  ...("bar" | "line" | "pie" | "scatter" | "kpi" | "table" | "grouped_bar")[]
];
export type TraceId6 = string;
export type Event6 = "summary";
export type Text = string;
export type Lang2 = string;
export type Warnings = string[];
export type TraceId7 = string;
export type Event7 = "done";
export type TraceId8 = string;
export type Event8 = "error";
export type Kind = "failed" | "internal";
export type Message1 = string;
export type Sql1 = string | null;
export type Error = string | null;

export interface StatusEvent {
  trace_id: TraceId;
  event: Event;
  node: Node;
  phase: Phase;
  attempt: Attempt;
}
export interface ClarifyEvent {
  trace_id: TraceId1;
  event: Event1;
  question: Question;
  options: Options;
  lang: Lang;
}
export interface ClarifyOption {
  id: Id;
  label: Label;
}
export interface DenyEvent {
  trace_id: TraceId2;
  event: Event2;
  message: Message;
  role: Role;
  blocked: Blocked;
  lang: Lang1;
}
export interface SqlEvent {
  trace_id: TraceId3;
  event: Event3;
  sql: Sql;
  attempt: Attempt1;
}
export interface ResultEvent {
  trace_id: TraceId4;
  event: Event4;
  result: Result;
}
export interface Result {
  columns: Columns;
  rows: Rows;
  row_count: RowCount;
  truncated?: Truncated;
}
export interface ColumnInfo {
  name: Name;
  type: Type;
  role: Role1;
  format?: Format;
}
export interface ChartSpecEvent {
  trace_id: TraceId5;
  event: Event5;
  spec: ChartSpec;
}
export interface ChartSpec {
  type: Type1;
  x: X;
  y: Y;
  series?: Series;
  sort?: Sort;
  format?: Format1;
  orientation?: Orientation;
  allowed_types: AllowedTypes;
}
export interface SummaryEvent {
  trace_id: TraceId6;
  event: Event6;
  text: Text;
  lang: Lang2;
  warnings: Warnings;
}
export interface DoneEvent {
  trace_id: TraceId7;
  event: Event7;
}
/**
 * ``failed``: no SQL attempt produced a result; ``internal``: the run broke, with no detail for the client.
 */
export interface ErrorEvent {
  trace_id: TraceId8;
  event: Event8;
  kind: Kind;
  message: Message1;
  sql: Sql1;
  error: Error;
}
