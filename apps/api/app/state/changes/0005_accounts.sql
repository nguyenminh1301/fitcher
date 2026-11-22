-- Team-mode accounts kept by the application (DECISIONS §9). The e-mail is
-- stored lower-cased. password_hash is an Argon2id hash, empty for an account
-- that signs in only through OIDC.
CREATE TABLE accounts
(
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT,
    status TEXT NOT NULL CHECK (status IN ('enabled', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Pack roles and console roles held by an account.
CREATE TABLE account_roles
(
    account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    PRIMARY KEY (account_id, role)
);

-- A signed-in session per row. Only the SHA-256 of the random session id is stored.
-- Times are seconds since the epoch.
CREATE TABLE account_sessions
(
    id_hash TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    last_used_at REAL NOT NULL
);

CREATE INDEX account_sessions_by_account ON account_sessions (account_id);

-- Failed sign-ins by key (an e-mail or a client address), kept for the
-- throttling window only.
CREATE TABLE sign_in_failures
(
    key TEXT NOT NULL,
    failed_at REAL NOT NULL
);

CREATE INDEX sign_in_failures_by_key ON sign_in_failures (key, failed_at);
