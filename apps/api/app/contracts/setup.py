"""First-run setup as the setup page shows and changes it (DECISIONS §15)."""

from typing import Literal

from app.contracts.query_spec import ContractModel


class SetupStep(ContractModel):
    id: str
    state: Literal["pending", "done", "skipped"]


class SetupStatus(ContractModel):
    # Who uses the instance; null until the first step is answered.
    mode: Literal["individual", "team"] | None
    steps: list[SetupStep]
    complete: bool


class SetupModeChange(ContractModel):
    mode: Literal["individual", "team"]
