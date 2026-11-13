"""Signing in with a local account (DECISIONS §9)."""

from pydantic import Field

from app.contracts.query_spec import ContractModel


class SignIn(ContractModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)
