"""ClickHouse SQL that reaches a source manifest's tables (DECISIONS §4 Data sources).

The definitions live in ``app.sources.attach``, which the api uses for the
sources of the Sources page; a manifest is read through the same code:

- copy mode reads each table with a table function into ``raw.<source>__<table>``;
- live mode attaches database ``src_<source>``.

``relations`` tells dbt where each table is in the chosen mode.
"""

from app.sources.attach import (  # noqa: F401 - re-exported for the jobs and their tests
    DATABASE_ENGINES,
    FILE_FORMATS,
    LIVE_PREFIX,
    RAW_DATABASE,
    TABLE_FUNCTIONS,
    literal,
    live_database,
    live_statements,
    quote,
    raw_table,
    relations,
    table_function,
)
