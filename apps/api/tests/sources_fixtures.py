"""A fake ClickHouse that models what the sources service asks of it, and a catalog to list."""

import re

PG_CATALOG = {
    "pg_class": [("orders", "r", 1200.0, 50, "100"), ("order_items", "r", -1.0, 0, "101")],
    "pg_stat_user_tables": [("order_items", 40000)],
    "table = 'columns'": [
        ("orders", "id", "integer", "int4", "NO", 1), ("orders", "created_at", "timestamp", "timestamp", "NO", 2),
        ("order_items", "line_ref", "integer", "int4", "NO", 1),
    ],
    "pg_constraint": [("orders_pkey", "p", "100", "0", [1], []), ("items_fkey", "f", "101", "100", [1], [1])],
    "pg_attribute": [("100", 1, "id"), ("101", 1, "line_ref")],
}


class FakeClickHouse:
    """Records every statement; ``command`` answers counts and cursors from ``tables``, ``query`` the catalog."""

    def __init__(self, catalog=None, mart_definitions=(), fail_on=None, error=None, existing_collections=()):
        self.sql: list[str] = []
        self.settings: list[dict | None] = []
        self.catalog = PG_CATALOG if catalog is None else catalog
        self.mart_definitions = list(mart_definitions)
        self.fail_on = fail_on
        self.error = error or RuntimeError("source unreachable")
        self.collections = set(existing_collections)
        self.raw: dict[str, int] = {}
        self.source_rows = {"orders": 5, "order_items": 7}
        self.cursor = "41"

    def command(self, sql, parameters=None, settings=None):
        self.sql.append(sql)
        self.settings.append(settings)
        if self.fail_on and re.search(self.fail_on, sql):
            raise self.error
        if m := re.match(r"CREATE NAMED COLLECTION `(\w+)`", sql):
            if m[1] in self.collections:
                raise RuntimeError("A named collection already exists. (NAMED_COLLECTION_ALREADY_EXISTS)")
            self.collections.add(m[1])
        elif m := re.match(r"DROP NAMED COLLECTION IF EXISTS `(\w+)`", sql):
            self.collections.discard(m[1])
        elif m := re.match(r"EXISTS TABLE `raw`\.`(\w+)`", sql):
            return int(m[1] in self.raw)
        elif m := re.match(r"SELECT count\(\) FROM `raw`\.`(\w+)`", sql):
            return self.raw.get(m[1], 0)
        elif m := re.match(r"SELECT count\(\) FROM `src_\w+`\.`(\w+)`", sql):
            return self.source_rows.get(m[1], 0)
        elif m := re.match(r"CREATE TABLE `raw`\.`(\w+)__loading` ENGINE .* table = '(\w+)'", sql):
            self.raw[m[1] + "__loading"] = self.source_rows[m[2]]
        elif m := re.match(r"CREATE TABLE `raw`\.`(\w+)__loading` AS `raw`\.`(\w+)`", sql):
            self.raw[m[1] + "__loading"] = 0
        elif m := re.match(r"INSERT INTO `raw`\.`(\w+)__loading` SELECT .* table = '(\w+)'", sql):
            self.raw[m[1] + "__loading"] += 2
        elif m := re.match(r"INSERT INTO `raw`\.`(\w+)` SELECT \* FROM `raw`\.`\w+__loading`", sql):
            self.raw[m[1]] += self.raw[m[1] + "__loading"]
        elif m := re.match(r"RENAME TABLE `raw`\.`(\w+)__loading` TO `raw`\.`(\w+)`", sql):
            self.raw[m[2]] = self.raw.pop(m[1] + "__loading")
        elif m := re.match(r"EXCHANGE TABLES `raw`\.`(\w+)__loading` AND `raw`\.`(\w+)`", sql):
            self.raw[m[1] + "__loading"], self.raw[m[2]] = self.raw[m[2]], self.raw[m[1] + "__loading"]
        elif m := re.match(r"DROP TABLE (?:IF EXISTS )?`raw`\.`(\w+)`", sql):
            self.raw.pop(m[1], None)
        elif sql.startswith("SELECT toString(max("):
            return self.cursor
        return 0

    def query(self, sql, parameters=None, settings=None):
        self.sql.append(sql)
        if self.fail_on and re.search(self.fail_on, sql):
            raise self.error
        if "system.named_collections" in sql:
            rows = [(parameters["name"],)] if parameters["name"] in self.collections else []
        elif "system.tables" in sql:
            rows = [(name, definition) for name, definition in self.mart_definitions]
        else:
            rows = next((rows for fragment, rows in self.catalog.items() if fragment in sql), [])
        return type("Result", (), {"result_rows": rows})()


class UploadClickHouse(FakeClickHouse):
    """Adds schema inference and the streamed insert to the fake."""

    def __init__(self, inferred=None, **kwargs):
        super().__init__(**kwargs)
        self.inferred = inferred or [("Mã đơn", "Nullable(String)"), ("Số tiền", "Nullable(Float64)"),
                                     ("Ngày", "Nullable(Date)")]
        self.inserted: list[tuple] = []

    def query(self, sql, parameters=None, settings=None):
        if sql.startswith("DESCRIBE TABLE format("):
            self.sql.append(sql)
            self.parameters = parameters
            self.query_settings = settings
            rows = [(name, kind, "", "", "", "", "") for name, kind in self.inferred]
            return type("Result", (), {"result_rows": rows})()
        return super().query(sql, parameters, settings)

    def command(self, sql, parameters=None, settings=None):
        if sql.startswith("CREATE TABLE `raw`") and "ENGINE = MergeTree ORDER BY tuple()" in sql and "AS SELECT" not in sql:
            self.sql.append(sql)
            self.raw[sql.split("`")[3]] = 0
            return 0
        if sql.startswith("SELECT count() FROM `raw`.`") and sql.split("`")[3].endswith("__loading"):
            self.sql.append(sql)
            return self.raw.get(sql.split("`")[3], 0)
        return super().command(sql, parameters, settings)

    def raw_insert(self, table, column_names=None, insert_block=None, settings=None, fmt=None, **_):
        data = insert_block if isinstance(insert_block, bytes) else b"".join(insert_block)
        self.inserted.append((table, fmt, settings, data))
        self.raw[table.split(".")[1].strip("`")] = max(data.count(b"\n") - 1, 0)
        if self.fail_on == "raw_insert":
            raise self.error


class FakeSqlServer:
    """Stands for ``app.sources.sqlserver.SqlServer``: the catalog it lists and what a copy does to ``raw``."""

    def __init__(self, clickhouse, tables=None, error=None):
        from app.sources.inspect import CatalogColumn, TableInfo

        self.clickhouse = clickhouse
        self.error = error
        self.tables_listed = tables if tables is not None else [
            TableInfo("orders", "table", 1200, 400_000, columns=(CatalogColumn("id", "int", False, 1),
                                                                 CatalogColumn("placed", "datetime2", False, 2)),
                      primary_key=("id",)),
            TableInfo("big", "table", 9_000_000, 2 * 1024**3),
        ]
        self.calls: list[tuple] = []

    def check(self, **params):
        self.calls.append(("check", params))
        if self.error:
            raise self.error

    def tables(self, *, schema, **params):
        self.calls.append(("tables", {"schema": schema, **params}))
        if self.error:
            raise self.error
        return self.tables_listed

    def copy(self, clickhouse, source, table, *, cursor_column, after, schema, should_stop=None, **params):
        from app.sources.attach import CopyOutcome

        self.calls.append(("copy", {"table": table, "cursor_column": cursor_column, "after": after, "schema": schema, **params}))
        if self.error:
            raise self.error
        clickhouse.raw[f"{source.name}__{table}"] = 7
        return CopyOutcome(7, "70" if cursor_column else None, after is None)
