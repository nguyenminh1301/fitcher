"""Engine settings read from the environment.

Compose sets these for the ``api`` and ``jobs`` services; ``.env.example``
documents them. Nothing here names a pack, table or model.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import os


class SettingsError(RuntimeError):
    """A required setting is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    active_pack: str
    opensearch_url: str
    litellm_base_url: str
    litellm_master_key: str
    embedding_dimensions: int
    column_values_top_k: int
    compiled_pack_dir: str
    # agent_logs writer: records per batch, flush interval and queue bound.
    log_batch_size: int
    log_flush_interval_ms: int
    log_queue_max: int
    # Access token checks (Phase 7); empty values leave the authenticated endpoints unavailable.
    keycloak_issuer: str
    keycloak_audience: str
    keycloak_jwks_url: str
    # Questions per user per minute on /ask, refilled evenly; one api worker holds the buckets.
    rate_limit_per_minute: int


def positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name) or str(default)
    try:
        value = int(raw)
    except ValueError:
        raise SettingsError(f"{name} must be an integer, got {raw!r}") from None
    if value <= 0:
        raise SettingsError(f"{name} must be positive, got {value}")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    return Settings(
        active_pack=env.get("ACTIVE_PACK", ""),
        opensearch_url=env.get("OPENSEARCH_URL", "http://opensearch:9200").rstrip("/"),
        litellm_base_url=env.get("LITELLM_BASE_URL", "http://litellm:4000").rstrip("/"),
        litellm_master_key=env.get("LITELLM_MASTER_KEY", ""),
        embedding_dimensions=positive_int(env, "EMBEDDING_DIMENSIONS", 1024),
        column_values_top_k=positive_int(env, "COLUMN_VALUES_TOP_K", 10_000),
        compiled_pack_dir=env.get("COMPILED_PACK_DIR", "build/packs"),
        log_batch_size=positive_int(env, "LOG_BATCH_SIZE", 100),
        log_flush_interval_ms=positive_int(env, "LOG_FLUSH_INTERVAL_MS", 1000),
        log_queue_max=positive_int(env, "LOG_QUEUE_MAX", 10_000),
        keycloak_issuer=env.get("KEYCLOAK_ISSUER", ""),
        keycloak_audience=env.get("KEYCLOAK_AUDIENCE", ""),
        keycloak_jwks_url=env.get("KEYCLOAK_JWKS_URL", ""),
        rate_limit_per_minute=positive_int(env, "RATE_LIMIT_PER_MINUTE", 10),
    )
