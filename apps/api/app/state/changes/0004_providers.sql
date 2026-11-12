-- Model providers entered in the setup and on the Models page (DECISIONS §2,
-- §15). A provider's key is not here: it is the secret
-- provider:<id>:api_key. base_url is set for a model server (ollama,
-- openai_compatible) and empty for a hosted provider.
CREATE TABLE providers
(
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (kind IN ('openai', 'anthropic', 'gemini', 'ollama', 'openai_compatible')),
    base_url TEXT,
    created_at TEXT NOT NULL
);
