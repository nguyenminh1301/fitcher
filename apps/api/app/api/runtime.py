"""Long-lived objects the endpoints share, built on first use from the environment.

Each is a FastAPI dependency, so tests override it. A missing setting or an
uncompiled pack makes the endpoints that need it answer 503, while ``/health``
keeps working; a failure is not cached, so the next request tries again.

Several compiled packs live side by side, one per data source, and a request
serves one of them (DECISIONS §1): the pack named by ``?pack=`` (set by
``PackSelection``), the pack of the conversation a question belongs to, or
else the pack used last. The objects built for a pack (the compiled pack, the
agent, its documents, eval reports and run logs) are kept per pack name.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import cache
import logging
from datetime import UTC, datetime
import os
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs

import yaml

from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.api.agent import Agent
from app.api.limits import QuestionGate, one_job
from app.api.rate_limit import RateLimiter
from app.config import load_settings, positive_int
from app.conversation.store import ConversationStore, conversations_client
from app.data.clickhouse import ClientWarehouse, QueryLimits
from app.llm.client import LLMError
from app.llm.clients import chat_client, embedding_client, index_embeddings, shared_routes
from app.llm.routes import RouteError
from app.llm.model_store import ClickHouseModelStore, model_tiers_client
from app.onboarding.documents import ClickHouseDocumentRegistry, DocumentService, compile_lock_path, pack_review_client
from app.admin.logs import AdminLogs, trace_reader_client
from app.eval.console import EvalReports, EvalRuns
from app.feedback.store import ClickHouseProposalStore, review_reader_client
from app.observability.log_writer import start_log_writer, writer_client
from app.onboarding.drafter import Drafter
from app.onboarding.review import ReviewService
from app.onboarding.client import pack_admin_client
from app.onboarding.drafter import TIER as DRAFT_TIER
from app.onboarding.instant import InstantPipeline, InstantWarehouse
from app.packs.active import active_pack, set_active_pack
from app.packs.models import READER_ROLE
from app.packs.compiler import CompileError, CompiledPack, compile_pack, load_compiled
from app.packs.search_indices import INDEX_NAMES, alias_name
from app.state.settings import Settings, documents_enabled
from app.screening.screen import Screener
from app.search.engine import open_search
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


PACK_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_requested_pack: ContextVar[str | None] = ContextVar("requested_pack", default=None)


def last_used_pack() -> str:
    """``ACTIVE_PACK``, else the pack last asked or built (app/packs/active.py); a new chat starts on it."""
    return active_pack(get_state_db())


def current_pack() -> str:
    """The pack this request serves: the one it named or its conversation's, else the pack used last."""
    return _requested_pack.get() or last_used_pack()


@contextmanager
def serving(pack: str) -> Iterator[None]:
    """Serve ``pack`` for the code run inside, as a ``?pack=`` request does."""
    token = _requested_pack.set(pack or None)
    try:
        yield
    finally:
        _requested_pack.reset(token)


class PackSelection:
    """ASGI middleware: a request's ``?pack=`` names the pack the request serves; an invalid name is refused."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        names = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("pack") or []
        if not names or not names[-1]:
            return await self.app(scope, receive, send)
        if not PACK_NAME.fullmatch(names[-1]):
            from fastapi.responses import JSONResponse  # noqa: PLC0415 - only built for a refused request

            return await JSONResponse({"detail": "pack must be a pack name"}, status_code=422)(scope, receive, send)
        token = _requested_pack.set(names[-1])
        try:
            return await self.app(scope, receive, send)
        finally:
            _requested_pack.reset(token)


class PerPack:
    """One object per pack name, built on first use; a failure is not kept, so the next use tries again."""

    def __init__(self, build: Callable[[str], object], close: Callable[[object], None] | None = None):
        self._build = build
        self._close = close
        self._items: dict[str, object] = {}
        self._lock = threading.Lock()

    def __call__(self, name: str):
        with self._lock:
            if name not in self._items:
                self._items[name] = self._build(name)
            return self._items[name]

    def forget(self, name: str | None = None) -> None:
        """Drop the object of ``name``, or every object, closing each one."""
        with self._lock:
            if name is None:
                dropped = list(self._items.values())
                self._items.clear()
            else:
                dropped = [self._items.pop(name)] if name in self._items else []
        for item in dropped:
            if self._close is not None:
                self._close(item)

    def __len__(self) -> int:
        return len(self._items)


def _load_compiled(name: str) -> CompiledPack:
    try:
        return load_compiled(Path(load_settings().compiled_pack_dir), name)
    except CompileError as error:
        raise unavailable(str(error)) from None


compiled_packs = PerPack(_load_compiled)


def get_compiled() -> CompiledPack:
    """The compiled pack this request serves."""
    name = current_pack()
    if not name:
        raise unavailable("no pack is active: connect a source and build its pack, or set ACTIVE_PACK")
    return compiled_packs(name)


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
    # The pack's roles: its one reader role, or the roles an older compiled pack still lists.
    roles: list[str]


def _read(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.is_file() else {}


def pack_identity(compiled: CompiledPack | None) -> PackIdentity:
    """Name, display name and roles of the active pack: from ``compiled.json``, else from its pack files.

    A new company's pack is reviewed before its first compile, so ``/pack``, Review and Documents read the
    pack files until ``compile_pack`` has run; questions still need the compiled pack.
    """
    if compiled is not None:
        return PackIdentity(
            compiled.pack.name, compiled.pack.business_profile.display_name,
            [role.id for role in compiled.pack.policies.roles],
        )
    settings = load_settings()
    name = current_pack()
    if not name:
        raise unavailable("no pack is active: connect a source and build its pack, or set ACTIVE_PACK")
    pack_dir = Path(settings.packs_dir) / name
    if not (pack_dir / "datasets.yaml").is_file():
        raise unavailable(
            f"pack {name} has no compiled.json and no pack files under {settings.packs_dir}; "
            "compile the pack first"
        )
    profile = _read(pack_dir / "business_profile.yaml")
    return PackIdentity(name, str(profile.get("display_name") or name), [READER_ROLE])


def get_pack_identity(compiled: Annotated[CompiledPack | None, Depends(get_compiled_or_none)]) -> PackIdentity:
    return pack_identity(compiled)


def get_pack_identity_or_none(
    compiled: Annotated[CompiledPack | None, Depends(get_compiled_or_none)],
) -> PackIdentity | None:
    """The active pack, or None on an instance where no pack is active yet: its setup still needs the signed-in user."""
    if compiled is None and not current_pack():
        return None
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


def _build_agent(name: str) -> Agent:
    try:
        return Agent(load_settings(), compiled_packs(name), get_screener(), lambda: documents_enabled(get_state_db()))
    except LLMError as error:
        raise unavailable(str(error)) from None


agents = PerPack(_build_agent, close=lambda agent: agent.close())


def get_agent() -> Agent:
    """The agent of the pack this request serves."""
    get_compiled()
    return agents(current_pack())


@cache
def get_conversation_store() -> ConversationStore:
    try:
        return ConversationStore(conversations_client(),
                                 earlier_pack=lambda: Settings(get_state_db()).get("pack", "earlier_conversations") or "")
    except RuntimeError as error:
        raise unavailable(str(error)) from None


def get_document_service() -> DocumentService:
    """The documents of the pack this request serves; chunks are screened and embedded like a compile does."""
    return document_services(pack_identity(get_compiled_or_none()).name)


def _build_document_service(name: str) -> DocumentService:
    settings = load_settings()
    with serving(name):
        identity = pack_identity(get_compiled_or_none())
    try:
        registry = ClickHouseDocumentRegistry(pack_review_client())
        embeddings, _ = index_embeddings(call_log=_call_log())
    except Exception as error:  # noqa: BLE001 - a missing password, no embedding model, or ClickHouse unreachable
        raise unavailable(f"the document store is unavailable: {error}") from None
    return DocumentService(
        pack=identity.name, pack_roles=identity.roles, registry=registry,
        search=open_search(), embeddings=embeddings, screener=get_screener(),
        store_dir=Path(settings.documents_dir), compiled_dir=Path(settings.compiled_pack_dir),
        max_bytes=settings.document_max_bytes,
    )


document_services = PerPack(_build_document_service)


def get_document_service_or_none() -> DocumentService | None:
    """The documents of the pack this request serves, or None without a pack or document store."""
    try:
        return get_document_service()
    except HTTPException:
        return None


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
    def execute(pack: str) -> int:
        with one_job():  # an eval run waits for a sync or a compile in progress, and they for it
            return _run_eval(pack)

    return EvalRuns(execute)


def _build_eval_reports(name: str) -> EvalReports:
    try:
        client = trace_reader_client()
    except Exception as error:  # noqa: BLE001 - a missing password or ClickHouse unreachable
        raise unavailable(f"the eval reports are unavailable: {error}") from None
    return EvalReports(lambda sql, parameters: client.query(sql, parameters=parameters).result_rows, name)


eval_reports = PerPack(_build_eval_reports)


def get_eval_reports() -> EvalReports:
    """The eval reports of the pack this request serves."""
    return eval_reports(pack_identity(get_compiled_or_none()).name)


def get_admin_action_log() -> ClickHouseModelStore:
    """``agent_logs.admin_actions``, written by the same user as the Models page's changes."""
    return get_model_store()


def _build_admin_logs(name: str) -> AdminLogs:
    try:
        return AdminLogs.from_client(trace_reader_client(), name)
    except Exception as error:  # noqa: BLE001 - a missing password or ClickHouse unreachable
        raise unavailable(f"the run logs are unavailable: {error}") from None


admin_logs = PerPack(_build_admin_logs)


def get_admin_logs() -> AdminLogs:
    """The run logs of the pack this request serves, read as ``agent_logs_trace_reader``."""
    try:
        name = pack_identity(get_compiled_or_none()).name
    except HTTPException:
        name = ""  # without any pack the logs still answer for every pack's model calls
    return admin_logs(name)


@cache
def get_question_gate() -> QuestionGate:
    """The questions answered at once; ``limits.concurrent_questions`` is read again as each question queues."""
    return QuestionGate(lambda: Settings(get_state_db()).get("limits", "concurrent_questions"))


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


def _model_missing() -> str | None:
    """Why no model can draft a pack yet, in the words the Models page uses, or None."""
    try:
        shared_routes().route(DRAFT_TIER)
    except RouteError as error:
        return str(error)
    return None


def _compile_instant(pack_dir: Path) -> object:
    """Compile an instant pack as ``pack_admin``, as ``jobs.compile_pack`` does as the admin user."""
    settings = load_settings()
    compiled_dir = Path(settings.compiled_pack_dir)
    with one_job():
        return _compile_instant_now(pack_dir, settings, compiled_dir)


def _compile_instant_now(pack_dir: Path, settings, compiled_dir: Path) -> object:
    lock = compile_lock_path(compiled_dir, pack_dir.name)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    try:
        embeddings, label = index_embeddings(call_log=_call_log())
        warehouse = InstantWarehouse(pack_admin_client())
        return compile_pack(
            pack_dir, warehouse=warehouse, access=warehouse, agent_secret=os.environ.get("CLICKHOUSE_AGENT_PASSWORD", ""),
            top_k=settings.column_values_top_k, search=open_search(), embeddings=embeddings,
            output_dir=compiled_dir, schema_dir=pack_dir.parent / "_schema", screener=get_screener(),
            # With company documents off no chunk is indexed; turning them on again indexes them at the next compile.
            registry=ClickHouseDocumentRegistry(pack_review_client()) if documents_enabled(get_state_db()) else None,
            documents_dir=Path(settings.documents_dir),
            embedding_alias=label,
        )
    finally:
        lock.unlink(missing_ok=True)


def packs_missing_their_index(compiled_dir: Path, packs_dir: Path, live: set[str], active: str) -> list[str]:
    """Compiled packs, the active one first, whose search collections are not all live but whose files are present."""
    found = sorted(path.parent.name for path in compiled_dir.glob("*/compiled.json"))
    missing = [
        pack for pack in found
        if (packs_dir / pack).is_dir() and not compile_lock_path(compiled_dir, pack).exists()
        and not all(alias_name(pack, index) in live for index in INDEX_NAMES)
    ]
    return sorted(missing, key=lambda pack: pack != active)


def _rebuild_missing_indices() -> None:
    settings = load_settings()
    try:
        live = set(open_search().live())
    except Exception as error:  # noqa: BLE001 - a missing index is rebuilt at the next start
        logger.warning("search index check skipped: %s", error)
        return
    for pack in packs_missing_their_index(Path(settings.compiled_pack_dir), Path(settings.packs_dir), live, current_pack()):
        logger.info("compiling pack %s: its search index is missing, as after an upgrade of the search engine", pack)
        try:
            _compile_instant(Path(settings.packs_dir) / pack)
        except Exception:  # noqa: BLE001 - one pack's failure must not stop the others or the api
            logger.exception("compiling pack %s to rebuild its search index failed", pack)
            continue
        reload_pack(pack)


def rebuild_missing_indices_in_background() -> None:
    """Compile every compiled pack whose search index is missing, as after an upgrade that moved search to a new engine."""
    threading.Thread(target=_rebuild_missing_indices, name="search-index", daemon=True).start()


def _activate_instant(pack: str) -> None:
    """A built pack serves its source's conversations and is where a new chat starts; other packs are untouched."""
    set_active_pack(get_state_db(), pack)
    reload_pack(pack)


@cache
def get_instant_pipeline() -> InstantPipeline:
    settings = load_settings()
    packs_dir = Path(settings.packs_dir)
    client = pack_admin_client()
    return InstantPipeline(
        store=get_source_store(), client=client, packs_dir=packs_dir, schema_dir=packs_dir / "_schema",
        drafter=lambda: Drafter(chat_client(call_log=_call_log()), InstantWarehouse(client)),
        compile_pack=_compile_instant, activate=_activate_instant, model_missing=_model_missing,
    )


def pack_status(name: str) -> tuple[str, int, str | None]:
    """The status of the pack built from source ``name``, its dataset count and its latest build error."""
    job = get_instant_pipeline().latest_job(name) if get_instant_pipeline.cache_info().currsize else None
    if job is not None and job.status == "running":
        return "building", 0, None
    error = job.error if job is not None and job.status == "failed" else None
    if (Path(load_settings().compiled_pack_dir) / name / "compiled.json").is_file():
        try:
            return "ready", len(compiled_packs(name).pack.datasets.datasets), error
        except HTTPException as refused:
            return "failed", 0, error or str(refused.detail)
    return ("failed", 0, error) if error else ("none", 0, None)


# The objects built per pack; ``reload_pack`` drops them when the pack is compiled again.
PACK_DEPENDENCIES = (compiled_packs, agents, document_services, eval_reports, admin_logs)


def reload_pack(name: str | None = None) -> None:
    """Forget the objects of pack ``name`` (or of every pack), closing its agent's log writer."""
    for dependency in PACK_DEPENDENCIES:
        dependency.forget(name)


def close() -> None:
    """Flush and stop the agent's log writer if a question ever built the agent, and the api's call log."""
    if _source_scheduler is not None:
        _source_scheduler.stop()
    global _call_log_writer
    agents.forget()
    with _call_log_lock:
        if _call_log_writer is not None:
            _call_log_writer.close()
            _call_log_writer = None
