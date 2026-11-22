-- The model gateway inside the api writes llm_calls (DECISIONS §2, §10): each
-- row names the provider it called, and a model without a known price logs a
-- null cost instead of zero. Rows written through the LiteLLM Proxy keep an
-- empty provider and their alias.
ALTER TABLE agent_logs.llm_calls ADD COLUMN IF NOT EXISTS provider LowCardinality(String) AFTER tier;
ALTER TABLE agent_logs.llm_calls MODIFY COLUMN cost_usd Nullable(Float64);
