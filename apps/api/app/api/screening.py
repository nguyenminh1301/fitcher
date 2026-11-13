"""GET, POST and DELETE /screening/classifier: the optional prompt-injection classifier (DECISIONS §9).

The EN/VI rules always screen; the classifier is turned on and off here and is
off on a new instance. Turning it on needs its exported model in the guard
model directory: the model is gated and is exported to ONNX with PyTorch, so
it is fetched by the ``guard-model`` job (``jobs.fetch_guard_model``) in its
own image rather than by the api. Once it is on, screening fails closed
whenever the model cannot run. Each change is written to
``agent_logs.admin_actions``. Until sign-in moves into the app (Phase 15) the
endpoints need the ``admin`` role.
"""

import json
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.console import require_admin
from app.api.runtime import get_admin_action_log, get_screener
from app.api.setup import get_state_db
from app.auth.jwt import Principal
from app.config import load_settings
from app.contracts.screening import ClassifierStatus
from app.observability.events import AdminActionRecord, utc_now
from app.screening.classifier import MODEL_FILE, TOKENIZER_FILE, VERSION_FILE
from app.screening.screen import Screener
from app.state.db import StateDb
from app.state.settings import Settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/screening")
Admin = Annotated[Principal, Depends(require_admin)]
FETCH_COMMAND = "docker compose run --rm guard-model"


def get_model_dir() -> Path:
    return Path(load_settings().guard_model_dir)


def get_classifier_screener() -> Screener:
    return get_screener()


State = Annotated[StateDb, Depends(get_state_db)]
ModelDir = Annotated[Path, Depends(get_model_dir)]


def _status(db: StateDb, model_dir: Path) -> ClassifierStatus:
    present = (model_dir / MODEL_FILE).is_file() and (model_dir / TOKENIZER_FILE).is_file()
    version = None
    if present:
        try:
            version = str(json.loads((model_dir / VERSION_FILE).read_text(encoding="utf-8")).get("version") or "") or None
        except (OSError, ValueError, AttributeError):
            version = None
    return ClassifierStatus(enabled=Settings(db).get("screening", "classifier_enabled"), model_present=present,
                            version=version)


def _set(db: StateDb, admin: Principal, log, enabled: bool) -> None:
    before = Settings(db).get("screening", "classifier_enabled")
    Settings(db).set("screening", "classifier_enabled", enabled)
    try:
        log.record_action(AdminActionRecord(ts=utc_now(), actor=admin.user_id, action="screening_classifier",
                                            target="classifier", old_value="on" if before else "off",
                                            new_value="on" if enabled else "off"))
    except Exception:  # noqa: BLE001 - the change stands; the failure is logged
        logger.exception("the screening classifier change was not recorded")


@router.get("/classifier")
def classifier_status(_: Admin, db: State, model_dir: ModelDir) -> ClassifierStatus:
    return _status(db, model_dir)


@router.post("/classifier")
def turn_classifier_on(
    admin: Admin, db: State, model_dir: ModelDir, log: Annotated[object, Depends(get_admin_action_log)],
    screener: Annotated[Screener, Depends(get_classifier_screener)],
) -> ClassifierStatus:
    if not _status(db, model_dir).model_present:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail=f"the classifier's model is not in {model_dir}; fetch it with `{FETCH_COMMAND}`")
    _set(db, admin, log, True)
    screener.load_now()
    return _status(db, model_dir)


@router.delete("/classifier")
def turn_classifier_off(
    admin: Admin, db: State, model_dir: ModelDir, log: Annotated[object, Depends(get_admin_action_log)],
) -> ClassifierStatus:
    _set(db, admin, log, False)
    return _status(db, model_dir)
