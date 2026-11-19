"""Host and Origin checks of the personal app (DECISIONS §9).

There are no accounts, so the address is the gate. A request is
accepted only when its ``Host`` is a loopback name, a name listed in
``FITCHER_ALLOWED_HOSTS`` or a name in ``FITCHER_INTERNAL_HOSTS``, the
private names by which the web server reaches the api (``api`` in the
development Compose stack). A browser always sends the page's own host, so a
DNS-rebinding page cannot produce an allowed name. The web server forwards the
browser's host as ``X-Forwarded-Host``; when present it must be allowed too,
and it is the host a state-changing request's ``Origin`` must match.

A ``Host`` header is written by the client, so a loopback name alone does not
prove the request comes from this computer: any machine or container that
reaches the port can send ``Host: localhost``. A request naming a loopback host
is therefore accepted only from a local peer: a loopback address, a default
gateway of this network namespace (how Docker's published ports deliver the
host's connections into the container) or an address in
``FITCHER_TRUSTED_PEERS`` (addresses or networks, for container runtimes that
deliver them from elsewhere). The peer is the connection's address, or the
``X-Fitcher-Peer`` header that the web server overwrites with its own
connection's address on every request (``apps/web/peer-address.cjs``); the api
listens on loopback or on the Compose network, so only the web server reaches it.

A reverse proxy or tunnel on this computer connects to the published port like a local browser does, and a
stock nginx ``proxy_pass`` even rewrites ``Host`` to the loopback address it forwards to, so the internet it
relays would pass for this computer. The same hook therefore writes ``X-Fitcher-Proxy``: the signs that a proxy
relayed the request (forwarding headers, ``Connection: close``, HTTP/1.0). A request carrying any of them whose
browser host is a loopback name is refused; a proxy must send the public name, which ``FITCHER_ALLOWED_HOSTS``
lists and which needs the owner password.

A listed ``FITCHER_ALLOWED_HOSTS`` name makes the instance reachable by others,
which ``/me`` reports as ``exposed`` so the interface can warn.

The owner password (``app/auth/owner.py``) is checked after the address: once it is set, every request but
the public paths needs a signed-in session; without it, a request through a name other than this computer's
is refused until the owner sets one here.
"""

from collections.abc import Mapping
from functools import cache
from http.cookies import CookieError, SimpleCookie
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth import owner
from app.state.db import shared_state


LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
PEER_HEADER = "x-fitcher-peer"
PROXY_HEADER = "x-fitcher-proxy"
ROUTE_TABLE = Path("/proc/net/route")


def _names(value: str | None) -> frozenset[str]:
    return frozenset(name.strip().lower() for name in (value or "").split(",") if name.strip())


def allowed_hosts(env: Mapping[str, str] | None = None) -> frozenset[str]:
    return _names((os.environ if env is None else env).get("FITCHER_ALLOWED_HOSTS"))


def internal_hosts(env: Mapping[str, str] | None = None) -> frozenset[str]:
    return _names((os.environ if env is None else env).get("FITCHER_INTERNAL_HOSTS"))


def trusted_peers(env: Mapping[str, str] | None = None) -> list:
    """The networks of ``FITCHER_TRUSTED_PEERS``; an entry that is not an address or a network is ignored."""
    networks = []
    for entry in _names((os.environ if env is None else env).get("FITCHER_TRUSTED_PEERS")):
        try:
            networks.append(ip_network(entry, strict=False))
        except ValueError:
            continue
    return networks


@cache
def default_gateways(route_table: Path = ROUTE_TABLE) -> frozenset[IPv4Address]:
    """The IPv4 default gateways of this network namespace, read once from the kernel's route table."""
    try:
        lines = route_table.read_text().splitlines()[1:]
    except OSError:
        return frozenset()
    gateways = set()
    for line in lines:
        fields = line.split()
        if len(fields) > 2 and fields[1] == "00000000":
            try:
                gateways.add(IPv4Address(int(fields[2], 16).to_bytes(4, "little")))
            except ValueError:
                continue
    return frozenset(gateways)


def peer_address(value: str | None) -> IPv4Address | IPv6Address | None:
    """An address as a socket reports it, with an IPv4-mapped IPv6 address read as IPv4; None when it is not one."""
    try:
        address = ip_address((value or "").strip().partition("%")[0])
    except ValueError:
        return None
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def local_peer(value: str | None) -> bool:
    """Whether a peer address is this computer: loopback, a default gateway or a trusted peer network."""
    address = peer_address(value)
    if address is None:
        return False
    return (address.is_loopback or address in default_gateways()
            or any(address.version == network.version and address in network for network in trusted_peers()))


def exposed(env: Mapping[str, str] | None = None) -> bool:
    """Whether a name other than loopback may reach the instance."""
    return bool(allowed_hosts(env) - LOOPBACK)


def hostname(host: str) -> str:
    """The name of a ``Host`` value without its port: ``[::1]:3000`` -> ``::1``."""
    host = host.strip().lower()
    if host.startswith("["):
        return host[1:].partition("]")[0]
    return host.rpartition(":")[0] if host.count(":") == 1 else host


def https_forwarded(headers: Mapping[str, str]) -> bool:
    """A reverse proxy's ``X-Forwarded-Proto``, trusted only when the instance names its public hosts."""
    return bool(allowed_hosts()) and headers.get("x-forwarded-proto", "").strip().lower() == "https"


def refusal(method: str, host: str, forwarded: str | None, origin: str | None, peer: str | None = None,
            proxy: str | None = None) -> str | None:
    """Why a request is refused, or None when it is accepted; ``proxy`` lists the signs of a relaying proxy."""
    accepted = LOOPBACK | allowed_hosts() | internal_hosts()
    browser_host = forwarded if forwarded is not None else host
    for value in (host, browser_host):
        if not value or hostname(value) not in accepted:
            return (f"the host {value!r} is not allowed; reach the instance through localhost or list the name "
                    "in FITCHER_ALLOWED_HOSTS")
    if (proxy or "").strip() and hostname(browser_host) in LOOPBACK:
        return (f"the request names {browser_host!r} but came through a reverse proxy ({proxy.strip()}), so it is not "
                "this computer; make the proxy send the public host name (nginx: proxy_set_header Host $host), "
                "list it in FITCHER_ALLOWED_HOSTS and set an owner password")
    claimed = next((value for value in (browser_host, host) if hostname(value) in LOOPBACK), None)
    if claimed is not None and not local_peer(peer):
        return (f"the request names {claimed!r} but comes from {peer!r}, which is not this computer; "
                "list the address in FITCHER_TRUSTED_PEERS if your container runtime delivers local connections "
                "from it")
    if method not in SAFE_METHODS:
        if not origin or urlsplit(origin).netloc.lower() != browser_host.strip().lower():
            return "a change must come from a page of this instance"
    return None


# Reachable without a session: liveness, whether a password is set, and signing in or out.
PUBLIC = frozenset({("GET", "/health"), ("GET", "/owner/status"), ("POST", "/owner/session"), ("DELETE", "/owner/session")})
# Answered before a password exists to a request from another machine, so its page can say what to do.
OPEN_WITHOUT_PASSWORD = frozenset({("GET", "/health"), ("GET", "/owner/status")})


def session_cookie(header: str | None) -> str | None:
    cookies = SimpleCookie()
    try:
        cookies.load(header or "")
    except CookieError:
        return None
    morsel = cookies.get(owner.SESSION_COOKIE)
    return morsel.value if morsel else None


def remote(browser_host: str) -> bool:
    """Whether the browser reached the instance through a name other than this computer's."""
    return hostname(browser_host) not in LOOPBACK | internal_hosts()


def owner_refusal(method: str, path: str, browser_host: str, cookie: str | None) -> tuple[int, str] | None:
    """The status and reason of a request the owner password refuses, or None when it may go on."""
    db = shared_state()
    if owner.password_set(db):
        if (method, path) in PUBLIC or owner.session_valid(db, session_cookie(cookie)):
            return None
        return 401, "sign in with the owner password"
    if remote(browser_host) and (method, path) not in OPEN_WITHOUT_PASSWORD:
        return 403, (f"this instance is reachable from other machines through {browser_host!r}; set an owner "
                     "password on this computer first")
    return None


class HostOriginGuard:
    """ASGI middleware refusing a request from a foreign host or machine, or a cross-origin change."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in scope["headers"]}
        client = scope.get("client")
        peer = headers.get(PEER_HEADER, client[0] if client else None)
        forwarded = headers.get("x-forwarded-host")
        reason = refusal(scope["method"], headers.get("host", ""), forwarded, headers.get("origin"), peer,
                         headers.get(PROXY_HEADER))
        refused = (403, reason) if reason is not None else owner_refusal(
            scope["method"], scope["path"], forwarded if forwarded is not None else headers.get("host", ""), headers.get("cookie"))
        if refused is None:
            await self.app(scope, receive, send)
            return
        code, detail = refused
        body = json.dumps({"detail": detail}).encode()
        await send({"type": "http.response.start", "status": code,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
