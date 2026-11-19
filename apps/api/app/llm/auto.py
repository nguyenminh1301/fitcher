"""Choosing each chat tier's chain from the model catalog (DECISIONS §2).

``auto_free`` uses only models that cost nothing or have a free tier, best
benchmark first and then the fastest measured latency. ``auto_best`` uses any
chat model, best benchmark first and the cheaper one on a tie. A model without
a benchmark comes after every model with one.

Every chain starts with the best model and then takes the best model of each
other provider, so one provider's outage or daily limit leaves an answer; it
then fills up from the remaining models, ``CHAIN_LENGTH`` models in all. The
``fast`` tier needs a model known to answer in a JSON schema; the other tiers
leave out only the models known not to.

``refresh`` applies the choice: when the mode changes, when a provider or key
is added, changed or removed, and once a day (``REFRESH_AFTER``) when the
tiers are read. A tier with no eligible model keeps its chain.
"""

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta, UTC
import logging

from app.llm.catalog import CatalogModel, ModelListError, with_latency
from app.llm.providers import Provider
from app.llm.routes import TierMapping, TierModel
from app.llm.tiers import CHAT_TIERS

CHAIN_LENGTH = 4
REFRESH_AFTER = timedelta(days=1)
STRUCTURED_TIERS = frozenset({"fast"})
AUTO_MODES = frozenset({"auto_free", "auto_best"})

_log = logging.getLogger(__name__)


def _rank(mode: str):
    def key(model: CatalogModel):
        benchmark = -(model.benchmark if model.benchmark is not None else -1.0)
        if mode == "auto_free":
            return (benchmark, model.median_latency_ms if model.median_latency_ms is not None else float("inf"))
        price = (model.input_price or 0.0) + (model.output_price or 0.0) if model.input_price is not None else float("inf")
        return (benchmark, price)
    return key


def eligible(models: Iterable[CatalogModel], mode: str, tier: str) -> list[CatalogModel]:
    """The tier's candidates in the mode's order."""
    chosen = [
        model for model in models
        if model.kind == "chat"
        and (mode != "auto_free" or model.free != "none")
        and (model.structured_output is True if tier in STRUCTURED_TIERS else model.structured_output is not False)
    ]
    return sorted(chosen, key=_rank(mode))


def chain_of(ranked: list[CatalogModel]) -> list[TierModel]:
    """The best model, then the best of each other provider, then the rest, ``CHAIN_LENGTH`` in all."""
    chain: list[CatalogModel] = ranked[:1]
    for model in ranked[1:]:
        if len(chain) < CHAIN_LENGTH and model.provider_id not in {link.provider_id for link in chain}:
            chain.append(model)
    for model in ranked:
        if len(chain) < CHAIN_LENGTH and model not in chain:
            chain.append(model)
    return [TierModel(model.provider_id, model.id) for model in chain]


def choose(models: Iterable[CatalogModel], mode: str) -> dict[str, list[TierModel]]:
    """Each chat tier's chain in ``mode``; a tier with no eligible model is left out."""
    models = list(models)
    return {tier: chain for tier in CHAT_TIERS if (chain := chain_of(eligible(models, mode, tier)))}


def refresh(
    mapping: TierMapping, providers: Iterable[Provider], catalog: Callable[[Provider], list[CatalogModel]],
    latency: Mapping[tuple[str, str], int], *, force: bool = False, now: datetime | None = None,
) -> bool:
    """Choose the chains again in an automatic mode; returns whether it did.

    Without ``force`` it runs only once ``REFRESH_AFTER`` has passed since the last choice.
    """
    mode, refreshed_at = mapping.mode()
    now = now or datetime.now(UTC)
    if mode not in AUTO_MODES or (not force and refreshed_at is not None and now - refreshed_at < REFRESH_AFTER):
        return False
    models: list[CatalogModel] = []
    for provider in providers:
        try:
            listed = catalog(provider)
        except ModelListError as error:  # a provider that does not answer adds no model this time
            _log.warning("the models of %s are left out of the automatic choice: %s", provider.id, error)
            continue
        measured = {model: ms for (provider_id, model), ms in latency.items() if provider_id == provider.id}
        models.extend(with_latency(listed, measured))
    for tier, chain in choose(models, mode).items():
        mapping.set_chain(tier, chain)
    mapping.set_mode(mode, now)
    return True
