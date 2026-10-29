"""Download official NYC TLC inputs for one lab month."""

import argparse
import csv
from pathlib import Path
import re
import sys
import tempfile
from urllib.request import urlopen

import duckdb

ROOT = Path(__file__).resolve().parents[1]
TLC_BASE_URL = "https://d37ci6vzurychx.cloudfront.net"
DEFAULT_MONTH = "2024-03"
EXPECTED_ZONE_IDS = frozenset(range(1, 266))


def parse_month(value: str) -> str:
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", value) or value < "2019-02":
        raise ValueError("Expected YYYY-MM from 2019-02 onwards.")
    return value


def validate_file(path: Path, suffix: str) -> None:
    try:
        if suffix == ".parquet":
            with duckdb.connect() as connection:
                columns = connection.read_parquet(str(path)).columns
            required = {"hvfhs_license_num", "pickup_datetime", "PULocationID", "DOLocationID", "base_passenger_fare"}
            if not required.issubset(columns):
                raise ValueError("Missing HVFHV columns")
        else:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames != ["LocationID", "Borough", "Zone", "service_zone"]:
                    raise ValueError("Unexpected taxi-zone columns")
                rows = list(reader)
            ids = [int(row["LocationID"]) for row in rows]
            malformed = any(None in row or any(value is None for value in row.values()) for row in rows)
            if set(ids) != EXPECTED_ZONE_IDS or len(ids) != len(set(ids)) or malformed:
                raise ValueError("Incomplete, duplicate or malformed taxi-zone rows")
    except (duckdb.Error, ValueError, KeyError, TypeError, UnicodeError, csv.Error) as error:
        raise ValueError(f"Invalid TLC input: {path.name}. Move invalid existing files aside before retrying.") from error


def download_file(url: str, destination: Path) -> Path:
    if destination.exists():
        validate_file(destination, destination.suffix)
        print(f"Using existing {destination.name}", flush=True)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    print(f"Downloading {destination.name} ...", flush=True)
    try:
        with urlopen(url, timeout=60) as response:
            expected_length = response.headers.get("Content-Length")
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=destination.name + ".", suffix=".part", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                received = 0
                while chunk := response.read(1024 * 1024):
                    handle.write(chunk)
                    received += len(chunk)
        if expected_length is not None and received != int(expected_length):
            raise ValueError(f"Download length mismatch for {destination.name}")
        validate_file(temporary, destination.suffix)
        temporary.chmod(0o644)
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f"Saved {destination.name} ({received:,} bytes)", flush=True)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", type=parse_month, default=DEFAULT_MONTH)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "parquet")
    args = parser.parse_args()
    name = f"fhvhv_tripdata_{args.month}.parquet"
    try:
        download_file(f"{TLC_BASE_URL}/trip-data/{name}", args.data_dir / name)
        download_file(f"{TLC_BASE_URL}/misc/taxi_zone_lookup.csv", args.data_dir / "taxi_zone_lookup.csv")
    except (OSError, ValueError) as error:
        print(f"Download failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
