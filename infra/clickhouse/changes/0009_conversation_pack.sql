-- Each conversation keeps the pack of the source it was started on (DECISIONS §1,
-- §15). A conversation stored before this change has an empty pack and keeps the
-- pack the instance used then, which the app state records.
ALTER TABLE agent_logs.conversations ADD COLUMN IF NOT EXISTS pack String DEFAULT '' AFTER group_id;
