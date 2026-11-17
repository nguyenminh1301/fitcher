"""First-run setup as the setup page shows and changes it (DECISIONS §15)."""

from typing import Literal

from app.contracts.query_spec import ContractModel


class SetupStep(ContractModel):
    id: str
    state: Literal["pending", "done", "skipped"]


class SetupStatus(ContractModel):
    steps: list[SetupStep]
    complete: bool
