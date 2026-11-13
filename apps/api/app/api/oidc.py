"""Sign-in through an OpenID Connect provider, and its settings for an admin (DECISIONS §9).

OIDC is available in team mode once an admin has registered a provider with
``PUT /settings/oidc``; local accounts keep working. ``GET /session/oidc/start``
sends the browser to the provider and ``GET /session/oidc/callback`` signs the
account in with the session cookie and sends the browser home, or back to the
sign-in page when anything fails. Success answers a small page of this site
that moves on to the app, so the browser sends the new ``SameSite=Strict``
cookie with the next request. The redirect URI is the web app's
``/auth/oidc/callback`` on the host the browser used. The client secret is
stored encrypted and never returned; every change is recorded in
``agent_logs.admin_actions`` without it.
"""

import json
import threading
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.console import require_admin
from app.api.runtime import get_admin_action_log, get_compiled_or_none, get_oidc_http, get_state_db, get_vault, pack_identity
from app.api.session import sign_in_response
from app.api.users import ActionLog
from app.auth import oidc, origin
from app.auth.principal import Principal
from app.auth.roles import CONSOLE_ROLES
from app.contracts.oidc import OidcAvailability, OidcSettingsChange, OidcSettingsView
from app.observability.events import AdminActionRecord, utc_now
from app.packs.compiler import CompiledPack
from app.state.db import StateDb
from app.state.secrets import SecretVault
from app.state.settings import Settings

router = APIRouter()
SECRET = "oidc:client_secret"
CALLBACK_PATH = "/auth/oidc/callback"
FAILED = "/sign-in?error=oidc"
SIGNED_IN_PAGE = (
    '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=/">'
    '<title>Signed in</title></head><body><a href="/">Continue</a></body></html>'
)
Admin = Annotated[Principal, Depends(require_admin)]
State = Annotated[StateDb, Depends(get_state_db)]
Vault = Annotated[SecretVault, Depends(get_vault)]
Http = Annotated[httpx.Client, Depends(get_oidc_http)]
Log = Annotated[ActionLog, Depends(get_admin_action_log)]

_providers: dict[tuple, oidc.Provider] = {}
_providers_lock = threading.Lock()


def _config(db: StateDb, vault: SecretVault) -> oidc.OidcConfig | None:
    settings = Settings(db)
    issuer, client_id = settings.get("oidc", "issuer"), settings.get("oidc", "client_id")
    if not issuer or not client_id or not vault.has(SECRET):
        return None
    return oidc.OidcConfig(issuer, client_id, vault.reader().get(SECRET), settings.get("oidc", "roles_claim"))


def _provider(config: oidc.OidcConfig, http: httpx.Client) -> oidc.Provider:
    """One provider per configuration and client, so its discovery document and keys are read once."""
    key = (config, id(http))
    with _providers_lock:
        if key not in _providers:
            _providers.clear()
            _providers[key] = oidc.Provider(config, http)
        return _providers[key]


def _active(db: StateDb, vault: SecretVault, http: httpx.Client) -> oidc.Provider | None:
    if origin.instance_mode(db) != "team":
        return None
    config = _config(db, vault)
    return None if config is None else _provider(config, http)


def _redirect_uri(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    https = request.url.scheme == "https" or origin.https_forwarded(request.headers)
    return f"{'https' if https else 'http'}://{host}{CALLBACK_PATH}"


def _instance_roles(compiled: CompiledPack | None) -> list[str]:
    try:
        return [*pack_identity(compiled).roles, *CONSOLE_ROLES]
    except HTTPException:
        return list(CONSOLE_ROLES)


@router.get("/session/oidc")
def availability(db: State, vault: Vault, http: Http) -> OidcAvailability:
    return OidcAvailability(enabled=_active(db, vault, http) is not None)


@router.get("/session/oidc/start")
def start(request: Request, db: State, vault: Vault, http: Http) -> RedirectResponse:
    provider = _active(db, vault, http)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="sign-in through a provider is not set up")
    try:
        url = oidc.start(db, provider, _redirect_uri(request))
    except oidc.OidcError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(error)) from None
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get("/session/oidc/callback")
def callback(
    request: Request, db: State, vault: Vault, http: Http,
    compiled: Annotated[CompiledPack | None, Depends(get_compiled_or_none)],
    state: str = "", code: str = "",
) -> Response:
    provider = _active(db, vault, http)
    if provider is None or not state or not code:
        return RedirectResponse(FAILED, status_code=status.HTTP_303_SEE_OTHER)
    try:
        account = oidc.finish(db, provider, state, code, _instance_roles(compiled))
    except oidc.OidcError:
        return RedirectResponse(FAILED, status_code=status.HTTP_303_SEE_OTHER)
    # A page of this site moves on, because the browser does not send a SameSite=Strict cookie with a redirect
    # that is still part of the provider's cross-site navigation.
    response = HTMLResponse(SIGNED_IN_PAGE, headers={"Cache-Control": "no-store"})
    sign_in_response(request, response, db, account.id)
    return response


def _view(db: StateDb, vault: SecretVault, request: Request) -> OidcSettingsView:
    settings = Settings(db)
    issuer = settings.get("oidc", "issuer")
    return OidcSettingsView(
        configured=_config(db, vault) is not None, issuer=issuer, client_id=settings.get("oidc", "client_id"),
        roles_claim=settings.get("oidc", "roles_claim"), secret_set=vault.has(SECRET),
        secret_last_four=vault.last_four(SECRET), redirect_uri=_redirect_uri(request),
    )


def _public(db: StateDb) -> dict[str, Any] | None:
    settings = Settings(db)
    if not settings.get("oidc", "issuer"):
        return None
    return {key: settings.get("oidc", key) for key in ("issuer", "client_id", "roles_claim")}


def _record(log: ActionLog, admin: Principal, action: str, target: str, old: Any, new: Any) -> None:
    log.record_action(AdminActionRecord(ts=utc_now(), actor=admin.user_id, action=action, target=target,
                                        old_value=json.dumps(old), new_value=json.dumps(new)))


@router.get("/settings/oidc")
def read_settings(_: Admin, db: State, vault: Vault, request: Request) -> OidcSettingsView:
    return _view(db, vault, request)


@router.put("/settings/oidc")
def change_settings(
    change: OidcSettingsChange, admin: Admin, db: State, vault: Vault, http: Http, log: Log, request: Request,
) -> OidcSettingsView:
    secret = change.client_secret or (vault.reader().get(SECRET) if vault.has(SECRET) else None)
    if not secret:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="enter the client secret")
    issuer = change.issuer.strip().rstrip("/")
    candidate = oidc.Provider(oidc.OidcConfig(issuer, change.client_id.strip(), secret, change.roles_claim.strip()), http)
    try:
        candidate.discovery()
    except oidc.OidcError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    old = _public(db)
    settings = Settings(db)
    settings.set("oidc", "issuer", issuer)
    settings.set("oidc", "client_id", change.client_id.strip())
    settings.set("oidc", "roles_claim", change.roles_claim.strip())
    if change.client_secret:
        vault.set(SECRET, change.client_secret)
    _record(log, admin, "oidc_settings", issuer, old, _public(db))
    return _view(db, vault, request)


@router.delete("/settings/oidc", status_code=status.HTTP_204_NO_CONTENT)
def remove_settings(admin: Admin, db: State, vault: Vault, log: Log) -> Response:
    old = _public(db)
    settings = Settings(db)
    for key in ("issuer", "client_id", "roles_claim"):
        settings.unset("oidc", key)
    vault.delete(SECRET)
    if old is not None:
        _record(log, admin, "oidc_settings_removed", old["issuer"], old, None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
