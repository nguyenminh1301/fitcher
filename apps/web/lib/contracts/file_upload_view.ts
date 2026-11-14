// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Id = string;
export type FileName = string;
export type Format = "csv" | "xlsx" | "parquet";
export type SizeBytes = number;
export type Name = string;
export type Type = string;
export type Columns = FileColumn[];
export type Sample = (string | null)[][];

export interface FileUploadView {
  id: Id;
  file_name: FileName;
  format: Format;
  size_bytes: SizeBytes;
  columns: Columns;
  sample: Sample;
}
export interface FileColumn {
  name: Name;
  type: Type;
}
