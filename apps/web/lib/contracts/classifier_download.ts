// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type State = "idle" | "downloading" | "checking" | "done" | "failed" | "cancelled";
export type BytesDone = number;
export type BytesTotal = number;
export type Error = string | null;

export interface ClassifierDownload {
  state: State;
  bytes_done: BytesDone;
  bytes_total: BytesTotal;
  error?: Error;
}
