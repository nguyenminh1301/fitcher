"""GET /admin/models and PUT /admin/models/{tier}: the console's Models page (DECISIONS §2, §15).

Only an ``admin`` reaches either. ``GET`` lists every tier with its current
alias, provider and eligibility, and for each chat tier the aliases the
gateway loaded with their eligibility from the active pack's eval reports.
``PUT`` maps a chat tier to an eligible alias: it refuses ``embed`` (a new
embedding model needs a full reindex), an alias the gateway did not load and
an ineligible alias, writes the mapping, records the change in
``agent_logs.admin_actions`` (when that fails, the previous alias is written
back while the tier still holds this change, so no change stays unaudited)
and makes this process's tier lookup read the new
mapping at once; other processes read it within the tier cache window.
Changes run one at a time in the process; the api runs one worker.
"""

import logging
import threading
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.console import require_admin
from app.api.runtime import get_catalog, get_compiled, get_model_store, get_tier_map, unavailable
from app.auth.jwt import Principal
from app.contracts.model_tiers import AliasOption, ModelTier, ModelTierChange, ModelTiers
from app.llm.eligibility import eligibility, ReportSummary
from app.llm.model_store import CatalogError
from app.llm.tiers import CHAT_TIERS, EMBED_TIER, provider_of, TierMap, TIERS, TierStoreError
from app.observability.events import AdminActionRecord, utc_now
from app.packs.compiler import CompiledPack

logger = logging.getLogger(__name__)
router = APIRouter()
ACTION = "model_tier"
_CHANGES = threading.Lock()


class ModelStore(Protocol):
    def read(self) -> dict[str, str]: ...

    def write(self, tier: str, alias: str, changed_by: str, changed_at) -> None: ...

    def reports(self, pack: str) -> list[ReportSummary]: ...

    def record_action(self, record: AdminActionRecord) -> None: ...


class Catalog(Protocol):
    def aliases(self) -> list[str]: ...


def _chat_aliases(catalog: Catalog) -> tuple[list[str], str | None]:
    try:
        return [alias for alias in catalog.aliases() if not alias.endswith("-embed")], None
    except CatalogError as error:
        return [], str(error)


def _reports(store: ModelStore, pack: str) -> list[ReportSummary]:
    try:
        return store.reports(pack)
    except Exception:  # noqa: BLE001 - ClickHouse is unreachable or refused the reports table
        logger.exception("the eval reports could not be read")
        raise unavailable("the model store is unavailable") from None


def _tier(tier: str, current: dict[str, str], tiers: TierMap, reports, aliases: list[str]) -> ModelTier:
    alias = current[tier]
    editable = tier != EMBED_TIER
    state = eligibility(reports, tier, alias)
    reason = state.reason if editable else "changed only in .env, followed by a full reindex"
    options = [
        AliasOption(alias=option, provider=provider_of(option), **vars(eligibility(reports, tier, option)))
        for option in aliases
    ] if editable else []
    return ModelTier(
        tier=tier, alias=alias, provider=provider_of(alias), default_alias=tiers.defaults[tier], editable=editable,
        eligible=state.eligible, reason=reason, report_id=state.report_id, report_ts=state.report_ts, options=options,
    )


def _listing(compiled: CompiledPack, tiers: TierMap, store: ModelStore, catalog: Catalog) -> ModelTiers:
    pack = compiled.pack.name
    reports = _reports(store, pack)
    aliases, catalog_error = _chat_aliases(catalog)
    current = tiers.current()
    return ModelTiers(
        pack=pack, tiers=[_tier(tier, current, tiers, reports, aliases) for tier in TIERS], catalog_error=catalog_error,
    )


@router.get("/admin/models")
def list_models(
    _: Annotated[Principal, Depends(require_admin)],
    compiled: Annotated[CompiledPack, Depends(get_compiled)],
    tiers: Annotated[TierMap, Depends(get_tier_map)],
    store: Annotated[ModelStore, Depends(get_model_store)],
    catalog: Annotated[Catalog, Depends(get_catalog)],
) -> ModelTiers:
    return _listing(compiled, tiers, store, catalog)


@router.put("/admin/models/{tier}")
def change_model(
    tier: str,
    body: ModelTierChange,
    admin: Annotated[Principal, Depends(require_admin)],
    compiled: Annotated[CompiledPack, Depends(get_compiled)],
    tiers: Annotated[TierMap, Depends(get_tier_map)],
    store: Annotated[ModelStore, Depends(get_model_store)],
    catalog: Annotated[Catalog, Depends(get_catalog)],
) -> ModelTier:
    if tier == EMBED_TIER:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="embed changes only in .env, followed by a full reindex",
        )
    if tier not in CHAT_TIERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"unknown model tier {tier!r}")
    aliases, catalog_error = _chat_aliases(catalog)
    if catalog_error is not None:
        raise unavailable(catalog_error)
    if body.alias not in aliases:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"the gateway has no alias {body.alias!r}")
    reports = _reports(store, compiled.pack.name)
    state = eligibility(reports, tier, body.alias)
    if not state.eligible:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"{body.alias} is not eligible for {tier}: {state.reason}")
    with _CHANGES:
        tiers.invalidate()
        previous = tiers.current()[tier]
        now = utc_now()
        try:
            store.write(tier, body.alias, admin.user_id, now)
        except Exception:  # noqa: BLE001 - ClickHouse is unreachable or refused the write
            logger.exception("the model tier change was not written")
            raise unavailable("the model store is unavailable") from None
        try:
            store.record_action(AdminActionRecord(
                ts=now, actor=admin.user_id, action=ACTION, target=tier, old_value=previous, new_value=body.alias,
            ))
        except Exception:  # noqa: BLE001 - an unaudited change is undone
            logger.exception("the model tier change was not audited; writing back %s", previous)
            _write_back(store, tier, body.alias, previous, admin.user_id)
            tiers.invalidate()
            raise unavailable("the model store is unavailable") from None
        tiers.invalidate()
        return _tier(tier, tiers.current(), tiers, reports, aliases)


def _write_back(store: ModelStore, tier: str, written: str, previous: str, actor: str) -> None:
    """Restore ``previous`` unless another process changed the tier after ``written``."""
    try:
        if store.read().get(tier, written) != written:
            logger.warning("tier %s changed again elsewhere; %s is not written back", tier, previous)
            return
    except TierStoreError:
        logger.warning("tier %s could not be read before the write-back; restoring %s", tier, previous)
    try:
        store.write(tier, previous, actor, utc_now())
    except Exception:  # noqa: BLE001 - reported; the operator restores the mapping from the logs
        logger.exception("the previous model tier mapping could not be written back")
