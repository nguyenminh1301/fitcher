"""Create, replace and drop the named collection of a source with SQL (DECISIONS §4 Data sources).

The collection holds the host, port, user, password and TLS settings of the source and is named after it. It is
created as ``source_admin``, which may manage collections but not read their secrets; ClickHouse stores it
encrypted and writes these statements to its logs with every value hidden. The password is written once and
kept nowhere else.

A failed statement is reported as a ``CollectionError`` with a fixed reason and no text from the driver: a
rejected statement can echo what it was given, so neither the exception nor its cause may carry it.
"""

from app.sources.attach import literal, quote, valid_name
from app.sources.connection import Connection, ConnectionFieldError


class CollectionError(RuntimeError):
    """A collection could not be created, replaced or dropped; ``reason`` is ``name_taken`` or ``failed``."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def collection_params(connection: Connection) -> dict[str, str | int]:
    """The keys of the named collection for ``connection``, in the order they are written."""
    # The database and schema are not secret: they are named where the collection is used (``attach``), because
    # a key the collection holds cannot be overridden by a user that may not read secrets.
    # A connection without a password (an edit that keeps the stored one) leaves the key out.
    params: dict[str, str | int] = {"host": connection.host, "port": connection.port, "user": connection.user}
    if connection.password is not None:
        params["password"] = connection.password
    if connection.kind == "postgres":
        params["sslmode"] = "verify-full" if connection.tls_mode == "verify" else connection.tls_mode
        if connection.ca_certificate:
            params["sslrootcert_pem"] = connection.ca_certificate
        return params
    # The MySQL engine takes only certificates: TLS is used when the server offers it and a CA certificate
    # makes the engine verify the server, so requiring TLS without one cannot be honoured.
    if connection.tls_mode != "prefer" and not connection.ca_certificate:
        raise ConnectionFieldError("a CA certificate is required to require or verify TLS on MySQL")
    if connection.ca_certificate:
        params["ssl_ca_pem"] = connection.ca_certificate
    return params


def ca_key(kind: str) -> str:
    """The collection key that holds a CA certificate."""
    return "sslrootcert_pem" if kind == "postgres" else "ssl_ca_pem"


def _assignments(params: dict[str, str | int]) -> str:
    return ", ".join(f"{key} = {value if isinstance(value, int) else literal(value)}" for key, value in params.items())


def _checked(name: str) -> str:
    if not valid_name(name):
        raise ValueError(f"{name!r} is not a valid source name")
    return quote(name)


class CollectionAdmin:
    def __init__(self, client):
        self._client = client

    def _run(self, sql: str, what: str) -> None:
        try:
            self._client.command(sql)
        except Exception as error:  # noqa: BLE001 - the driver text may echo the statement, so it is dropped
            taken = "already exists" in str(error)
            raise CollectionError("name_taken" if taken else "failed", f"cannot {what}") from None

    def create(self, name: str, connection: Connection) -> None:
        self._run(f"CREATE NAMED COLLECTION {_checked(name)} AS {_assignments(collection_params(connection))}",
                  "create the named collection")

    def replace(self, name: str, connection: Connection, drop: list[str] | tuple[str, ...] = ()) -> None:
        """Set the keys of ``connection`` and delete the keys in ``drop``.

        A key the connection leaves out (the password, the CA certificate) keeps its stored value: nothing is
        read back, so an edit that does not name a secret never rewrites it.
        """
        statement = f"ALTER NAMED COLLECTION {_checked(name)} SET {_assignments(collection_params(connection))}"
        if drop:
            statement += " DELETE " + ", ".join(drop)
        self._run(statement, "replace the named collection")

    def drop(self, name: str) -> None:
        self._run(f"DROP NAMED COLLECTION IF EXISTS {_checked(name)}", "drop the named collection")

    def exists(self, name: str) -> bool:
        rows = self._client.query(
            "SELECT name FROM system.named_collections WHERE name = {name:String}", parameters={"name": name}
        ).result_rows
        return bool(rows)
