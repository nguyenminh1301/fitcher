"""Realm users as the console's Users section shows and changes them (DECISIONS §15)."""

from app.contracts.query_spec import ContractModel


class UserView(ContractModel):
    id: str
    username: str
    display_name: str
    # The user's roles of the active pack; console roles are not shown or changed here.
    roles: list[str]
    enabled: bool


class UserRoles(ContractModel):
    roles: list[str]
