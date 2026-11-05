// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Id = string;
export type Name = string;
export type Size = number;
export type MediaType = string;
export type Status = "processing" | "indexed" | "failed";
export type Error = string;
export type Roles = string[];
export type ChunkCount = number;
export type BlockedChunks = number;
export type UploadedBy = string;
export type UploadedAt = string;

export interface DocumentView {
  id: Id;
  name: Name;
  size: Size;
  media_type: MediaType;
  status: Status;
  error?: Error;
  roles: Roles;
  chunk_count: ChunkCount;
  blocked_chunks: BlockedChunks;
  uploaded_by: UploadedBy;
  uploaded_at: UploadedAt;
}
