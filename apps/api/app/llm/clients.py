"""The model clients of the api and the jobs, built from the shared app state (DECISIONS §2).

Every caller gets its chat client and embedding client here, so the provider,
model and key of each tier always come from the app state: the gateway reads
the mapping on every call. A local embedding model is loaded once per process
and shared by every client that uses it. ``bootstrap`` creates the environment's providers
when the app state has none, and copies the tier mapping an admin made on the
old Models page (``data_meta.model_tiers``) once.

``job_call_log`` gives a job its ``llm_calls`` writer, so the Costs page
counts the calls of compiles, drafts and evals like those of questions.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import threading

from app.config import load_settings
from app.llm.call_log import CallLog
from app.llm.embeddings import EmbeddingClient, EmbeddingError
from app.llm.local_embeddings import LocalEmbeddings
from app.llm.gateway import Gateway, GatewayEmbeddings
from app.llm.providers import ProviderStore
from app.llm.routes import bootstrap_providers, EmbeddingChoice, SettingsRoutes, TierMapping, TierModel
from app.state.db import shared_state
from app.state.secrets import shared_vault

_log = logging.getLogger(__name__)
_local: dict[str, LocalEmbeddings] = {}
_local_lock = threading.Lock()


def _mapping() -> tuple[TierMapping, ProviderStore]:
    store = ProviderStore(shared_state(), shared_vault())
    return TierMapping(shared_state(), store), store


def shared_routes(overrides: Mapping[str, TierModel] | None = None) -> SettingsRoutes:
    mapping, store = _mapping()
    return SettingsRoutes(mapping, store, shared_vault().reader(), overrides)


def chat_client(*, call_log: CallLog | None = None, temperature: float | None = None,
                overrides: Mapping[str, TierModel] | None = None) -> Gateway:
    return Gateway(shared_routes(overrides), call_log=call_log, temperature=temperature)


def embedding_choice() -> EmbeddingChoice:
    return _mapping()[0].embedding()


def _local_model(choice: EmbeddingChoice) -> LocalEmbeddings:
    with _local_lock:
        if choice.model not in _local:
            _local[choice.model] = LocalEmbeddings(choice.model, choice.dimensions)
        return _local[choice.model]


def embedding_client(dimensions: int, *, call_log: CallLog | None = None) -> EmbeddingClient:
    """Embeddings of ``dimensions`` floats: a compiled pack's size for queries, the setting's size to index.

    A local model returns only its own size, so a pack compiled at another size fails each query with
    ``EmbeddingError`` until it is recompiled.
    """
    choice = embedding_choice()
    if choice.backend == "local":
        if dimensions != choice.dimensions:
            return _Mismatched(choice, dimensions)
        return _local_model(choice)
    return GatewayEmbeddings(shared_routes(), dimensions, call_log=call_log)


class _Mismatched:
    """Stands in for an embedding model whose vector size differs from the pack's until it is recompiled."""

    def __init__(self, choice: EmbeddingChoice, dimensions: int):
        self.dimensions = dimensions
        self._choice = choice

    def embed(self, texts) -> list[list[float]]:
        raise EmbeddingError(
            f"the pack was indexed with {self.dimensions} dimensions but the embedding model {self._choice.label} "
            f"returns {self._choice.dimensions}; recompile the pack"
        )


def embedding_setting() -> tuple[str, int]:
    """The embed tier's label (``local/<model>`` or ``<provider>/<model>``) and vector size."""
    choice = embedding_choice()
    return choice.label, choice.dimensions


def index_embeddings(*, call_log: CallLog | None = None) -> tuple[EmbeddingClient, str]:
    """The client that indexes pack content at the setting's size, and the setting's label for ``compiled.json``."""
    label, dimensions = embedding_setting()
    return embedding_client(dimensions, call_log=call_log), label


def embedding_label() -> str:
    return embedding_setting()[0]


def compiled_embedding() -> tuple[str, int] | None:
    """The embedding label and size the active pack was compiled with, or None without a compiled pack."""
    settings = load_settings()
    path = Path(settings.compiled_pack_dir) / settings.active_pack / "compiled.json"
    if not settings.active_pack or not path.is_file():
        return None
    try:
        compiled = json.loads(path.read_text(encoding="utf-8"))
        return str(compiled.get("embedding_alias") or ""), int(compiled["embedding_dimensions"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def stored_aliases() -> dict[str, str]:
    """The tier mapping of the old Models page in ``data_meta.model_tiers``; empty when it cannot be read."""
    from app.llm.model_store import ClickHouseModelStore, model_tiers_client  # noqa: PLC0415 - only for bootstrap

    try:
        return ClickHouseModelStore(model_tiers_client()).read()
    except Exception:  # noqa: BLE001 - no password, no ClickHouse or no table: nothing to copy
        return {}


def bootstrap() -> None:
    bootstrap_providers(legacy_aliases=stored_aliases, compiled_embedding=compiled_embedding)


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
