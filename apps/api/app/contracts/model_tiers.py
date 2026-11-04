"""The Models page payloads: model tiers, their aliases and eligibility (DECISIONS §2, §15)."""

from datetime import datetime

from pydantic import Field

from app.contracts.query_spec import ContractModel


class AliasOption(ContractModel):
    """A catalog alias the gateway loaded, and whether it may serve the tier."""

    alias: str
    provider: str
    eligible: bool
    # Why the alias is or is not eligible, shown next to a disabled choice.
    reason: str
    # The latest eval report that ran the tier with this alias.
    report_id: str | None = None
    report_ts: datetime | None = None


class ModelTier(ContractModel):
    tier: str
    alias: str
    provider: str
    default_alias: str
    # False for embed, which changes only with a new default and a full reindex.
    editable: bool
    # Whether the current alias is eligible, and the report that made it so.
    eligible: bool
    reason: str
    report_id: str | None = None
    report_ts: datetime | None = None
    options: list[AliasOption] = []


class ModelTiers(ContractModel):
    pack: str
    tiers: list[ModelTier]
    # Set when the gateway did not list its aliases; options are then empty.
    catalog_error: str | None = None


class ModelTierChange(ContractModel):
    alias: str = Field(min_length=1, max_length=100)
