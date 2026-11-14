"""Long-lived objects the endpoints share, built on first use from the environment.

Each is a FastAPI dependency, so tests override it. A missing setting or an
uncompiled pack makes the endpoints that need it answer 503, while ``/health``
keeps working; a failure is not cached, so the next request tries again.
"""

from dataclasses import dataclass
from functools import cache
import logging
import os
from pathlib import Path
import threading

import httpx
import yaml

from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.api.agent import Agent
from app.api.rate_limit import RateLimiter
from app.config import load_settings, positive_int
from app.conversation.store import ConversationStore, conversations_client
from app.data.clickhouse import ClientWarehouse, QueryLimits
from app.llm.client import LLMError
from app.llm.clients import chat_client, embedding_client, index_embeddings
from app.llm.model_store import ClickHouseModelStore, model_tiers_client
from app.onboarding.documents import ClickHouseDocumentRegistry, DocumentService, pack_review_client
from app.admin.logs import AdminLogs, trace_reader_client
from app.eval.console import EvalReports, EvalRuns
from app.feedback.store import ClickHouseProposalStore, review_reader_client
from app.observability.log_writer import start_log_writer, writer_client
from app.onboarding.drafter import Drafter
from app.onboarding.review import ReviewService
from app.packs.compiler import CompileError, CompiledPack, load_compiled
from app.screening.screen import Screener
from app.search.client import QdrantSearch
from app.sources.client import source_admin_client
from app.sources.files import FileService
from app.sources.schedule import SourceScheduler
from app.sources.service import SourceService
from app.sources.sqlserver import SqlServer
from app.sources.store import SourceStore
from app.state.db import StateDb, data_dir, shared_state
from app.state.secrets import SecretVault, shared_vault


logger = logging.getLogger(__name__)


def unavailable(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


def get_state_db() -> StateDb:
    return shared_state()


def get_vault() -> SecretVault:
    return shared_vault()


@cache
def get_oidc_http() -> httpx.Client:
    """The HTTP client of OIDC discovery, JWKS and code exchanges."""
    return httpx.Client(follow_redirects=False)


@cache
def get_compiled() -> CompiledPack:
    settings = load_settings()
    if not settings.active_pack:
        raise unavailable("ACTIVE_PACK must be set")
    try:
        return load_compiled(Path(settings.compiled_pack_dir), settings.active_pack)
    except CompileError as error:
        raise unavailable(str(error)) from None


def get_compiled_or_none() -> CompiledPack | None:
    """The compiled active pack, or None while it was never compiled (a pack still under onboarding)."""
    try:
        return get_compiled()
    except HTTPException:
        return None


@dataclass(frozen=True)
class PackIdentity:
    name: str
    display_name: str
    # The pack's policy roles, in policies.yaml order.
    roles: list[str]


def _read(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.is_file() else {}


def pack_identity(compiled: CompiledPack | None) -> PackIdentity:
    """Name, display name and roles of the active pack: from ``compiled.json``, else from its pack files.

    A new company's pack is reviewed before its first compile, so sign-in, Review and Documents read the
    pack files until ``compile_pack`` has run; questions still need the compiled pack.
    """
    if compiled is not None:
        return PackIdentity(
            compiled.pack.name, compiled.pack.business_profile.display_name,
            [role.id for role in compiled.pack.policies.roles],
        )
    settings = load_settings()
    if not settings.active_pack:
        raise unavailable("ACTIVE_PACK must be set")
    pack_dir = Path(settings.packs_dir) / settings.active_pack
    if not (pack_dir / "policies.yaml").is_file():
        raise unavailable(
            f"pack {settings.active_pack} has no compiled.json and no pack files under {settings.packs_dir}; "
            "compile the pack first"
        )
    profile = _read(pack_dir / "business_profile.yaml")
    roles = [role["id"] for role in _read(pack_dir / "policies.yaml").get("roles") or [] if isinstance(role, dict)]
    return PackIdentity(settings.active_pack, str(profile.get("display_name") or settings.active_pack), roles)


def get_pack_identity(compiled: Annotated[CompiledPack | None, Depends(get_compiled_or_none)]) -> PackIdentity:
    return pack_identity(compiled)


_screener: Screener | None = None
_screener_lock = threading.Lock()


def get_screener() -> Screener:
    """The question screener, built once; without its model in ``GUARD_MODEL_DIR`` every question is refused.

    Building it loads the classifier, which takes seconds, so the api builds it in the background at startup.
    """
    global _screener
    with _screener_lock:
        if _screener is None:
            _screener = Screener.from_settings(load_settings())
        return _screener


def loaded_screener() -> Screener | None:
    """The screener if it is built; never builds it, so ``/health`` stays fast."""
    return _screener


def _build_screener() -> None:
    try:
        get_screener()
    except Exception:  # noqa: BLE001 - invalid settings leave screening unavailable; the next question tries again
        logger.exception("cannot build the question screener")


def build_screener_in_background() -> None:
    threading.Thread(target=_build_screener, name="screener", daemon=True).start()


@cache
def get_model_store() -> ClickHouseModelStore:
    try:
        return ClickHouseModelStore(model_tiers_client())
    except Exception as error:  # noqa: BLE001 - a missing password or unreachable ClickHouse
        raise unavailable(f"the model store is unavailable: {error}") from None


_call_log_writer = None
_call_log_lock = threading.Lock()


def _call_log():
    """The ``llm_calls`` writer of the api's calls outside a question: drafts and document embeddings."""
    global _call_log_writer
    with _call_log_lock:
        if _call_log_writer is None:
            try:
                _call_log_writer = start_log_writer(load_settings())
            except Exception:  # noqa: BLE001 - logging never blocks the call
                logger.exception("the llm_calls writer did not start")
                return None
        return _call_log_writer.enqueue


@cache
def get_agent() -> Agent:
    try:
        return Agent(load_settings(), get_compiled(), get_screener())
    except LLMError as error:
        raise unavailable(str(error)) from None


@cache
def get_conversation_store() -> ConversationStore:
    try:
        return ConversationStore(conversations_client())
    except RuntimeError as error:
        raise unavailable(str(error)) from None


@cache
def get_document_service() -> DocumentService:
    """The active pack's documents; chunks are screened and embedded like a compile does."""
    settings = load_settings()
    identity = pack_identity(get_compiled_or_none())
    try:
        registry = ClickHouseDocumentRegistry(pack_review_client())
        embeddings, _ = index_embeddings(call_log=_call_log())
    except Exception as error:  # noqa: BLE001 - a missing password, no embedding model, or ClickHouse unreachable
        raise unavailable(f"the document store is unavailable: {error}") from None
    return DocumentService(
        pack=identity.name, pack_roles=identity.roles, registry=registry,
        search=QdrantSearch(settings.qdrant_url), embeddings=embeddings, screener=get_screener(),
        store_dir=Path(settings.documents_dir), compiled_dir=Path(settings.compiled_pack_dir),
        max_bytes=settings.document_max_bytes,
    )


def get_pack_dir() -> Path:
    """The active pack's working tree, where reviewed and drafted YAML is written (never committed by the app)."""
    return Path(load_settings().packs_dir) / pack_identity(get_compiled_or_none()).name


@cache
def get_review_warehouse() -> ClientWarehouse:
    """Reads marts as ``pack_review`` for drafts and reviewer test-runs; each query sends its own limits."""
    try:
        return ClientWarehouse(pack_review_client())
    except Exception as error:  # noqa: BLE001 - a missing password or ClickHouse unreachable
        raise unavailable(f"the warehouse is unavailable: {error}") from None


@cache
def get_drafter() -> Drafter:
    return Drafter(chat_client(call_log=_call_log()), get_review_warehouse())


def get_review_service() -> ReviewService:
    """Built per request: it reads the pack files fresh each time."""
    settings = load_settings()
    return ReviewService(
        pack=pack_identity(get_compiled_or_none()).name, pack_dir=get_pack_dir(), registry=get_document_service().registry,
        warehouse=get_review_warehouse(), limits=QueryLimits.from_env(), compiled_dir=Path(settings.compiled_pack_dir),
        proposals=_optional_proposal_store(),
    )


@cache
def get_proposal_store() -> ClickHouseProposalStore:
    """Example proposals: read as the review reader, written as the insert-only log writer."""
    try:
        return ClickHouseProposalStore(review_reader_client(), writer_client())
    except Exception as error:  # noqa: BLE001 - a missing password or ClickHouse unreachable
        raise unavailable(f"the feedback store is unavailable: {error}") from None


def _optional_proposal_store() -> ClickHouseProposalStore | None:
    try:
        return get_proposal_store()
    except HTTPException:
        return None


def _run_eval(pack: str) -> int:
    """One run of the pack's eval set with jobs.eval itself, which stores its report in agent_logs."""
    from jobs import eval as eval_job  # noqa: PLC0415 - the api image ships jobs/; imported only when a run starts

    return eval_job.main(["--pack", pack, "--packs-dir", load_settings().packs_dir], runners_factory=eval_job.role_runners)


@cache
def get_eval_runs() -> EvalRuns:
    return EvalRuns(_run_eval)


@cache
def get_eval_reports() -> EvalReports:
    try:
        client = trace_reader_client()
    except Exception as error:  # noqa: BLE001 - a missing password or ClickHouse unreachable
        raise unavailable(f"the eval reports are unavailable: {error}") from None
    return EvalReports(lambda sql, parameters: client.query(sql, parameters=parameters).result_rows,
                       pack_identity(get_compiled_or_none()).name)


def get_admin_action_log() -> ClickHouseModelStore:
    """``agent_logs.admin_actions``, written by the same user as the Models page's changes."""
    return get_model_store()


@cache
def get_admin_logs() -> AdminLogs:
    """The run logs of the active pack, read as ``agent_logs_trace_reader``."""
    try:
        return AdminLogs.from_client(trace_reader_client(), pack_identity(get_compiled_or_none()).name)
    except Exception as error:  # noqa: BLE001 - a missing password or ClickHouse unreachable
        raise unavailable(f"the run logs are unavailable: {error}") from None


@cache
def get_rate_limiter() -> RateLimiter:
    return RateLimiter(load_settings().rate_limit_per_minute)


@cache
def get_file_service() -> FileService:
    """Uploaded data files: originals under the data directory, rows streamed into ``raw`` as ``source_admin``."""
    try:
        return FileService(get_source_store(), source_admin_client(), data_dir() / "sources" / "files",
                           positive_int(os.environ, "SOURCE_FILE_MAX_BYTES", 256 * 1024 * 1024))
    except Exception as error:  # noqa: BLE001 - a missing password or an invalid size cap
        raise unavailable(f"the file upload is unavailable: {error}") from None


@cache
def get_source_service() -> SourceService:
    """Connects, tests and syncs the sources of the Sources page as ``source_admin``."""
    try:
        return SourceService(get_source_store(), source_admin_client(), files=get_file_service(),
                             sqlserver=SqlServer(), vault=get_vault())
    except HTTPException:
        raise
    except Exception as error:  # noqa: BLE001 - a missing password or ClickHouse unreachable
        raise unavailable(f"the sources service is unavailable: {error}") from None


def get_source_store() -> SourceStore:
    return SourceStore(shared_state())


_source_scheduler: SourceScheduler | None = None


def start_source_scheduler() -> None:
    """Run the due copies in the background; without the ``source_admin`` password there is nothing to run them as."""
    global _source_scheduler
    try:
        _source_scheduler = SourceScheduler(get_source_service(), get_source_store())
    except HTTPException:
        logger.warning("scheduled source copies are off: CLICKHOUSE_SOURCE_ADMIN_PASSWORD is not set or ClickHouse is down")
        return
    _source_scheduler.start()


def close() -> None:
    """Flush and stop the agent's log writer if a question ever built the agent, and the api's call log."""
    if _source_scheduler is not None:
        _source_scheduler.stop()
    global _call_log_writer
    if get_agent.cache_info().currsize:
        get_agent().close()
    with _call_log_lock:
        if _call_log_writer is not None:
            _call_log_writer.close()
            _call_log_writer = None
