"""Download Iowa Liquor Sales 2025 for the PostgreSQL fixture of the ``sources`` profile.

Run with ``python infra/sources/iowa_liquor/fetch.py`` from the repository root.
It downloads the Iowa Data Hub's CSV export of dataset 1262 (every Class E
liquor purchase in Iowa in 2025, CC BY 4.0, published by the Iowa Department
of Revenue, Alcohol Operations Bureau), extracts it to
``data/sources/iowa_liquor/sales_2025.csv``, checks that its header holds the
columns ``seed.sh`` loads, and prints the row count and SHA-256 to record in
``jobs/sources/iowa_liquor.yaml``. ``data/`` is Git-ignored, so the dataset is
never committed. Only the standard library is used.
"""

import argparse
import csv
import hashlib
from pathlib import Path
import shutil
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[3]
SOURCE_URL = "https://idh-be.iowa.gov/api/v1/datasets/1262/rows.csv"
TARGET_DIR = ROOT / "data" / "sources" / "iowa_liquor"
CSV_NAME = "sales_2025.csv"
# The columns seed.sh copies into PostgreSQL, in the export's order.
COLUMNS = (
    "invoice_id", "ordered_on", "store_no", "store_name", "store_address", "store_city", "store_zip_code",
    "county_fips_code", "county_name", "category_code", "category_name", "vendor_number", "vendor_name", "item_no",
    "im_desc", "pack", "bottle_volume_ml", "state_bottle_cost", "state_bottle_retail", "sales_bottles",
    "sales_dollars", "sales_liters", "sales_gallons",
)
CHUNK = 1 << 20


class FetchError(RuntimeError):
    """The download is missing, malformed or not the expected export."""


def check_header(header: list[str]) -> None:
    if tuple(header) != COLUMNS:
        missing = sorted(set(COLUMNS) - set(header))
        extra = sorted(set(header) - set(COLUMNS))
        raise FetchError(f"unexpected header: missing {missing or 'none'}, extra {extra or 'none'}, or another order")


def extract_csv(archive: Path, target: Path) -> None:
    """Concatenate the CSV parts of the export into ``target`` with one header."""
    with zipfile.ZipFile(archive) as bundle:
        parts = sorted(name for name in bundle.namelist() if name.endswith(".csv"))
        if not parts:
            raise FetchError(f"{archive.name} holds no CSV file")
        with target.open("wb") as out:
            for number, name in enumerate(parts):
                with bundle.open(name) as part:
                    header = part.readline()
                    if number == 0:
                        out.write(header)
                    shutil.copyfileobj(part, out, CHUNK)


def summarize(path: Path) -> tuple[int, str]:
    """Rows after the header (checking it) and the SHA-256 of the file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        check_header(next(reader, []))
        rows = sum(1 for _ in reader)
    return rows, digest.hexdigest()


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "fitcher-lab-fixture"})
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as out:  # noqa: S310 - fixed https URL
        shutil.copyfileobj(response, out, CHUNK)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target-dir", type=Path, default=TARGET_DIR)
    args = parser.parse_args(argv)
    args.target_dir.mkdir(parents=True, exist_ok=True)
    archive = args.target_dir / "sales_2025.zip"
    csv_path = args.target_dir / CSV_NAME
    try:
        if not archive.is_file():
            print(f"Downloading {SOURCE_URL} ...")
            partial = archive.with_suffix(".zip.part")
            download(SOURCE_URL, partial)
            partial.replace(archive)
        extract_csv(archive, csv_path)
        rows, sha256 = summarize(csv_path)
    except (FetchError, OSError, zipfile.BadZipFile) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"{csv_path}: {rows} rows, sha256 {sha256}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
