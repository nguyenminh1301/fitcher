-- Typed settings, one row per group and key. The value is JSON.
CREATE TABLE settings
(
    group_name TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (group_name, key)
);
