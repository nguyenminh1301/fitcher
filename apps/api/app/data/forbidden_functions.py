"""ClickHouse functions no agent query or metric expression may call.

The SQL guard rejects generated queries that call them, and the pack compiler
rejects metric expressions that do, since every query built on such a metric
would be refused and the compile test-run itself runs as the admin user.
"""

from sqlglot import exp

FORBIDDEN_FUNCTIONS = frozenset(name.lower() for name in (
    # table functions and external access
    "file", "url", "urlCluster", "remote", "remoteSecure", "s3", "s3Cluster", "gcs", "azureBlobStorage",
    "azureBlobStorageCluster", "hdfs", "hdfsCluster", "mysql", "postgresql", "mongodb", "redis", "sqlite",
    "jdbc", "odbc", "executable", "input", "cluster", "clusterAllReplicas", "merge", "view", "dictionary",
    "generateRandom", "numbers", "numbers_mt", "zeros", "zeros_mt", "values", "format", "null", "iceberg",
    "deltaLake", "hudi", "loop", "fuzzJSON",
    # column matchers that bypass the column allowlist
    "columns",
    # reads outside the query's tables
    "joinGet", "joinGetOrNull",
    # deliberate stalls
    "sleep", "sleepEachRow",
))
FORBIDDEN_PREFIXES = ("dictget", "dicthas", "dictis")


def function_name(node: exp.Func) -> str:
    return (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()


def forbidden_function(tree: exp.Expression) -> str | None:
    """Lower-case name of the first forbidden function ``tree`` calls, or None."""
    for node in tree.find_all(exp.Func):
        name = function_name(node)
        if name in FORBIDDEN_FUNCTIONS or name.startswith(FORBIDDEN_PREFIXES):
            return name
    return None
