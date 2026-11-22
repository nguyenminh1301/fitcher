"""The owner password as the sign-in page and the Security page use it (DECISIONS §9)."""

from pydantic import Field

from app.contracts.query_spec import ContractModel


class OwnerStatus(ContractModel):
    password_set: bool
    # Whether the request carries a live session.
    signed_in: bool
    # Whether the instance is reachable through a name other than this computer's.
    exposed: bool


class OwnerSignIn(ContractModel):
    password: str = Field(max_length=1024, repr=False)


class OwnerPasswordChange(ContractModel):
    # Required when a password is set already.
    current_password: str | None = Field(default=None, max_length=1024, repr=False)
    new_password: str = Field(max_length=1024, repr=False)


class OwnerPasswordRemoval(ContractModel):
    current_password: str = Field(max_length=1024, repr=False)
