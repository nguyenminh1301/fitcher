-- Registry of a pack's company documents (DECISIONS §5 Company documents).
-- One row per change of a document; the latest updated_at of an id wins, so
-- reads use FINAL. status is processing, indexed or failed; a deleted
-- document keeps its row with deleted_at set. chunk_count counts the chunks
-- indexed into kb_docs and blocked_chunks those screening kept out. Written
-- and read by the pack_review user; compile_pack reads it as the admin.
CREATE TABLE IF NOT EXISTS data_meta.documents
(
    id String,
    pack LowCardinality(String),
    file_name String,
    media_type LowCardinality(String),
    size_bytes UInt64,
    sha256 String,
    uploaded_by String,
    allowed_roles Array(String),
    status LowCardinality(String),
    error String,
    chunk_count UInt32,
    blocked_chunks UInt32,
    uploaded_at DateTime64(3, 'UTC'),
    deleted_at Nullable(DateTime64(3, 'UTC')),
    updated_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (pack, id);
