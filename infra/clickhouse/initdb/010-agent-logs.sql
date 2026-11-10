-- Agent run logs (DECISIONS §10). The ClickHouse entrypoint runs this file on a
-- fresh volume; `python -m jobs.apply_log_schema` applies it to an existing one.
-- Every statement only creates what is missing, or adds a column that is
-- missing, so both paths are idempotent; any other change to an existing table
-- needs its own deliberate migration.
--
-- jobs.apply_log_schema splits this file on semicolons after dropping comment
-- lines, so no statement may contain a semicolon inside a string literal.
--
-- Trace tables are sorted by (trace_id, ts) and user tables by (user_id, ts).
-- Rows expire after 90 days. The deduplication window lets a retried batch
-- that carries the same insert_deduplication_token add no rows.

CREATE DATABASE IF NOT EXISTS agent_logs;

-- One row per run state: `running` before the graph starts, then the final
-- state. Read with FINAL to get the latest row of each trace.
CREATE TABLE IF NOT EXISTS agent_logs.runs
(
    trace_id String,
    ts DateTime64(3, 'UTC'),
    updated_at DateTime64(3, 'UTC'),
    user_id String,
    pack LowCardinality(String),
    question String,
    intent LowCardinality(String),
    status LowCardinality(String),
    latency_ms UInt32,
    error String,
    log_complete Bool,
    lost_records UInt32,
    llm_calls UInt32
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY trace_id
TTL toDateTime(ts) + INTERVAL 90 DAY
SETTINGS non_replicated_deduplication_window = 10000;

-- One row per graph node execution; payload is JSON capped at 16 KB.
CREATE TABLE IF NOT EXISTS agent_logs.events
(
    trace_id String,
    ts DateTime64(3, 'UTC'),
    ended_at DateTime64(3, 'UTC'),
    node LowCardinality(String),
    status LowCardinality(String),
    duration_ms UInt32,
    payload String,
    payload_truncated Bool
)
ENGINE = MergeTree
ORDER BY (trace_id, ts)
TTL toDateTime(ts) + INTERVAL 90 DAY
SETTINGS non_replicated_deduplication_window = 10000;

-- Written by the LiteLLM proxy callback, one row per gateway call. tier is the
-- model tier the engine called and alias the catalog alias it resolved to.
CREATE TABLE IF NOT EXISTS agent_logs.llm_calls
(
    trace_id String,
    ts DateTime64(3, 'UTC'),
    node LowCardinality(String),
    alias LowCardinality(String),
    tier LowCardinality(String),
    model LowCardinality(String),
    call_id String,
    prompt_tokens UInt32,
    completion_tokens UInt32,
    total_tokens UInt32,
    cost_usd Float64,
    latency_ms UInt32,
    status LowCardinality(String),
    error String
)
ENGINE = MergeTree
ORDER BY (trace_id, ts)
TTL toDateTime(ts) + INTERVAL 90 DAY
SETTINGS non_replicated_deduplication_window = 10000;

-- Column added after llm_calls was first created; a no-op on a fresh volume.
ALTER TABLE agent_logs.llm_calls ADD COLUMN IF NOT EXISTS tier LowCardinality(String) AFTER alias;

-- One row per executed SQL attempt; query_id joins system.query_log.
CREATE TABLE IF NOT EXISTS agent_logs.sql_runs
(
    trace_id String,
    ts DateTime64(3, 'UTC'),
    attempt UInt8,
    sql String,
    query_id String,
    rows UInt64,
    error String
)
ENGINE = MergeTree
ORDER BY (trace_id, ts)
TTL toDateTime(ts) + INTERVAL 90 DAY
SETTINGS non_replicated_deduplication_window = 10000;

-- Every ALLOW or DENY access decision.
CREATE TABLE IF NOT EXISTS agent_logs.audit
(
    trace_id String,
    ts DateTime64(3, 'UTC'),
    user_id String,
    role LowCardinality(String),
    decision Enum8('ALLOW' = 1, 'DENY' = 2),
    dataset String,
    blocked_tables Array(String),
    reason String
)
ENGINE = MergeTree
ORDER BY (trace_id, ts)
TTL toDateTime(ts) + INTERVAL 90 DAY
SETTINGS non_replicated_deduplication_window = 10000;

-- The screening verdict of each question (DECISIONS §9, Layer 0), written by
-- the graph's screen node before any LLM call. score is null when the
-- classifier was unavailable; the question text itself stays in runs.
CREATE TABLE IF NOT EXISTS agent_logs.input_screening
(
    trace_id String,
    ts DateTime64(3, 'UTC'),
    user_id String,
    source LowCardinality(String),
    verdict LowCardinality(String),
    mode LowCardinality(String),
    score Nullable(Float64),
    rule_hits Array(String),
    model_version LowCardinality(String)
)
ENGINE = MergeTree
ORDER BY (trace_id, ts)
TTL toDateTime(ts) + INTERVAL 90 DAY
SETTINGS non_replicated_deduplication_window = 10000;

-- Conversation turns, read back for follow-up questions. Each question and
-- its answer share a turn number; an edit or retry of a turn writes it again
-- under a higher revision. result holds the shaped Result JSON of an answer
-- and events its other stream events (sql, chart_spec, summary, clarify, deny
-- or error) as a JSON array, so a conversation can be shown again.
CREATE TABLE IF NOT EXISTS agent_logs.chat_messages
(
    user_id String,
    ts DateTime64(3, 'UTC'),
    conversation_id String,
    trace_id String,
    role LowCardinality(String),
    content String,
    query_spec String,
    turn UInt32,
    revision UInt32,
    result String,
    events String
)
ENGINE = MergeTree
ORDER BY (user_id, ts)
TTL toDateTime(ts) + INTERVAL 90 DAY
SETTINGS non_replicated_deduplication_window = 10000;

-- Columns added after chat_messages was first created; no-ops on a fresh volume.
ALTER TABLE agent_logs.chat_messages ADD COLUMN IF NOT EXISTS turn UInt32;
ALTER TABLE agent_logs.chat_messages ADD COLUMN IF NOT EXISTS revision UInt32;
ALTER TABLE agent_logs.chat_messages ADD COLUMN IF NOT EXISTS result String;
ALTER TABLE agent_logs.chat_messages ADD COLUMN IF NOT EXISTS events String;

-- One row per change of a conversation (created, renamed, pinned, moved or
-- deleted); read with FINAL for its current state. Delete only hides it from
-- its owner. Rows expire 90 days after the last change.
CREATE TABLE IF NOT EXISTS agent_logs.conversations
(
    user_id String,
    conversation_id String,
    title String,
    pinned Bool,
    group_id String,
    deleted Bool,
    created_at DateTime64(3, 'UTC'),
    updated_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (user_id, conversation_id)
TTL toDateTime(updated_at) + INTERVAL 90 DAY
SETTINGS non_replicated_deduplication_window = 10000;

-- A user's folders for conversations, one row per change like conversations.
CREATE TABLE IF NOT EXISTS agent_logs.conversation_groups
(
    user_id String,
    group_id String,
    name String,
    deleted Bool,
    updated_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (user_id, group_id)
TTL toDateTime(updated_at) + INTERVAL 90 DAY
SETTINGS non_replicated_deduplication_window = 10000;

CREATE TABLE IF NOT EXISTS agent_logs.feedback
(
    user_id String,
    ts DateTime64(3, 'UTC'),
    trace_id String,
    rating Enum8('like' = 1, 'dislike' = 2),
    note String
)
ENGINE = MergeTree
ORDER BY (user_id, ts)
TTL toDateTime(ts) + INTERVAL 90 DAY
SETTINGS non_replicated_deduplication_window = 10000;

-- One row per eval run; report holds the full JSON report, tiers the
-- tier-to-alias mapping the run used and regressed whether it regressed
-- against the baseline it was compared with (NULL without a baseline).
CREATE TABLE IF NOT EXISTS agent_logs.eval_reports
(
    pack LowCardinality(String),
    ts DateTime64(3, 'UTC'),
    report_id String,
    execution_rate Float64,
    passed Bool,
    report String,
    tiers Map(String, String),
    regressed Nullable(Bool)
)
ENGINE = MergeTree
ORDER BY (pack, ts)
TTL toDateTime(ts) + INTERVAL 90 DAY
SETTINGS non_replicated_deduplication_window = 10000;

-- Columns added after eval_reports was first created; no-ops on a fresh volume.
ALTER TABLE agent_logs.eval_reports ADD COLUMN IF NOT EXISTS tiers Map(String, String);
ALTER TABLE agent_logs.eval_reports ADD COLUMN IF NOT EXISTS regressed Nullable(Bool);

-- One row per change an admin makes from the console, such as a model tier
-- mapping (DECISIONS §15). target names what changed; old_value and new_value
-- hold its value before and after.
CREATE TABLE IF NOT EXISTS agent_logs.admin_actions
(
    ts DateTime64(3, 'UTC'),
    actor String,
    action LowCardinality(String),
    target String,
    old_value String,
    new_value String
)
ENGINE = MergeTree
ORDER BY (action, ts)
TTL toDateTime(ts) + INTERVAL 90 DAY
SETTINGS non_replicated_deduplication_window = 10000;

-- Examples proposed from disliked or failed runs for pack review.
CREATE TABLE IF NOT EXISTS agent_logs.example_proposals
(
    pack LowCardinality(String),
    ts DateTime64(3, 'UTC'),
    proposal_id String,
    trace_id String,
    question String,
    sql String,
    source LowCardinality(String),
    status LowCardinality(String),
    -- The run's final QuerySpec (JSON), its error, the feedback note and the proposal's confidence,
    -- all redacted before storage (Phase 12); never written to Git.
    spec String,
    error String,
    note String,
    confidence Float64
)
ENGINE = MergeTree
ORDER BY (pack, ts)
TTL toDateTime(ts) + INTERVAL 90 DAY
SETTINGS non_replicated_deduplication_window = 10000;
ALTER TABLE agent_logs.example_proposals ADD COLUMN IF NOT EXISTS spec String;
ALTER TABLE agent_logs.example_proposals ADD COLUMN IF NOT EXISTS error String;
ALTER TABLE agent_logs.example_proposals ADD COLUMN IF NOT EXISTS note String;
ALTER TABLE agent_logs.example_proposals ADD COLUMN IF NOT EXISTS confidence Float64;

-- ClickHouse's own record of every agent query, keyed by the trace id the api
-- sets as log_comment. No copy is kept: the view reads system.query_log, which
-- flushes every few seconds, so a trace read right after its run may miss the
-- last queries (run SYSTEM FLUSH LOGS as admin first). Readers need SELECT on
-- both the view and system.query_log.
--
-- A fresh server creates system.query_log at its first log flush, and a view
-- cannot be created over a table that does not exist yet, so flush first.
SYSTEM FLUSH LOGS;

CREATE VIEW IF NOT EXISTS agent_logs.trace_query_log AS
SELECT
    log_comment AS trace_id,
    event_time_microseconds AS ts,
    query_id,
    type,
    query_duration_ms,
    read_rows,
    result_rows,
    exception,
    query
FROM system.query_log
WHERE log_comment != '' AND type != 'QueryStart';
