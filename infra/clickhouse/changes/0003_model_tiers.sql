-- The model tier mapping an admin sets on the console's Models page
-- (DECISIONS §2 Model tiers, §15). One row per change; the latest
-- changed_at of a tier wins. A tier without a row keeps its MODEL_TIER_<TIER>
-- default. Written and read by the model_tiers_admin user only.
CREATE TABLE IF NOT EXISTS data_meta.model_tiers
(
    tier LowCardinality(String),
    alias String,
    changed_by String,
    changed_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(changed_at)
ORDER BY tier;
