-- A chat tier has an ordered fallback chain of models (DECISIONS §2): a call
-- that replaced a failed call of the chain names that call's id. A failed call
-- now has an id of its own so it can be named.
ALTER TABLE agent_logs.llm_calls ADD COLUMN IF NOT EXISTS fallback_of String DEFAULT '' AFTER error;
