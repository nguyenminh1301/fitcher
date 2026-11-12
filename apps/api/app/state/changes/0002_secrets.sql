-- Secrets encrypted with the instance key (AES-256-GCM). The name is the
-- associated data of the ciphertext. last_four is the only plain part and is
-- what the interface shows.
CREATE TABLE secrets
(
    name TEXT PRIMARY KEY,
    nonce BLOB NOT NULL,
    ciphertext BLOB NOT NULL,
    last_four TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
