"""Host and Origin checks of individual mode (DECISIONS §9).

Individual mode has no sign-in, so the address is the only gate. A request is
accepted only when its ``Host`` is a loopback name, a name listed in
``FITCHER_ALLOWED_HOSTS`` or a name in ``FITCHER_INTERNAL_HOSTS``, the
private names by which the web server reaches the api (``api`` in the
development Compose stack). A browser always sends the page's own host, so a
DNS-rebinding page cannot produce an allowed name. The web server forwards the
browser's host as ``X-Forwarded-Host``; when present it must be allowed too,
and it is the host a state-changing request's ``Origin`` must match.

A listed ``FITCHER_ALLOWED_HOSTS`` name makes the instance reachable by others,
which ``/me`` reports as ``exposed`` so the interface can warn. Team mode signs
users in and is not checked here.
"""

from collections.abc import Mapping
import json
import os
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

from app.state.db import StateDb, shared_state
from app.state.settings import Settings

LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
INDIVIDUAL = "individual"


def _names(value: str | None) -> frozenset[str]:
    return frozenset(name.strip().lower() for name in (value or "").split(",") if name.strip())


def allowed_hosts(env: Mapping[str, str] | None = None) -> frozenset[str]:
    return _names((os.environ if env is None else env).get("FITCHER_ALLOWED_HOSTS"))


def internal_hosts(env: Mapping[str, str] | None = None) -> frozenset[str]:
    return _names((os.environ if env is None else env).get("FITCHER_INTERNAL_HOSTS"))


def exposed(env: Mapping[str, str] | None = None) -> bool:
    """Whether a name other than loopback may reach the instance."""
    return bool(allowed_hosts(env) - LOOPBACK)


def hostname(host: str) -> str:
    """The name of a ``Host`` value without its port: ``[::1]:3000`` -> ``::1``."""
    host = host.strip().lower()
    if host.startswith("["):
        return host[1:].partition("]")[0]
    return host.rpartition(":")[0] if host.count(":") == 1 else host


def instance_mode(db: StateDb | None = None) -> str:
    """The instance's mode; a new instance is individual until its setup says otherwise."""
    return Settings(db or shared_state()).get("instance", "mode") or INDIVIDUAL


def https_forwarded(headers: Mapping[str, str]) -> bool:
    """A reverse proxy's ``X-Forwarded-Proto``, trusted only when the instance names its public hosts."""
    return bool(allowed_hosts()) and headers.get("x-forwarded-proto", "").strip().lower() == "https"


def refusal(method: str, host: str, forwarded: str | None, origin: str | None) -> str | None:
    """Why a request is refused in individual mode, or None when it is accepted."""
    accepted = LOOPBACK | allowed_hosts() | internal_hosts()
    browser_host = forwarded if forwarded is not None else host
    for value in (host, browser_host):
        if not value or hostname(value) not in accepted:
            return (f"the host {value!r} is not allowed; reach the instance through localhost or list the name "
                    "in FITCHER_ALLOWED_HOSTS")
    if method not in SAFE_METHODS:
        if not origin or urlsplit(origin).netloc.lower() != browser_host.strip().lower():
            return "a change must come from a page of this instance"
    return None


class HostOriginGuard:
    """ASGI middleware refusing, in individual mode, a request from a foreign host or a cross-origin change."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or instance_mode() != INDIVIDUAL:
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in scope["headers"]}
        reason = refusal(scope["method"], headers.get("host", ""), headers.get("x-forwarded-host"), headers.get("origin"))
        if reason is None:
            await self.app(scope, receive, send)
            return
        body = json.dumps({"detail": reason}).encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
