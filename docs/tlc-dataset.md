# TLC lab dataset

The lab uses one month of NYC TLC high-volume for-hire vehicle (HVFHV) trips and the taxi-zone lookup.
The fixed default is **March 2024**. `trips` includes only `hvfhs_license_num = 'HV0003'` (Uber); `zones` maps location IDs to borough and zone names.

Sources: [TLC trip records](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page), [HVFHV dictionary](https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_hvfhs.pdf), [March 2024 Parquet](https://d37ci6vzurychx.cloudfront.net/trip-data/fhvhv_tripdata_2024-03.parquet) and [zone CSV](https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv).

## Download and inspect

Use the Python 3.13/uv setup in [README](../README.md). From the repository root:

```bash
uv sync --project api --frozen
uv run --project api python -m scripts.download_tlc --month 2024-03
uv run --project api python -m scripts.check_tlc --month 2024-03
```

The same commands work in PowerShell and Bash. `--data-dir PATH` on both commands overrides the default `data/parquet` directory. Months must use `YYYY-MM`, from February 2019 onwards; unavailable months fail with the source HTTP error.

The downloader streams each response to a unique temporary file, checks its advertised byte length when present, validates Parquet metadata/required columns or CSV lookup structure, then publishes it atomically. Downloads use a 60-second socket timeout. Existing valid files are reused without downloading again; invalid files are preserved and reported for manual inspection. Interrupted downloads are cleaned up; restarting begins that file again. Validation does not supply an official source checksum or detect every possible damaged Parquet data page.

The zone lookup must contain each current official ID from 1 through 265 exactly once. This also rejects a response truncated at a valid row boundary when no length is advertised. If TLC changes the ID set, review and update the expected taxonomy before accepting the new revision. Newly published files use mode `0644` on Linux so the API's separate user can read them. For files created by older versions with mode `0600`, grant read access to the two downloaded inputs before container inspection; existing cached files are not automatically chmodded.

On Linux, a restrictive `umask 077` can also create the mounted `data/parquet` directory with mode `0700`. The API runs as UID `10001` and needs traversal access to this directory even when its files are readable. If needed, grant traversal and read access to these public TLC inputs before running the container check:

```bash
chmod o+x data/parquet
chmod a+r data/parquet/fhvhv_tripdata_2024-03.parquet data/parquet/taxi_zone_lookup.csv
```

Use the corresponding directory and filename when selecting another `--data-dir` or month. These POSIX permission commands apply to Linux hosts; no directory permissions are changed automatically by the downloader.

Keep Parquet, CSV, temporary files and databases under ignored `data/`; do not commit them. No OpenAI requests occur during download, inspection or tests.

`check_tlc` opens an in-memory DuckDB connection, binds local file paths to session variables, and loads [init_views.sql](../scripts/init_views.sql). Views are connection-scoped and must be initialized on each new connection. No data is copied into PostgreSQL or a persistent DuckDB database. The source trip columns remain available; the zone lookup has typed `LocationID`, `Borough`, `Zone` and `service_zone` columns.

The script prints `DESCRIBE trips`, source/Uber/zone counts and the complete results and wall-clock durations for three [sample queries](../scripts/sample_queries):

1. Daily Uber trip counts.
2. Weekly Uber trip counts and base passenger fares, summed as decimal cents.
3. Top ten pickup zones, retaining unmatched locations with a left join and using location ID to break count ties.

`base_passenger_fare` excludes additional charges such as tolls and tips; it is not net revenue or driver pay. Weeks begin on Monday and include only rows in the selected file. The first and last weeks can therefore be partial. TLC timestamps are used as published, without timezone conversion or additional data-quality filtering.

After rebuilding the stack, inspect the same read-only mounted files from Linux:

```bash
docker compose up --build --wait
docker compose exec api python -m scripts.check_tlc --month 2024-03
```

Download on the host first. The API's `data/parquet` mount is read-only. This inspection command runs fixed local SQL; the bounded executor and SQL validator are separate planned work.

## Native DuckDB CLI

With [DuckDB CLI 2.0.0](https://github.com/duckdb/duckdb/releases/tag/v2.0.0) installed, open `duckdb` from the repository root and enter:

```sql
SET VARIABLE trip_file = 'data/parquet/fhvhv_tripdata_2024-03.parquet';
SET VARIABLE zones_file = 'data/parquet/taxi_zone_lookup.csv';
.read scripts/init_views.sql
DESCRIBE trips;
SELECT count(*) AS uber_trips FROM trips;
SELECT count(*) AS zones FROM zones;
.timer on
.read scripts/sample_queries/daily_trip_counts.sql
.read scripts/sample_queries/weekly_base_fares.sql
.read scripts/sample_queries/top_pickup_zones.sql
```

## Observed March 2024 verification

Verified on 2026-10-29 with DuckDB 2.0.0, Python 3.13.3 and the native Windows CLI. These are observations for the downloaded files, not assertions about future TLC revisions.

| Input | Bytes | Observed SHA-256 |
| --- | ---: | --- |
| `fhvhv_tripdata_2024-03.parquet` | 507,940,560 | `ff25b93f890f889637963b749d0839ec5a15f075d23ea5297b3312ed9a10d6d9` |
| `taxi_zone_lookup.csv` | 12,331 | `1a99e105092230f8620f301edcca7f80d3080642ff404d28ed957d3fa222c8ed` |

These fingerprints were computed locally; TLC does not provide them as verification values in the download workflow.

The source contains 21,280,788 rows: 15,621,998 Uber rows and 5,658,790 Lyft rows. There are 265 distinct zone IDs. The Uber pickup range is March 1–31, with 31 daily groups. The zone join preserved all 15,621,998 Uber rows; none had unmatched pickup IDs in this file.

| Query | Windows Python | Windows native CLI | Linux API container | Result |
| --- | ---: | ---: | ---: | --- |
| Daily counts | 0.112 s | 0.124 s | 0.199 s | 31 rows; counts sum to 15,621,998 |
| Weekly base fares | 0.229 s | 0.197 s | 0.456 s | 5 rows; base fares sum to USD 403,016,613.40 |
| Top pickup zones | 0.218 s | 0.210 s | 0.299 s | 10 rows; JFK Airport leads with 281,614 trips |

These are single warm runs after schema/count inspection, with default DuckDB settings, not cold-cache benchmarks or latency guarantees.

Weekly results:

| Week starting | Uber trips | Base fares (USD) |
| --- | ---: | ---: |
| 2024-02-26 | 1,635,497 | 40,912,146.69 |
| 2024-03-04 | 3,499,512 | 92,603,531.78 |
| 2024-03-11 | 3,435,730 | 91,704,540.81 |
| 2024-03-18 | 3,574,241 | 90,888,093.02 |
| 2024-03-25 | 3,477,018 | 86,908,301.10 |

Correctness checks combined hand-calculated mixed-operator fixtures with independent aggregates over the raw Parquet: daily/weekly counts matched the raw Uber total, weekly fares matched the raw decimal fare total, and top pickup IDs/counts matched raw grouping without the zone join. Fixture tests also verify week boundaries, exact cents, quoted file paths and retention of unmatched zones.
