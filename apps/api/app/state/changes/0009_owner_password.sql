-- The optional owner password of this personal app (DECISIONS §9). One row
-- at most; password_hash is an Argon2id hash.
CREATE TABLE owner_password
(
    id INTEGER PRIMARY KEY CHECK (id = 1),
    password_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- A signed-in browser per row. Only the SHA-256 of the random session id is
-- stored. Times are seconds since the epoch.
CREATE TABLE owner_sessions
(
    id_hash TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    last_used_at REAL NOT NULL
);

-- Failed sign-ins by client address, kept for the throttling window only.
CREATE TABLE sign_in_failures
(
    key TEXT NOT NULL,
    failed_at REAL NOT NULL
);

CREATE INDEX sign_in_failures_by_key ON sign_in_failures (key, failed_at);
