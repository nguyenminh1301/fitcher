"""Which prompt-injection classifier the screener runs (DECISIONS §9, Layer 0).

``provider`` (the default) sends each text to a Prompt Guard model of a
configured provider (``app/screening/provider_engine.py``); ``local_onnx`` runs
the ONNX model in the guard model directory on this computer
(``app/screening/classifier.py``), downloaded from the Security page
(``app/screening/download.py``) or exported by ``jobs.fetch_guard_model``. The
choice and the provider's model are app-state settings. A missing provider or
model gives no classifier, so a screener that has the classifier turned on
fails closed.
"""

from collections.abc import Callable
import logging
from pathlib import Path

from app.llm.call_log import CallLog
from app.screening.classifier import Classifier, load_classifier
from app.screening.provider_engine import DEFAULT_MODEL, ProviderClassifier

logger = logging.getLogger(__name__)
ENGINES = ("provider", "local_onnx")


def configured_classifier(model_dir: Path, call_log: CallLog | None = None, *, state=None, vault=None) -> Classifier | None:
    """The classifier the app state chooses, or None when it cannot run."""
    from app.llm.providers import ProviderNotFound, ProviderStore  # noqa: PLC0415 - the screener loads without the state
    from app.state.db import shared_state  # noqa: PLC0415
    from app.state.secrets import SecretError, shared_vault  # noqa: PLC0415
    from app.state.settings import Settings  # noqa: PLC0415

    state = state or shared_state()
    settings = Settings(state)
    if settings.get("screening", "classifier_engine") == "local_onnx":
        return load_classifier(model_dir)
    provider_id = settings.get("screening", "classifier_provider_id")
    if not provider_id:
        logger.warning("the screening classifier has no provider; screening is unavailable")
        return None
    vault = vault or shared_vault()
    model = settings.get("screening", "classifier_model") or DEFAULT_MODEL
    try:
        route = ProviderStore(state, vault).route(provider_id, model, vault.reader())
    except (ProviderNotFound, SecretError) as error:
        logger.warning("the screening classifier's provider cannot be used: %s", type(error).__name__)
        return None
    return ProviderClassifier(route, call_log=call_log)


def loader(model_dir: Path, call_log: Callable[[], CallLog | None] = lambda: None) -> Callable[[], Classifier | None]:
    return lambda: configured_classifier(model_dir, call_log())
