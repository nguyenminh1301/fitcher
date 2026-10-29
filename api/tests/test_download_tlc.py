from io import BytesIO
import os
import stat

import duckdb
import pytest

from scripts import download_tlc


ZONE_CSV = ('LocationID,Borough,Zone,service_zone\n' + ''.join(
    f'{location_id},Manhattan,Example {location_id},Yellow Zone\n'
    for location_id in range(1, 266)
)).encode()


@pytest.fixture
def parquet_bytes(tmp_path):
    path = tmp_path / "fixture.parquet"
    with duckdb.connect() as connection:
        connection.sql("""
            SELECT 'HV0003' AS hvfhs_license_num,
                   TIMESTAMP '2024-03-01 12:00:00' AS pickup_datetime,
                   1 AS PULocationID, 1 AS DOLocationID,
                   10.25 AS base_passenger_fare
        """).write_parquet(str(path))
    return path.read_bytes()


def response(body, length=None):
    stream = BytesIO(body)
    stream.headers = {"Content-Length": str(len(body) if length is None else length)}
    return stream


@pytest.mark.parametrize("month", ["2024-03", "2019-02"])
def test_supported_month_is_accepted(month):
    assert download_tlc.parse_month(month) == month


@pytest.mark.parametrize("month", ["2019-01", "2024-13", "2024-00", "2024-3", "../2024-03"])
def test_invalid_month_cannot_form_download_path(month):
    with pytest.raises(ValueError):
        download_tlc.parse_month(month)


def test_download_publishes_valid_parquet_atomically(tmp_path, parquet_bytes, monkeypatch):
    destination = tmp_path / "trips.parquet"
    monkeypatch.setattr(download_tlc, "urlopen", lambda *a, **kw: response(parquet_bytes))
    assert download_tlc.download_file("https://example.invalid/trips", destination) == destination
    assert destination.read_bytes() == parquet_bytes
    assert list(tmp_path.glob("*.part")) == []


def test_repeat_download_reuses_valid_file_without_network(tmp_path, monkeypatch):
    destination = tmp_path / "zones.csv"
    destination.write_bytes(ZONE_CSV)

    def unexpected_request(*args, **kwargs):
        pytest.fail("Valid cached inputs should not be downloaded again")

    monkeypatch.setattr(download_tlc, "urlopen", unexpected_request)
    assert download_tlc.download_file("https://example.invalid/zones", destination) == destination
    assert destination.read_bytes() == ZONE_CSV


def test_truncated_download_is_not_published(tmp_path, monkeypatch):
    destination = tmp_path / "zones.csv"
    monkeypatch.setattr(download_tlc, "urlopen", lambda *a, **kw: response(ZONE_CSV, len(ZONE_CSV) + 10))
    with pytest.raises(ValueError, match="length"):
        download_tlc.download_file("https://example.invalid/zones", destination)
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_wrong_content_is_not_published(tmp_path, monkeypatch):
    destination = tmp_path / "trips.parquet"
    monkeypatch.setattr(download_tlc, "urlopen", lambda *a, **kw: response(b'<html>Not data</html>'))
    with pytest.raises(ValueError, match="Invalid"):
        download_tlc.download_file("https://example.invalid/trips", destination)
    assert list(tmp_path.iterdir()) == []


def test_invalid_existing_file_is_preserved(tmp_path):
    destination = tmp_path / "zones.csv"
    destination.write_text("wrong,header\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid"):
        download_tlc.download_file("https://example.invalid/zones", destination)
    assert destination.read_text(encoding="utf-8") == "wrong,header\n1,2\n"


def test_incomplete_zone_row_is_rejected_and_preserved(tmp_path):
    destination = tmp_path / "zones.csv"
    partial = b'LocationID,Borough,Zone,service_zone\n1,Manhattan\n'
    destination.write_bytes(partial)
    with pytest.raises(ValueError, match="Invalid"):
        download_tlc.download_file("https://example.invalid/zones", destination)
    assert destination.read_bytes() == partial


def test_network_interruption_removes_partial_file(tmp_path, monkeypatch):
    destination = tmp_path / "zones.csv"
    stream = response(ZONE_CSV)
    original_read = stream.read

    def interrupted_read(size):
        if stream.tell():
            raise OSError("Connection interrupted")
        return original_read(10)

    monkeypatch.setattr(stream, "read", interrupted_read)
    monkeypatch.setattr(download_tlc, "urlopen", lambda *a, **kw: stream)
    with pytest.raises(OSError, match="interrupted"):
        download_tlc.download_file("https://example.invalid/zones", destination)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("cached", [False, True])
def test_complete_rows_from_truncated_lookup_are_rejected(tmp_path, monkeypatch, cached):
    destination = tmp_path / "zones.csv"
    partial = b'LocationID,Borough,Zone,service_zone\n1,Manhattan,Example,Yellow Zone\n'
    stream = response(partial)
    stream.headers = {}
    monkeypatch.setattr(download_tlc, "urlopen", lambda *a, **kw: stream)
    if cached:
        destination.write_bytes(partial)
    with pytest.raises(ValueError, match="Invalid"):
        download_tlc.download_file("https://example.invalid/zones", destination)
    if cached:
        assert destination.read_bytes() == partial
    else:
        assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits require Linux/macOS")
def test_published_download_is_readable_by_container_user(tmp_path, monkeypatch):
    destination = tmp_path / "zones.csv"
    monkeypatch.setattr(download_tlc, "urlopen", lambda *a, **kw: response(ZONE_CSV))
    download_tlc.download_file("https://example.invalid/zones", destination)
    assert stat.S_IMODE(destination.stat().st_mode) == 0o644
