# dbt project

dbt-clickhouse models transform the ClickHouse `raw` database into the wide marts the agent queries.
The agent never queries `raw` directly.

See [DECISIONS §4](../docs/DECISIONS.md#4-lab-dataset). The project and the first marts arrive in [Phase 1](../docs/plans/phase-01-data-and-marts.md).
