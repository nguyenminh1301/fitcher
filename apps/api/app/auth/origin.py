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

A listed ``FITCHER_ALLOWED_HOSTS`` name makes the instance reachable by others,
which ``/me`` reports as ``exposed`` so the interface can warn.
"""

from collections.abc import Mapping
from functools import cache
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send


LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
PEER_HEADER = "x-fitcher-peer"
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


def refusal(method: str, host: str, forwarded: str | None, origin: str | None, peer: str | None = None) -> str | None:
    """Why a request is refused, or None when it is accepted."""
    accepted = LOOPBACK | allowed_hosts() | internal_hosts()
    browser_host = forwarded if forwarded is not None else host
    for value in (host, browser_host):
        if not value or hostname(value) not in accepted:
            return (f"the host {value!r} is not allowed; reach the instance through localhost or list the name "
                    "in FITCHER_ALLOWED_HOSTS")
    claimed = next((value for value in (browser_host, host) if hostname(value) in LOOPBACK), None)
    if claimed is not None and not local_peer(peer):
        return (f"the request names {claimed!r} but comes from {peer!r}, which is not this computer; "
                "list the address in FITCHER_TRUSTED_PEERS if your container runtime delivers local connections "
                "from it")
    if method not in SAFE_METHODS:
        if not origin or urlsplit(origin).netloc.lower() != browser_host.strip().lower():
            return "a change must come from a page of this instance"
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
        reason = refusal(scope["method"], headers.get("host", ""), headers.get("x-forwarded-host"), headers.get("origin"),
                         peer)
        if reason is None:
            await self.app(scope, receive, send)
            return
        body = json.dumps({"detail": reason}).encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
