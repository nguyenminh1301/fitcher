"""Requests and replies of ``/pack/instant`` (DECISIONS §11 step 0): build a pack from a source's chosen tables."""

from typing import Literal

from app.contracts.query_spec import ContractModel
from app.contracts.sources import FailureReason


class InstantEstimateRequest(ContractModel):
    source_id: str
    # An empty list is refused by the pipeline with its reason.
    tables: list[str]


class InstantRequest(InstantEstimateRequest):
    # Drafting is a billable model call; the request must say the admin accepted it.
    confirm_billable: bool


class InstantEstimate(ContractModel):
    # Prompt tokens of the draft, estimated from the source's catalog.
    prompt_tokens: int
    # Mart views the tables become, wide views included.
    datasets: int
    # Why no model can draft yet, or None.
    model_missing: str | None = None


class InstantStep(ContractModel):
    id: Literal["marts", "profile", "files", "draft", "approve", "compile", "activate"]
    state: Literal["pending", "running", "done", "failed"]
    # Of a long step, while it runs: the compile's phase (screening column values, then indexing them) and how many
    # items of that phase are done out of how many.
    phase: Literal["screen", "index"] | None = None
    done: int | None = None
    total: int | None = None


class InstantResult(ContractModel):
    pack: str
    datasets: int = 0
    relationships: int = 0
    # Views without a time column, which got no dataset.
    skipped: list[str] = []
    # Drafted items dropped because their test-run failed, or because they cite one that did.
    dropped: list[str] = []
    # Wide views that read a live table: ClickHouse joins the live rows itself, so copying the tables is faster.
    slow: list[str] = []
    # Columns ("mart.column") whose values ClickHouse could not read, such as a number too large for its type; the
    # pack was drafted without them.
    unreadable_columns: list[str] = []
    suggested_questions: list[str] = []


class InstantJobView(ContractModel):
    id: str
    source_id: str
    tables: list[str]
    status: Literal["running", "succeeded", "failed"]
    steps: list[InstantStep]
    failed_step: str | None = None
    error: str | None = None
    # Set when ClickHouse refused the failed step: the reason the interface words instead of ClickHouse's text.
    error_reason: FailureReason | None = None
    # Whether the source had a pack before this build; a failed build leaves that pack answering.
    had_pack: bool = False
    result: InstantResult | None = None
    started_at: str
    finished_at: str | None = None


class InstantJobReply(ContractModel):
    job: InstantJobView
