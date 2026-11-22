-- Data sources connected in the application (DECISIONS §4, §15). Credentials are
-- not here: a source's host, port, user, password and TLS settings live in a
-- ClickHouse named collection named after the source, stored encrypted by
-- ClickHouse. A source's id is its name: it names the live database
-- src_<id> and the copies raw.<id>__<table>. host, port, database and
-- username are empty for an uploaded file.
CREATE TABLE sources
(
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    host TEXT,
    port INTEGER,
    database TEXT,
    schema TEXT,
    username TEXT,
    tls_mode TEXT NOT NULL DEFAULT 'prefer',
    has_ca INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- The tables of a source's catalog, with the user's choices. columns,
-- primary_key, foreign_keys and unusual_columns are JSON read from the source's
-- catalog. cursor_value is the last value of cursor_column seen by an
-- incremental copy; next_run_at is when the table is due again (copy mode).
CREATE TABLE source_tables
(
    source_id TEXT NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'table',
    selected INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL CHECK (mode IN ('live', 'copy')),
    proposed_mode TEXT NOT NULL CHECK (proposed_mode IN ('live', 'copy')),
    reason TEXT NOT NULL,
    row_estimate INTEGER,
    size_bytes INTEGER,
    columns TEXT NOT NULL DEFAULT '[]',
    primary_key TEXT NOT NULL DEFAULT '[]',
    foreign_keys TEXT NOT NULL DEFAULT '[]',
    unusual_columns TEXT NOT NULL DEFAULT '[]',
    interval_seconds INTEGER NOT NULL DEFAULT 86400 CHECK (interval_seconds >= 60),
    cursor_column TEXT,
    cursor_value TEXT,
    next_run_at TEXT,
    last_synced_at TEXT,
    last_rows INTEGER,
    PRIMARY KEY (source_id, name)
);

-- One row per sync. results is JSON, one entry per table. error is a reason
-- code, never the text of a failure. The unique index lets one sync run per
-- source at a time, even across processes: a second insert of a running row fails.
-- heartbeat_at is touched while a sync runs; a running row whose heartbeat is
-- stale belongs to a process that stopped and is marked failed (interrupted).
CREATE TABLE source_syncs
(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    started_by TEXT NOT NULL CHECK (started_by IN ('manual', 'schedule', 'setup')),
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    heartbeat_at TEXT NOT NULL,
    results TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    query_id TEXT
);

CREATE UNIQUE INDEX source_syncs_one_running ON source_syncs (source_id) WHERE status = 'running';

-- An uploaded file waiting for its column types to be confirmed, then loaded.
-- The original stays in the data directory (stored_path) for a reload.
CREATE TABLE source_files
(
    id TEXT PRIMARY KEY,
    source_id TEXT REFERENCES sources (id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    format TEXT NOT NULL CHECK (format IN ('csv', 'xlsx', 'parquet')),
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    columns TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    uploaded_by TEXT,
    created_at TEXT NOT NULL
);
