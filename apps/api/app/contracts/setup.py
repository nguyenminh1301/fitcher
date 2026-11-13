"""First-run setup as the setup page shows and changes it (DECISIONS §15)."""

from typing import Literal

from pydantic import Field

from app.contracts.query_spec import ContractModel


class SetupStep(ContractModel):
    id: str
    state: Literal["pending", "done", "skipped"]


class SetupStatus(ContractModel):
    # Who uses the instance; null until the first step is answered.
    mode: Literal["individual", "team"] | None
    steps: list[SetupStep]
    complete: bool


class FirstAdminInput(ContractModel):
    email: str = Field(max_length=320)
    display_name: str = Field(max_length=200)
    password: str = Field(max_length=1024)


class SetupModeChange(ContractModel):
    mode: Literal["individual", "team"]
    # Required when moving to team mode while no admin account is enabled.
    admin: FirstAdminInput | None = None
