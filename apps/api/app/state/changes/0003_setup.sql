-- State of each first-run setup step: pending, done or skipped.
CREATE TABLE setup_steps
(
    id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('pending', 'done', 'skipped')),
    updated_at TEXT NOT NULL
);
