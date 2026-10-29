"""Inspect local TLC views and run the three sample queries."""

import argparse
from pathlib import Path
import sys
from time import perf_counter

import duckdb

from scripts.download_tlc import DEFAULT_MONTH, ROOT, parse_month

QUERY_DIR = Path(__file__).resolve().parent / "sample_queries"


def initialize_views(connection: duckdb.DuckDBPyConnection, data_dir: Path, month: str) -> None:
    month = parse_month(month)
    trips = (data_dir / f"fhvhv_tripdata_{month}.parquet").resolve()
    zones = (data_dir / "taxi_zone_lookup.csv").resolve()
    for path in (trips, zones):
        if not path.is_file():
            raise FileNotFoundError(f"Missing {path}. Run python -m scripts.download_tlc first.")
    connection.execute("SET VARIABLE trip_file = ?", [str(trips)])
    connection.execute("SET VARIABLE zones_file = ?", [str(zones)])
    connection.execute((Path(__file__).with_name("init_views.sql")).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", type=parse_month, default=DEFAULT_MONTH)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "parquet")
    args = parser.parse_args()
    try:
        with duckdb.connect() as connection:
            initialize_views(connection, args.data_dir, args.month)
            print(f"DuckDB {duckdb.__version__}; TLC month {args.month}")
            print("trips schema (name, type):")
            for row in connection.execute("DESCRIBE trips").fetchall():
                print(f"  {row[0]}: {row[1]}")
            raw_count = connection.execute(
                "SELECT count(*) FROM read_parquet(getvariable('trip_file'))"
            ).fetchone()[0]
            trip_count = connection.execute("SELECT count(*) FROM trips").fetchone()[0]
            zone_count = connection.execute("SELECT count(*) FROM zones").fetchone()[0]
            print(f"Source rows: {raw_count:,}; Uber trips: {trip_count:,}; zones: {zone_count}")
            for name in ("daily_trip_counts", "weekly_base_fares", "top_pickup_zones"):
                sql = (QUERY_DIR / f"{name}.sql").read_text(encoding="utf-8")
                started = perf_counter()
                result = connection.execute(sql)
                columns = [column[0] for column in result.description]
                rows = result.fetchall()
                elapsed = perf_counter() - started
                print(f"\n{name}: {elapsed:.3f}s")
                print(" | ".join(columns))
                for row in rows:
                    print(" | ".join(str(value) for value in row))
    except (OSError, ValueError, duckdb.Error) as error:
        print(f"TLC check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
