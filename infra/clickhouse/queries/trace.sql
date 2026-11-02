-- Everything recorded for one agent run, in time order: the run row, node
-- events, LLM calls, SQL attempts and ClickHouse's query_log entries.
--
-- clickhouse-client --user agent_logs_trace_reader --param_trace_id=<id> --queries-file trace.sql
--
-- The run row's state column reads `complete` only when log_complete is true;
-- any lost record, failed run-row write or crashed run reads INCOMPLETE. Its
-- detail compares the LLM calls the api sent with the llm_calls rows the
-- LiteLLM callback wrote. query_log rows appear a few seconds after a run
-- unless an admin runs SYSTEM FLUSH LOGS first.
SELECT ts, source, name, state, detail
FROM
(
    SELECT
        toDateTime64(ts, 6, 'UTC') AS ts,
        'run' AS source,
        toString(status) AS name,
        if(log_complete, 'complete', 'INCOMPLETE') AS state,
        concat(
            'latency_ms=', toString(latency_ms),
            ' lost_records=', toString(lost_records),
            ' llm_calls_sent=', toString(llm_calls),
            ' llm_calls_logged=', toString((SELECT count() FROM agent_logs.llm_calls WHERE trace_id = {trace_id:String})),
            if(error = '', '', concat(' error=', error))
        ) AS detail
    FROM agent_logs.runs FINAL
    WHERE trace_id = {trace_id:String}

    UNION ALL

    SELECT
        toDateTime64(ts, 6, 'UTC'),
        'node',
        toString(node),
        toString(status),
        concat('duration_ms=', toString(duration_ms), if(payload_truncated, ' truncated', ''), ' ', substring(payload, 1, 300))
    FROM agent_logs.events
    WHERE trace_id = {trace_id:String}

    UNION ALL

    SELECT
        toDateTime64(ts, 6, 'UTC'),
        'llm',
        concat(toString(node), ' ', toString(alias)),
        toString(status),
        concat(
            toString(model), ' tokens=', toString(total_tokens), ' cost_usd=', toString(cost_usd),
            ' latency_ms=', toString(latency_ms), if(error = '', '', concat(' error=', error))
        )
    FROM agent_logs.llm_calls
    WHERE trace_id = {trace_id:String}

    UNION ALL

    SELECT
        toDateTime64(ts, 6, 'UTC'),
        'sql',
        concat('attempt ', toString(attempt)),
        if(error = '', 'ok', 'error'),
        concat('query_id=', query_id, ' rows=', toString(rows), if(error = '', '', concat(' error=', error)))
    FROM agent_logs.sql_runs
    WHERE trace_id = {trace_id:String}

    UNION ALL

    SELECT
        toDateTime64(ts, 6, 'UTC'),
        'query_log',
        query_id,
        toString(type),
        concat(
            'duration_ms=', toString(query_duration_ms), ' read_rows=', toString(read_rows),
            ' result_rows=', toString(result_rows), if(exception = '', '', concat(' exception=', exception))
        )
    FROM agent_logs.trace_query_log
    WHERE trace_id = {trace_id:String}
)
ORDER BY ts, source
