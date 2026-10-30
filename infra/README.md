# Infrastructure

Service configuration for the local lab; `compose.yaml` at the repository root references these files so plain `docker compose` works without `-f`.
See [DECISIONS §3](../docs/DECISIONS.md#3-docker-compose) and the [Phase 0 plan](../docs/plans/phase-00-repository-and-infrastructure.md).

| Path | Purpose |
| --- | --- |
| `clickhouse/config.d/listen.xml` | Listen on container interfaces; Compose publishes ports on host loopback only |
| `clickhouse/users.d/users.xml` | Removes the passwordless `default` user |
| `clickhouse/initdb/001-databases.sql` | Creates `raw`, `marts` and `data_meta` |
| `litellm/config.yaml` | Aliases `fast`, `sql-gen`, `sql-gen-hard` and `embed`, with models from `LITELLM_MODEL_*` |
| `keycloak/realm-finch.json` | Realm `finch` with the public `finch-web` client and no users |
| `opensearch/` | Host requirements; no custom JVM or plugin settings |

## ClickHouse users and databases

The image entrypoint creates the admin user from `CLICKHOUSE_ADMIN_USER` and `CLICKHOUSE_ADMIN_PASSWORD`.
Scripts in `initdb/` run only when the `clickhouse-data` volume is empty.
The script is idempotent; apply it to an existing volume with:

```bash
docker compose exec -T clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --queries-file /docker-entrypoint-initdb.d/001-databases.sql'
```

Changing the admin password in `.env` after the first start also needs only a container recreate, because the entrypoint rewrites the user file on every start.

## LiteLLM

Change a model by editing its `LITELLM_MODEL_*` value in `.env` and running `docker compose up -d --wait litellm`.
The proxy requires `LITELLM_MASTER_KEY`; `OPENAI_API_KEY` reaches only this container.

## Keycloak

Keycloak runs `start-dev` with its embedded development database and imports `realm-finch.json` when the realm does not exist.
Edits to the realm file apply after `docker compose up -d --force-recreate --wait keycloak`, which starts from a new container.
