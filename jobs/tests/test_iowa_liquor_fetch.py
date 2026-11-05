"""The Iowa Liquor Sales fixture download: header check, part concatenation and row count."""

import importlib.util
from pathlib import Path
import zipfile

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "sources" / "iowa_liquor" / "fetch.py"
spec = importlib.util.spec_from_file_location("iowa_liquor_fetch", SCRIPT)
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)

HEADER = ",".join(fetch.COLUMNS)
ROW = "INV-1,2025-01-02,1,STORE,ADDR,CITY,50000,19001,ADAIR,1,CAT,035,VENDOR,9,ITEM,12,750,10.5,15.75,6,94.5,4.5,1.18"


def bundle(tmp_path: Path, parts: list[list[str]]) -> Path:
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as out:
        for number, rows in enumerate(parts, start=1):
            out.writestr(f"rows_part_{number:04d}.csv", "\n".join([HEADER, *rows]) + "\n")
    return archive


def test_parts_are_joined_under_one_header_and_counted(tmp_path):
    archive = bundle(tmp_path, [[ROW, ROW], [ROW]])
    target = tmp_path / "sales.csv"

    fetch.extract_csv(archive, target)
    rows, sha256 = fetch.summarize(target)

    assert target.read_text(encoding="utf-8").count("invoice_id") == 1
    assert rows == 3 and len(sha256) == 64


def test_an_export_with_another_header_is_refused(tmp_path):
    target = tmp_path / "sales.csv"
    target.write_text("invoice_id,ordered_on\nINV-1,2025-01-02\n", encoding="utf-8")
    with pytest.raises(fetch.FetchError, match="missing"):
        fetch.summarize(target)


def test_an_archive_without_csv_is_refused(tmp_path):
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("readme.txt", "nothing")
    with pytest.raises(fetch.FetchError, match="no CSV"):
        fetch.extract_csv(archive, tmp_path / "sales.csv")
