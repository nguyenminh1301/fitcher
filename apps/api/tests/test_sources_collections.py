"""The named collection that holds a source's credentials, created with SQL as ``source_admin`` (DECISIONS §4)."""

import pytest

from app.sources.collections import CollectionAdmin, CollectionError, ca_key, collection_params
from app.sources.connection import Connection, ConnectionFieldError, validate

SECRET = "pw'with\\odd\"chars-91827"


def postgres(**changes):
    fields = dict(kind="postgres", host="db.internal", port=5432, database="shop", user="reader", password=SECRET,
                  schema="public", tls_mode="prefer", ca_certificate=None)
    return Connection(**(fields | changes))


def mysql(**changes):
    fields = dict(kind="mysql", host="db.internal", port=3306, database="shop", user="reader", password=SECRET,
                  schema=None, tls_mode="prefer", ca_certificate=None)
    return Connection(**(fields | changes))


class FakeClient:
    def __init__(self, error=None, rows=()):
        self.sql: list[str] = []
        self.queries: list[tuple] = []
        self.error = error
        self.rows = rows

    def command(self, sql, **_):
        self.sql.append(sql)
        if self.error:
            raise self.error

    def query(self, sql, parameters=None):
        self.queries.append((sql, parameters))

        class Result:
            result_rows = self.rows

        return Result()


def test_a_postgres_collection_carries_the_credentials_and_tls_mode_but_not_the_database_or_schema():
    # The database and schema are not secret and are named where the collection is used: a key the collection
    # holds cannot be overridden by a user without the grant to read secrets, and the catalog is read as
    # another schema (or, in MySQL, another database).
    assert collection_params(postgres()) == {
        "host": "db.internal", "port": 5432, "user": "reader", "password": SECRET, "sslmode": "prefer",
    }


def test_a_postgres_ca_certificate_is_passed_and_verifies_the_server():
    params = collection_params(postgres(tls_mode="verify", ca_certificate="-----BEGIN CERTIFICATE-----\nx\n"))

    assert params["sslmode"] == "verify-full"
    assert params["sslrootcert_pem"] == "-----BEGIN CERTIFICATE-----\nx\n"


def test_a_mysql_collection_takes_the_ca_certificate():
    params = collection_params(mysql(tls_mode="require", ca_certificate="PEM"))

    assert params == {"host": "db.internal", "port": 3306, "user": "reader", "password": SECRET, "ssl_ca_pem": "PEM"}


def test_requiring_tls_on_mysql_needs_a_ca_certificate_because_the_engine_cannot_require_it_alone():
    with pytest.raises(ConnectionFieldError, match="CA certificate"):
        collection_params(mysql(tls_mode="require"))


def test_creating_a_collection_writes_every_value_as_an_escaped_literal():
    client = FakeClient()

    CollectionAdmin(client).create("shop", postgres())

    assert client.sql == [
        "CREATE NAMED COLLECTION `shop` AS host = 'db.internal', port = 5432, user = 'reader', "
        "password = 'pw\\'with\\\\odd\"chars-91827', sslmode = 'prefer'"
    ]


def test_replacing_a_collection_alters_it_and_removes_the_keys_it_is_told_to_drop():
    client = FakeClient()

    CollectionAdmin(client).replace("shop", postgres(password="new-pass"), drop=["sslrootcert_pem"])

    assert client.sql == [
        "ALTER NAMED COLLECTION `shop` SET host = 'db.internal', port = 5432, user = 'reader', "
        "password = 'new-pass', sslmode = 'prefer' DELETE sslrootcert_pem"
    ]


def test_replacing_without_keys_to_drop_deletes_nothing():
    client = FakeClient()

    CollectionAdmin(client).replace("shop", postgres())

    assert " DELETE " not in client.sql[0]


def test_dropping_a_collection_that_does_not_exist_is_not_an_error():
    client = FakeClient()

    CollectionAdmin(client).drop("shop")

    assert client.sql == ["DROP NAMED COLLECTION IF EXISTS `shop`"]


def test_existence_reads_the_collection_list_with_a_bound_name():
    client = FakeClient(rows=[("shop",)])

    assert CollectionAdmin(client).exists("shop") is True
    assert client.queries == [("SELECT name FROM system.named_collections WHERE name = {name:String}", {"name": "shop"})]
    assert CollectionAdmin(FakeClient(rows=[])).exists("shop") is False


@pytest.mark.parametrize("name", ["Shop", "", "raw", "a-b", "x" * 41])
def test_a_collection_name_must_be_a_source_name(name):
    with pytest.raises(ValueError, match="source name"):
        CollectionAdmin(FakeClient()).create(name, postgres())


def test_a_failure_never_carries_the_statement_or_the_password_not_even_as_its_cause():
    leaking = RuntimeError(f"Syntax error near password = '{SECRET}' in query CREATE NAMED COLLECTION")

    with pytest.raises(CollectionError) as raised:
        CollectionAdmin(FakeClient(error=leaking)).create("shop", postgres())

    assert SECRET not in str(raised.value) and "CREATE" not in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__


def test_a_name_taken_by_a_collection_in_the_server_configuration_is_reported_as_taken():
    error = RuntimeError("Code: 36. DB::Exception: Cannot create named collection shop: it already exists (BAD_ARGUMENTS)")

    with pytest.raises(CollectionError) as raised:
        CollectionAdmin(FakeClient(error=error)).create("shop", postgres())

    assert raised.value.reason == "name_taken"


@pytest.mark.parametrize("fields", [
    dict(host=""), dict(host="db host"), dict(host="http://db"), dict(host="db/x"), dict(port=0), dict(port=70000),
    dict(database=""), dict(user=""), dict(tls_mode="sometimes"),
])
def test_invalid_connection_fields_are_refused(fields):
    with pytest.raises(ConnectionFieldError):
        validate(postgres(**fields))


def test_a_valid_connection_is_returned_unchanged_with_a_trimmed_host():
    assert validate(postgres(host=" db.internal ")).host == "db.internal"


def test_only_postgres_and_mysql_can_be_connected():
    with pytest.raises(ConnectionFieldError, match="kind"):
        validate(postgres(kind="oracle"))


def test_the_schema_defaults_to_public_for_postgres_and_is_dropped_for_mysql():
    assert validate(postgres(schema=None)).schema == "public"
    assert validate(mysql(schema="ignored")).schema is None


def test_a_connection_without_a_password_or_certificate_leaves_those_keys_out_so_the_stored_ones_stay():
    params = collection_params(postgres(password=None))

    assert "password" not in params and "sslrootcert_pem" not in params
    client = FakeClient()
    CollectionAdmin(client).replace("shop", postgres(password=None, host="other"))
    assert "password" not in client.sql[0] and "other" in client.sql[0]


def test_the_certificate_key_depends_on_the_kind():
    assert ca_key("postgres") == "sslrootcert_pem" and ca_key("mysql") == "ssl_ca_pem"
