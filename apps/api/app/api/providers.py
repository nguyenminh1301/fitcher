"""Model providers and the tier mapping (DECISIONS §2, §9, §15): the setup's Models step and the Models page.

Until sign-in moves into the app (Phase 15) every endpoint needs the ``admin``
role. A key goes into the vault and never comes back: responses carry only
whether it is set and its last four characters, and admin actions record the
same. Adding the first provider maps every chat tier and the embedding to its
proposed models; any tier can then be mapped to any model of a configured
provider. The embedding runs locally until an admin chooses another model on
``PUT /models/embedding``, a separate action that must confirm the full
reindex it needs; ``needs_reindex`` then tells that the active pack was
indexed with another model and must be recompiled.

``POST /providers/{id}/test`` lists the provider's models, then asks one model
for a small structured reply through the gateway. For a hosted provider that
call is billed, which the response states. A model that fails structured
output is reported and stays selectable.

An admin action that cannot be recorded is logged; the change itself stands,
because a replaced key cannot be restored.
"""

from collections.abc import Callable
import json
import logging
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.api.console import require_admin
from app.api.runtime import get_admin_action_log, get_compiled_or_none, get_model_store, pack_identity
from app.api.setup import get_state_db
from app.auth.jwt import Principal
from app.contracts.providers import (
    EmbeddingChange, EmbeddingView, EvalStatus, ModelTiersView, ProviderCreate, ProviderModels, ProviderTestRequest, ProviderTestResult,
    ProviderUpdate, ProviderView, TierChange, TierView,
)
from app.llm import defaults
from app.llm.client import LLMError, Prompt
from app.llm.eligibility import eligibility, ReportSummary
from app.llm.gateway import Gateway, Route
from app.llm.provider_models import list_models, ModelListError
from app.llm.providers import key_name, Provider, ProviderError, ProviderNotFound, ProviderStore
from app.llm.clients import compiled_embedding
from app.llm.routes import EmbeddingChoice, fill_defaults, TierMapping
from app.llm.tiers import CHAT_TIERS, EMBED_TIER
from app.observability.events import AdminActionRecord, utc_now
from app.observability.tracing import trusted_pack_calls
from app.state import setup
from app.state.db import StateDb
from app.state.secrets import SecretError, SecretVault, shared_vault

logger = logging.getLogger(__name__)
router = APIRouter()
Admin = Annotated[Principal, Depends(require_admin)]
PROBE = Prompt(system='Reply with a JSON object {"ok": true} and nothing else.', user="Reply now.")


class ProbeReply(BaseModel):
    ok: bool


class ActionLog(Protocol):
    def record_action(self, record: AdminActionRecord) -> None: ...


def get_vault() -> SecretVault:
    return shared_vault()


def get_compiled_embedding() -> tuple[str, int] | None:
    """The embedding label and size the active pack was compiled with."""
    return compiled_embedding()


Compiled = Annotated[tuple[str, int] | None, Depends(get_compiled_embedding)]


def _active_reports() -> list[ReportSummary]:
    """The active pack's latest eval report per tier and model; none when the pack or the store is unavailable."""
    try:
        return get_model_store().reports(pack_identity(get_compiled_or_none()).name)
    except Exception:  # noqa: BLE001 - no compiled pack, no password or ClickHouse down: shown as not evaluated
        logger.warning("the eval reports of the Models page could not be read", exc_info=True)
        return []


def get_eval_reports() -> Callable[[], list[ReportSummary]]:
    return _active_reports


def get_model_lister() -> Callable[[Provider, str | None], list[str]]:
    return list_models


class _OneRoute:
    def __init__(self, route: Route):
        self._route = route

    def route(self, tier: str) -> Route:
        return self._route


def _probe(route: Route) -> None:
    """One structured reply from the route's model; raises ``LLMError`` when it fails."""
    with trusted_pack_calls():
        Gateway(_OneRoute(route), retries=0).structured("fast", PROBE, ProbeReply)


def get_probe() -> Callable[[Route], None]:
    return _probe


def get_store(db: Annotated[StateDb, Depends(get_state_db)], vault: Annotated[SecretVault, Depends(get_vault)]) -> ProviderStore:
    return ProviderStore(db, vault)


def get_mapping(db: Annotated[StateDb, Depends(get_state_db)], store: Annotated[ProviderStore, Depends(get_store)]) -> TierMapping:
    return TierMapping(db, store)


Store = Annotated[ProviderStore, Depends(get_store)]
Mapping = Annotated[TierMapping, Depends(get_mapping)]
Log = Annotated[ActionLog, Depends(get_admin_action_log)]


def _view(provider: Provider, in_use: set[str]) -> ProviderView:
    return ProviderView(
        id=provider.id, name=provider.name, kind=provider.kind, base_url=provider.base_url, key_set=provider.key_set,
        key_last4=provider.key_last4, hosted=provider.hosted, in_use=provider.id in in_use,
    )


def _described(provider: Provider | None) -> str:
    if provider is None:
        return ""
    return json.dumps({"name": provider.name, "kind": provider.kind, "base_url": provider.base_url,
                       "key_last4": provider.key_last4})


def _record(log: ActionLog, admin: Principal, action: str, target: str, old: str, new: str) -> None:
    try:
        log.record_action(AdminActionRecord(ts=utc_now(), actor=admin.user_id, action=action, target=target,
                                            old_value=old, new_value=new))
    except Exception:  # noqa: BLE001 - the change already happened and a replaced key cannot be restored
        logger.exception("the admin action %s on %s was not recorded", action, target)


def _found(store: ProviderStore, provider_id: str) -> Provider:
    try:
        return store.get(provider_id)
    except ProviderNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error)) from None


def _refused(error: ProviderError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))


@router.get("/providers")
def list_providers(_: Admin, store: Store, mapping: Mapping) -> list[ProviderView]:
    in_use = mapping.providers_in_use()
    return [_view(provider, in_use) for provider in store.list()]


@router.post("/providers", status_code=status.HTTP_201_CREATED)
def add_provider(body: ProviderCreate, admin: Admin, store: Store, mapping: Mapping, log: Log,
                 db: Annotated[StateDb, Depends(get_state_db)]) -> ProviderView:
    try:
        provider = store.create(body.kind, name=body.name, api_key=body.api_key, base_url=body.base_url)
    except ProviderError as error:
        raise _refused(error) from None
    fill_defaults(mapping, provider)
    setup.mark_done(db, "models")
    _record(log, admin, "provider_add", provider.id, "", _described(provider))
    return _view(provider, mapping.providers_in_use())


@router.patch("/providers/{provider_id}")
def change_provider(provider_id: str, body: ProviderUpdate, admin: Admin, store: Store, mapping: Mapping,
                    log: Log) -> ProviderView:
    before = _found(store, provider_id)
    try:
        provider = store.update(provider_id, name=body.name, api_key=body.api_key, base_url=body.base_url)
    except ProviderError as error:
        raise _refused(error) from None
    _record(log, admin, "provider_change", provider_id, _described(before), _described(provider))
    return _view(provider, mapping.providers_in_use())


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_provider(provider_id: str, admin: Admin, store: Store, mapping: Mapping, log: Log) -> Response:
    before = _found(store, provider_id)
    if provider_id in mapping.providers_in_use():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail=f"{before.name} is in use by a model tier or the embedding; map them elsewhere first")
    store.delete(provider_id)
    _record(log, admin, "provider_remove", provider_id, _described(before), "")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _unreadable(provider: Provider) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT,
                         detail=f"the key of {provider.name} cannot be read with this instance's key; enter it again")


def _key(vault: SecretVault, provider: Provider) -> str | None:
    try:
        return vault.reader().get(key_name(provider.id)) if provider.key_set else None
    except SecretError:
        raise _unreadable(provider) from None


@router.get("/providers/{provider_id}/models")
def provider_models(
    provider_id: str, _: Admin, store: Store, vault: Annotated[SecretVault, Depends(get_vault)],
    lister: Annotated[Callable, Depends(get_model_lister)],
) -> ProviderModels:
    provider = _found(store, provider_id)
    try:
        models = lister(provider, _key(vault, provider))
    except ModelListError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(error)) from None
    return ProviderModels(provider_id=provider_id, models=models)


def _test_model(provider: Provider, mapping: TierMapping, listed: list[str]) -> str | None:
    fast = mapping.tier("fast")
    if fast is not None and fast.provider_id == provider.id:
        return fast.model
    return defaults.chat_models(provider.kind).get("fast") or (listed[0] if listed else None)


@router.post("/providers/{provider_id}/test")
def test_provider(
    provider_id: str, body: ProviderTestRequest, _: Admin, store: Store, mapping: Mapping,
    vault: Annotated[SecretVault, Depends(get_vault)], lister: Annotated[Callable, Depends(get_model_lister)],
    probe: Annotated[Callable, Depends(get_probe)],
) -> ProviderTestResult:
    provider = _found(store, provider_id)
    result = {"provider_id": provider_id, "models": [], "model": body.model, "structured_output": False,
              "paid": provider.hosted, "error": None}
    try:
        result["models"] = lister(provider, _key(vault, provider))
    except ModelListError as error:
        return ProviderTestResult(**result | {"error": str(error)})
    model = body.model or _test_model(provider, mapping, result["models"])
    if model is None:
        return ProviderTestResult(**result | {"error": f"{provider.name} lists no model to test"})
    try:
        route = store.route(provider_id, model, vault.reader())
    except SecretError:
        raise _unreadable(provider) from None
    try:
        probe(route)
    except LLMError as error:
        return ProviderTestResult(**result | {"model": model, "error": str(error)})
    return ProviderTestResult(**result | {"model": model, "structured_output": True})


def _embedding(choice: EmbeddingChoice, compiled: tuple[str, int] | None) -> EmbeddingView:
    stale = compiled is not None and compiled != (choice.label, choice.dimensions)
    return EmbeddingView(backend=choice.backend, provider_id=choice.provider_id, model=choice.model,
                         dimensions=choice.dimensions, needs_reindex=stale)


def _eval(reports: list[ReportSummary], tier: str, provider_id: str, model: str) -> EvalStatus:
    found = eligibility(reports, tier, f"{provider_id}/{model}")
    return EvalStatus(evaluated=found.report_id is not None, passed=found.eligible, reason=found.reason,
                      report_id=found.report_id, report_ts=found.report_ts)


def _tiers(mapping: TierMapping, compiled: tuple[str, int] | None, reports: list[ReportSummary]) -> ModelTiersView:
    mapped = mapping.tiers()
    return ModelTiersView(
        tiers=[TierView(tier=tier, provider_id=mapped[tier].provider_id, model=mapped[tier].model,
                        eval=_eval(reports, tier, mapped[tier].provider_id, mapped[tier].model))
               if tier in mapped else TierView(tier=tier, provider_id=None, model=None) for tier in CHAT_TIERS],
        embedding=_embedding(mapping.embedding(), compiled),
    )


@router.get("/models/tiers")
def model_tiers(_: Admin, mapping: Mapping, compiled: Compiled,
                reports: Annotated[Callable, Depends(get_eval_reports)]) -> ModelTiersView:
    return _tiers(mapping, compiled, reports())


@router.put("/models/embedding")
def change_embedding(body: EmbeddingChange, admin: Admin, mapping: Mapping, compiled: Compiled, log: Log) -> EmbeddingView:
    if not body.confirm_reindex:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="changing the embedding model needs a full reindex of the pack; confirm it")
    before = mapping.embedding()
    try:
        if body.backend == "local":
            choice = mapping.set_local_embedding(body.model)
        else:
            if not body.provider_id:
                raise ValueError("a provider embedding needs a provider")
            choice = mapping.set_embedding(body.provider_id, body.model, body.dimensions or 0)
    except (ProviderNotFound, ValueError) as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    _record(log, admin, "embedding", EMBED_TIER, before.label, choice.label)
    return _embedding(choice, compiled)


@router.put("/models/tiers/{tier}")
def map_tier(tier: str, body: TierChange, admin: Admin, mapping: Mapping, log: Log) -> TierView:
    if tier == EMBED_TIER:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail="the embedding model changes with a full reindex, not as a tier")
    if tier not in CHAT_TIERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"unknown model tier {tier!r}")
    before = mapping.tier(tier)
    try:
        mapped = mapping.set_tier(tier, body.provider_id, body.model)
    except ProviderNotFound as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    _record(log, admin, "model_tier", tier, f"{before.provider_id}/{before.model}" if before else "",
            f"{mapped.provider_id}/{mapped.model}")
    return TierView(tier=tier, provider_id=mapped.provider_id, model=mapped.model)
