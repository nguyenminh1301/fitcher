// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Enabled = boolean;
export type ModelPresent = boolean;
export type Version = string | null;
export type Engine = "provider" | "local_onnx";
export type ProviderId = string | null;
export type Model = string | null;
export type State = "idle" | "downloading" | "checking" | "done" | "failed" | "cancelled";
export type BytesDone = number;
export type BytesTotal = number;
export type Error = string | null;
export type DownloadSource = string | null;
export type License = string | null;

export interface ClassifierStatus {
  enabled: Enabled;
  model_present: ModelPresent;
  version: Version;
  engine?: Engine;
  provider_id?: ProviderId;
  model?: Model;
  download?: ClassifierDownload | null;
  download_source?: DownloadSource;
  license?: License;
}
export interface ClassifierDownload {
  state: State;
  bytes_done: BytesDone;
  bytes_total: BytesTotal;
  error?: Error;
}
