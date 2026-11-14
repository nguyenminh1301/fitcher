"""The connection fields of a source and the rules they must meet before anything is sent to ClickHouse.

Only PostgreSQL and MySQL/MariaDB are connected from the Sources page. The password is part of ``Connection``
for the one call that writes it into a named collection; it is never stored by the app state, returned by an
endpoint or included in a log line (DECISIONS §4).
"""

from dataclasses import dataclass, replace
import re

KINDS = ("postgres", "mysql")
DEFAULT_PORTS = {"postgres": 5432, "mysql": 3306}
TLS_MODES = ("prefer", "require", "verify")
DEFAULT_SCHEMA = "public"
# A host name, an IPv4 or an IPv6 address, as the user types it: no scheme, path, port or whitespace.
HOST = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$|^[0-9A-Fa-f:]+$")


class ConnectionFieldError(ValueError):
    """A connection field is missing or does not fit the kind of source."""


@dataclass(frozen=True)
class Connection:
    kind: str
    host: str
    port: int
    database: str
    user: str
    password: str | None
    schema: str | None = None
    tls_mode: str = "prefer"
    ca_certificate: str | None = None


def validate(connection: Connection) -> Connection:
    """The connection with a trimmed host and the schema that fits its kind; raises ``ConnectionFieldError``."""
    if connection.kind not in KINDS:
        raise ConnectionFieldError(f"unknown kind {connection.kind!r}; use one of {', '.join(KINDS)}")
    host = (connection.host or "").strip()
    if not HOST.match(host):
        raise ConnectionFieldError("the host must be a name or an address without a scheme, port or path")
    if not 1 <= connection.port <= 65535:
        raise ConnectionFieldError("the port must be between 1 and 65535")
    for label, value in (("database", connection.database), ("user", connection.user)):
        if not (value or "").strip():
            raise ConnectionFieldError(f"the {label} is required")
    if connection.tls_mode not in TLS_MODES:
        raise ConnectionFieldError(f"the TLS mode must be one of {', '.join(TLS_MODES)}")
    schema = (connection.schema or DEFAULT_SCHEMA).strip() if connection.kind == "postgres" else None
    return replace(connection, host=host, database=connection.database.strip(), user=connection.user.strip(),
                   schema=schema)
