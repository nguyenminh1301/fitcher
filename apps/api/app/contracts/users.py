"""Accounts as the console's Users section shows and changes them (DECISIONS §9, §15)."""

from pydantic import Field

from app.contracts.query_spec import ContractModel


class UserView(ContractModel):
    id: str
    email: str
    display_name: str
    # Pack roles in policies.yaml order, then console roles.
    roles: list[str]
    enabled: bool


class NewUser(ContractModel):
    email: str = Field(max_length=320)
    display_name: str = Field(max_length=200)
    password: str = Field(max_length=1024)
    roles: list[str]


class UserChange(ContractModel):
    display_name: str | None = Field(default=None, max_length=200)
    roles: list[str] | None = None
    enabled: bool | None = None


class PasswordReset(ContractModel):
    password: str = Field(max_length=1024)
