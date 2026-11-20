-- A sync reads each table on its own, so one table that cannot be read no longer
-- fails the others: such a sync ends as partial, and its results name each failed
-- table with its reason. SQLite cannot change a CHECK constraint in place, so the
-- table is rebuilt with the same columns, rows and index.
CREATE TABLE source_syncs_next
(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    started_by TEXT NOT NULL CHECK (started_by IN ('manual', 'schedule', 'setup')),
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'partial', 'failed', 'cancelled')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    heartbeat_at TEXT NOT NULL,
    results TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    query_id TEXT
);

INSERT INTO source_syncs_next (id, source_id, started_by, status, started_at, finished_at, heartbeat_at, results, error,
                               query_id)
SELECT id, source_id, started_by, status, started_at, finished_at, heartbeat_at, results, error, query_id
FROM source_syncs;

DROP TABLE source_syncs;
ALTER TABLE source_syncs_next RENAME TO source_syncs;
CREATE UNIQUE INDEX source_syncs_one_running ON source_syncs (source_id) WHERE status = 'running';
