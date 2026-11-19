"""The optional prompt-injection classifier (DECISIONS §9): its engine, switch and model download.

The EN/VI rules always screen; the classifier is turned on and off here and is
off on a new instance. It runs through a provider that hosts Llama Prompt
Guard (the default engine) or on this computer from an ONNX model
(``local_onnx``). That model is downloaded from the Models page
(``POST /screening/classifier/download``) or, in the Compose stack, exported
by the ``guard-model`` job. Once the classifier is on, screening fails closed
whenever it cannot score. Each change is written to
``agent_logs.admin_actions``. The endpoints need the ``admin`` role, which the
owner holds.

``POST`` and ``DELETE /screening/classifier`` keep turning the classifier on
and off with the engine already chosen; ``PUT`` also chooses the engine.
"""

import json
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.console import require_admin
from app.api.runtime import get_admin_action_log, get_screener, get_vault
from app.api.setup import get_state_db
from app.auth.principal import Principal
from app.config import load_settings
from app.contracts.screening import ClassifierChange, ClassifierDownload, ClassifierStatus
from app.llm.providers import ProviderNotFound, ProviderStore
from app.observability.events import AdminActionRecord, utc_now
from app.screening.classifier import MODEL_FILE, TOKENIZER_FILE, VERSION_FILE
from app.screening.download import guard_download, GuardDownload, LICENSE, REPO, REVISION
from app.screening.provider_engine import DEFAULT_MODEL
from app.screening.screen import Screener
from app.state.db import StateDb
from app.state.secrets import SecretVault
from app.state.settings import Settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/screening")
Admin = Annotated[Principal, Depends(require_admin)]
FETCH_HINT = "download it on the Models page"


def get_model_dir() -> Path:
    return Path(load_settings().guard_model_dir)


def get_classifier_screener() -> Screener:
    return get_screener()


def get_download(model_dir: Annotated[Path, Depends(get_model_dir)]) -> GuardDownload:
    return guard_download(model_dir, on_done=lambda: get_screener().reload())


State = Annotated[StateDb, Depends(get_state_db)]
ModelDir = Annotated[Path, Depends(get_model_dir)]
Download = Annotated[GuardDownload, Depends(get_download)]
Log = Annotated[object, Depends(get_admin_action_log)]
ScreenerDep = Annotated[Screener, Depends(get_classifier_screener)]


def _present(model_dir: Path) -> bool:
    return (model_dir / MODEL_FILE).is_file() and (model_dir / TOKENIZER_FILE).is_file()


def _download_view(download: GuardDownload) -> ClassifierDownload | None:
    progress = download.progress
    if progress.state == "idle":
        return None
    return ClassifierDownload(state=progress.state, bytes_done=progress.bytes_done, bytes_total=progress.bytes_total,
                              error=progress.error)


def _status(db: StateDb, model_dir: Path, download: GuardDownload | None = None) -> ClassifierStatus:
    settings = Settings(db)
    present = _present(model_dir)
    version = None
    if present:
        try:
            version = str(json.loads((model_dir / VERSION_FILE).read_text(encoding="utf-8")).get("version") or "") or None
        except (OSError, ValueError, AttributeError):
            version = None
    engine = settings.get("screening", "classifier_engine")
    return ClassifierStatus(
        enabled=settings.get("screening", "classifier_enabled"), model_present=present, version=version, engine=engine,
        provider_id=settings.get("screening", "classifier_provider_id"),
        model=settings.get("screening", "classifier_model") or DEFAULT_MODEL,
        download=_download_view(download) if download is not None else None,
        download_source=f"{REPO}@{REVISION[:7]}", license=LICENSE,
    )


def _described(state: ClassifierStatus) -> str:
    if not state.enabled:
        return "off"
    if state.engine == "local_onnx":
        return "on: this computer"
    return f"on: {state.provider_id}/{state.model}"


def _record(log, admin: Principal, before: ClassifierStatus, after: ClassifierStatus) -> None:
    try:
        log.record_action(AdminActionRecord(ts=utc_now(), actor=admin.user_id, action="screening_classifier",
                                            target="classifier", old_value=_described(before),
                                            new_value=_described(after)))
    except Exception:  # noqa: BLE001 - the change stands; the failure is logged
        logger.exception("the screening classifier change was not recorded")


def _apply(db: StateDb, vault: SecretVault, model_dir: Path, change: ClassifierChange) -> None:
    """Check and store the change; the classifier must be able to run before it is turned on."""
    if change.engine == "provider":
        if change.enabled and not change.provider_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="choose the provider that runs the classifier")
        if change.provider_id:
            try:
                ProviderStore(db, vault).get(change.provider_id)
            except ProviderNotFound as error:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    elif change.enabled and not _present(model_dir):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail=f"the classifier's model is not in {model_dir}; {FETCH_HINT}")
    settings = Settings(db)
    settings.set("screening", "classifier_engine", change.engine)
    if change.provider_id is not None:
        settings.set("screening", "classifier_provider_id", change.provider_id)
    if change.model is not None:
        settings.set("screening", "classifier_model", change.model.strip() or DEFAULT_MODEL)
    settings.set("screening", "classifier_enabled", change.enabled)


@router.get("/classifier")
def classifier_status(_: Admin, db: State, model_dir: ModelDir, download: Download) -> ClassifierStatus:
    return _status(db, model_dir, download)


@router.put("/classifier")
def change_classifier(body: ClassifierChange, admin: Admin, db: State, model_dir: ModelDir, download: Download,
                      log: Log, screener: ScreenerDep, vault: Annotated[SecretVault, Depends(get_vault)]) -> ClassifierStatus:
    before = _status(db, model_dir)
    _apply(db, vault, model_dir, body)
    screener.reload()
    after = _status(db, model_dir, download)
    _record(log, admin, before, after)
    return after


@router.post("/classifier")
def turn_classifier_on(admin: Admin, db: State, model_dir: ModelDir, download: Download, log: Log,
                       screener: ScreenerDep, vault: Annotated[SecretVault, Depends(get_vault)]) -> ClassifierStatus:
    before = _status(db, model_dir)
    engine = before.engine
    # An instance whose model was exported by the guard-model job and that names no provider runs it here.
    if engine == "provider" and not before.provider_id and _present(model_dir):
        engine = "local_onnx"
    _apply(db, vault, model_dir, ClassifierChange(enabled=True, engine=engine, provider_id=before.provider_id))
    screener.reload()
    after = _status(db, model_dir, download)
    _record(log, admin, before, after)
    return after


@router.delete("/classifier")
def turn_classifier_off(admin: Admin, db: State, model_dir: ModelDir, download: Download, log: Log) -> ClassifierStatus:
    before = _status(db, model_dir)
    Settings(db).set("screening", "classifier_enabled", False)
    after = _status(db, model_dir, download)
    _record(log, admin, before, after)
    return after


@router.get("/classifier/download")
def download_progress(_: Admin, download: Download) -> ClassifierDownload:
    return _download_view(download) or ClassifierDownload(state="idle", bytes_done=0,
                                                           bytes_total=download.progress.bytes_total)


@router.post("/classifier/download", status_code=status.HTTP_202_ACCEPTED)
def start_download(_: Admin, download: Download) -> ClassifierDownload:
    """Download the pinned model in the background; ``GET`` follows it."""
    download.start()
    return _download_view(download)


@router.delete("/classifier/download")
def cancel_or_remove_download(_: Admin, db: State, model_dir: ModelDir, download: Download) -> ClassifierDownload:
    """Cancel a running download, or remove the downloaded model while the classifier does not use it."""
    if download.running:
        download.cancel()
        return _download_view(download)
    current = _status(db, model_dir)
    if current.enabled and current.engine == "local_onnx":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="the classifier runs on this model; turn it off or choose a provider first")
    download.remove()
    return ClassifierDownload(state="idle", bytes_done=0, bytes_total=download.progress.bytes_total)
