"""Model providers and the tier mapping as the setup's Models step and the Models page use them (DECISIONS §15).

No contract carries a key: a provider shows only whether its key is set and its last four characters.
"""

from datetime import datetime
from typing import Literal

from app.contracts.query_spec import ContractModel

ProviderKind = Literal["openai", "anthropic", "gemini", "ollama", "openai_compatible"]


class ProviderKeyView(ContractModel):
    id: str
    label: str
    last4: str | None
    created_at: str


class ProviderView(ContractModel):
    id: str
    name: str
    kind: ProviderKind
    base_url: str | None
    # Whether the provider has a key, and the last four characters of its first key.
    key_set: bool
    key_last4: str | None
    # A hosted provider bills its calls; the interface labels its test call as paid.
    hosted: bool
    # A tier or the embedding uses it.
    in_use: bool
    # The keys the gateway rotates, oldest first; only their label and last four characters.
    keys: list[ProviderKeyView] = []


class ProviderKeyCreate(ContractModel):
    api_key: str
    label: str = ""


class ProviderCreate(ContractModel):
    kind: ProviderKind
    name: str | None = None
    api_key: str | None = None
    base_url: str | None = None


class ProviderUpdate(ContractModel):
    name: str | None = None
    api_key: str | None = None
    base_url: str | None = None


class ProviderModels(ContractModel):
    provider_id: str
    models: list[str]


class CatalogEntry(ContractModel):
    """One model of a provider with what it is for, its price, limits and measured speed (``app/llm/catalog.py``)."""

    id: str
    provider_id: str
    kind: Literal["chat", "embedding", "other"]
    # free: calls cost nothing; free_tier: a rate-limited allowance the provider does not bill.
    free: Literal["none", "free", "free_tier"]
    # USD per million tokens; null when no source knows the price.
    input_price: float | None
    output_price: float | None
    context: int | None
    # Whether the model can answer in a JSON schema; null when no source says.
    structured_output: bool | None
    # Artificial Analysis' intelligence index as OpenRouter lists it.
    benchmark: float | None
    # The median latency of this instance's successful calls to the model over the last 7 days.
    median_latency_ms: int | None


class ModelCatalog(ContractModel):
    provider_id: str
    models: list[CatalogEntry]


class ProviderTestRequest(ContractModel):
    # The model to call; by default the provider's model of the fast tier or its proposed one.
    model: str | None = None


class ProviderTestResult(ContractModel):
    provider_id: str
    models: list[str]
    model: str | None
    structured_output: bool
    paid: bool
    error: str | None


class EvalStatus(ContractModel):
    """The latest eval report of the active pack that ran the tier on this model; it informs and never gates."""

    evaluated: bool
    passed: bool
    reason: str
    report_id: str | None = None
    report_ts: datetime | None = None


class ChainLink(ContractModel):
    provider_id: str
    model: str


class TierView(ContractModel):
    tier: str
    # The chain's first model, which answers unless it fails.
    provider_id: str | None
    model: str | None
    eval: EvalStatus | None = None
    # Every model the tier tries, in order.
    chain: list[ChainLink] = []


class EmbeddingView(ContractModel):
    # A local model runs inside the api; a provider's model is called through the gateway.
    backend: Literal["local", "provider"]
    provider_id: str | None
    model: str
    dimensions: int
    # The active pack was indexed with another model or size and must be recompiled.
    needs_reindex: bool


class EmbeddingChange(ContractModel):
    backend: Literal["local", "provider"]
    model: str
    provider_id: str | None = None
    dimensions: int | None = None
    # Changing the embedding needs a full reindex of the pack, so the change is refused unless confirmed.
    confirm_reindex: bool = False


ModelMode = Literal["auto_free", "auto_best", "manual"]


class ModelTiersView(ContractModel):
    tiers: list[TierView]
    embedding: EmbeddingView
    # manual: the owner's chains; auto_free or auto_best: chosen from the model catalog.
    mode: ModelMode = "manual"
    # When an automatic mode last chose the chains.
    refreshed_at: datetime | None = None


class TierChange(ContractModel):
    """One model as the tier's whole chain (``provider_id`` and ``model``), or a whole ``chain``."""

    provider_id: str | None = None
    model: str | None = None
    chain: list[ChainLink] | None = None


class ModeChange(ContractModel):
    mode: ModelMode
