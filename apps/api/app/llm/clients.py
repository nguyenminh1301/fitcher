"""The model clients of the api and the jobs, built from the shared app state (DECISIONS §2).

Every caller gets its chat client and embedding client here, so the provider,
model and key of each tier always come from the app state: the gateway reads
the mapping on every call. ``bootstrap`` creates the environment's providers
when the app state has none, and copies the tier mapping an admin made on the
old Models page (``data_meta.model_tiers``) once.

``job_call_log`` gives a job its ``llm_calls`` writer, so the Costs page
counts the calls of compiles, drafts and evals like those of questions.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import logging
import os

from app.config import load_settings
from app.llm.call_log import CallLog
from app.llm.embeddings import EmbeddingError
from app.llm.gateway import Gateway, GatewayEmbeddings
from app.llm.providers import ProviderStore
from app.llm.routes import bootstrap_providers, SettingsRoutes, TierMapping, TierModel
from app.state.db import shared_state
from app.state.secrets import shared_vault

_log = logging.getLogger(__name__)


def _mapping() -> tuple[TierMapping, ProviderStore]:
    store = ProviderStore(shared_state(), shared_vault())
    return TierMapping(shared_state(), store), store


def shared_routes(overrides: Mapping[str, TierModel] | None = None) -> SettingsRoutes:
    mapping, store = _mapping()
    return SettingsRoutes(mapping, store, shared_vault().reader(), overrides)


def chat_client(*, call_log: CallLog | None = None, temperature: float | None = None,
                overrides: Mapping[str, TierModel] | None = None) -> Gateway:
    return Gateway(shared_routes(overrides), call_log=call_log, temperature=temperature)


def embedding_client(dimensions: int, *, call_log: CallLog | None = None) -> GatewayEmbeddings:
    """Embeddings of ``dimensions`` floats: a compiled pack's size for queries, the setting's size to index."""
    return GatewayEmbeddings(shared_routes(), dimensions, call_log=call_log)


def embedding_setting() -> tuple[str, int] | None:
    """The embed tier's ``provider/model`` label and vector size, or None when no embedding model is set."""
    mapping, _ = _mapping()
    embedding = mapping.embedding()
    if embedding is None:
        return None
    return f"{embedding[0].provider_id}/{embedding[0].model}", embedding[1]


def index_embeddings(*, call_log: CallLog | None = None) -> tuple[GatewayEmbeddings, str]:
    """The client that indexes pack content at the setting's size, and the setting's label for ``compiled.json``."""
    setting = embedding_setting()
    if setting is None:
        raise EmbeddingError("no embedding model is set; add a provider on the Models page")
    label, dimensions = setting
    return embedding_client(dimensions, call_log=call_log), label


def embedding_label() -> str | None:
    setting = embedding_setting()
    return setting[0] if setting else None


def stored_aliases() -> dict[str, str]:
    """The tier mapping of the old Models page in ``data_meta.model_tiers``; empty when it cannot be read."""
    from app.llm.model_store import ClickHouseModelStore, model_tiers_client  # noqa: PLC0415 - only for bootstrap

    try:
        return ClickHouseModelStore(model_tiers_client()).read()
    except Exception:  # noqa: BLE001 - no password, no ClickHouse or no table: nothing to copy
        return {}


def bootstrap() -> None:
    bootstrap_providers(legacy_aliases=stored_aliases)


@contextmanager
def job_call_log() -> Iterator[CallLog | None]:
    """The ``llm_calls`` writer of a job, flushed when the block ends; None without the writer's password."""
    from app.observability.log_writer import start_log_writer  # noqa: PLC0415 - starts a thread, jobs only

    if not os.environ.get("CLICKHOUSE_LOGS_WRITER_PASSWORD"):
        yield None
        return
    try:
        writer = start_log_writer(load_settings())
    except Exception as error:  # noqa: BLE001 - logging never stops the job
        _log.warning("llm_calls rows of this job are not written: %s", error)
        yield None
        return
    try:
        yield writer.enqueue
    finally:
        writer.close()
