// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type SourceId = string;
export type Tables = string[];
export type ConfirmBillable = boolean;

export interface InstantRequest {
  source_id: SourceId;
  tables: Tables;
  confirm_billable: ConfirmBillable;
}
