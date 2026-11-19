-- Several API keys per provider, an ordered fallback chain of models per chat
-- tier, and how the chains are chosen (DECISIONS §2).
--
-- provider_keys lists a provider's keys; each key's value is the secret
-- provider:<provider id>:key:<key id>. A key stored before this change keeps its
-- secret provider:<provider id>:api_key and becomes the key with id "legacy":
-- a secret's name is part of its encryption, so it cannot be renamed here.
CREATE TABLE IF NOT EXISTS provider_keys
(
    id TEXT NOT NULL,
    provider_id TEXT NOT NULL REFERENCES providers (id) ON DELETE CASCADE,
    label TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (provider_id, id)
);

-- The models a chat tier tries in order; position 0 answers unless it fails.
CREATE TABLE IF NOT EXISTS tier_chain
(
    tier TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    provider_id TEXT NOT NULL REFERENCES providers (id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    PRIMARY KEY (tier, position)
);

-- manual: the owner's chains; auto_free and auto_best: chosen from the model catalog.
CREATE TABLE IF NOT EXISTS model_mode
(
    id INTEGER PRIMARY KEY CHECK (id = 1),
    mode TEXT NOT NULL CHECK (mode IN ('auto_free', 'auto_best', 'manual')),
    refreshed_at TEXT
);

INSERT OR IGNORE INTO provider_keys (id, provider_id, label, created_at)
SELECT 'legacy', p.id, '', p.created_at
FROM providers AS p
WHERE EXISTS (SELECT 1 FROM secrets WHERE name = 'provider:' || p.id || ':api_key');

INSERT OR IGNORE INTO model_mode (id, mode, refreshed_at) VALUES (1, 'manual', NULL);

-- Each tier's single model becomes the first link of its chain.
INSERT OR IGNORE INTO tier_chain (tier, position, provider_id, model)
SELECT s.key, 0, json_extract(s.value, '$.provider_id'), json_extract(s.value, '$.model')
FROM settings AS s
WHERE s.group_name = 'llm.tiers'
  AND json_extract(s.value, '$.provider_id') IN (SELECT id FROM providers)
  AND coalesce(json_extract(s.value, '$.model'), '') != '';

DELETE FROM settings WHERE group_name = 'llm.tiers';
