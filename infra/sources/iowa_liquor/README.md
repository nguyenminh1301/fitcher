# Iowa Liquor Sales in the fixture PostgreSQL

The second industry's data (DECISIONS §4): every spirits purchase by a Class E liquor licensee in Iowa in 2025, one row per invoice line.
It sits in the `sources` profile's PostgreSQL as a company's own database would, and reaches ClickHouse only through the `iowa_liquor` source manifest, like any company's data.

Source: Iowa Data Hub dataset 1262, "Iowa Liquor Sales, 2025", published by the Iowa Department of Revenue, Alcohol Operations Bureau, under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The download is kept in the Git-ignored `data/sources/iowa_liquor/` and never committed.

```bash
python infra/sources/iowa_liquor/fetch.py
docker compose --profile sources up -d --wait
docker compose --profile sources exec postgres-fixture sh /seed/iowa_liquor/seed.sh
docker compose run --rm jobs python -m jobs.refresh_data --source iowa_liquor
```

`fetch.py` downloads the export once (a partial download is never reused), joins its parts into `sales_2025.csv`, checks the header and prints the row count and SHA-256.
`seed.sh` recreates database `iowa_liquor` with one `sales` table holding the export's columns as text, which the dbt staging model types, and the read-only role `IOWA_LIQUOR_POSTGRES_USER`; running it again reloads the data.
Set the `IOWA_LIQUOR_POSTGRES_*` variables in `.env` first (see `.env.example`).
