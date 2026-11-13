"""The OpenID Connect provider as an admin reads and changes it (DECISIONS §9)."""

from pydantic import Field

from app.contracts.query_spec import ContractModel


class OidcSettingsView(ContractModel):
    configured: bool
    issuer: str | None
    client_id: str | None
    roles_claim: str
    # The client secret is never returned: only whether it is set and its last four characters.
    secret_set: bool
    secret_last_four: str | None
    # The address to register at the provider as this instance's redirect URI.
    redirect_uri: str


class OidcSettingsChange(ContractModel):
    issuer: str = Field(min_length=1, max_length=500)
    client_id: str = Field(min_length=1, max_length=200)
    # Omitted or null keeps the stored secret; required the first time.
    client_secret: str | None = Field(default=None, max_length=1000)
    roles_claim: str = Field(default="roles", min_length=1, max_length=100)


class OidcAvailability(ContractModel):
    enabled: bool
