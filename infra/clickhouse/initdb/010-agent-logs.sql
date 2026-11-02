-- Agent run logs (DECISIONS §10). The ClickHouse entrypoint runs this file on a
-- fresh volume; `python -m jobs.apply_log_schema` applies it to an existing one.
-- Every statement only creates what is missing, so both paths are idempotent;
-- changing an existing table needs its own deliberate migration.
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

-- Written by the LiteLLM proxy callback, one row per gateway call.
CREATE TABLE IF NOT EXISTS agent_logs.llm_calls
(
    trace_id String,
    ts DateTime64(3, 'UTC'),
    node LowCardinality(String),
    alias LowCardinality(String),
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

-- Conversation turns, read back for follow-up questions.
CREATE TABLE IF NOT EXISTS agent_logs.chat_messages
(
    user_id String,
    ts DateTime64(3, 'UTC'),
    conversation_id String,
    trace_id String,
    role LowCardinality(String),
    content String,
    query_spec String
)
ENGINE = MergeTree
ORDER BY (user_id, ts)
TTL toDateTime(ts) + INTERVAL 90 DAY
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

-- One row per eval run; report holds the full JSON report.
CREATE TABLE IF NOT EXISTS agent_logs.eval_reports
(
    pack LowCardinality(String),
    ts DateTime64(3, 'UTC'),
    report_id String,
    execution_rate Float64,
    passed Bool,
    report String
)
ENGINE = MergeTree
ORDER BY (pack, ts)
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
    status LowCardinality(String)
)
ENGINE = MergeTree
ORDER BY (pack, ts)
TTL toDateTime(ts) + INTERVAL 90 DAY
SETTINGS non_replicated_deduplication_window = 10000;
