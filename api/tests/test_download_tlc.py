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


@pytest.mark.parametrize("column,expression", [
    ("hvfhs_license_num", "123"),
    ("pickup_datetime", "'not-a-timestamp'"),
    ("PULocationID", "1.5"),
    ("DOLocationID", "'1'"),
    ("base_passenger_fare", "'10.25'"),
])
def test_incompatible_parquet_types_are_rejected(tmp_path, column, expression):
    columns = {
        "hvfhs_license_num": "'HV0003'", "pickup_datetime": "TIMESTAMP '2024-03-01'",
        "PULocationID": "1", "DOLocationID": "2", "base_passenger_fare": "10.25",
    }
    columns[column] = expression
    path = tmp_path / "wrong-type.parquet"
    with duckdb.connect() as connection:
        connection.sql("SELECT " + ", ".join(f"{value} AS {name}" for name, value in columns.items())).write_parquet(str(path))
    with pytest.raises(ValueError, match="Invalid TLC input"):
        download_tlc.validate_file(path, ".parquet")


@pytest.mark.parametrize("timestamp_type,fare_type", [("DATE", "DOUBLE"), ("TIMESTAMP_NS", "DECIMAL(18,2)")])
def test_compatible_parquet_types_are_accepted(tmp_path, timestamp_type, fare_type):
    path = tmp_path / "compatible.parquet"
    with duckdb.connect() as connection:
        connection.sql(f"""
            SELECT 'HV0003' AS hvfhs_license_num,
                   CAST('2024-03-01' AS {timestamp_type}) AS pickup_datetime,
                   1::SMALLINT AS PULocationID, 2::BIGINT AS DOLocationID,
                   CAST(10.25 AS {fare_type}) AS base_passenger_fare
        """).write_parquet(str(path))
    download_tlc.validate_file(path, ".parquet")


def test_download_cli_publishes_both_inputs(tmp_path, parquet_bytes, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["download_tlc", "--data-dir", str(tmp_path)])
    bodies = {"fhvhv_tripdata_2024-03.parquet": parquet_bytes, "taxi_zone_lookup.csv": ZONE_CSV}
    monkeypatch.setattr(download_tlc, "urlopen", lambda url, **kwargs: response(bodies[url.rsplit("/", 1)[1]]))
    assert download_tlc.main() == 0
    assert (tmp_path / "fhvhv_tripdata_2024-03.parquet").read_bytes() == parquet_bytes
    assert (tmp_path / "taxi_zone_lookup.csv").read_bytes() == ZONE_CSV
    assert "Saved taxi_zone_lookup.csv" in capsys.readouterr().out


def test_download_cli_returns_failure_for_invalid_cached_input(tmp_path, monkeypatch, capsys):
    path = tmp_path / "fhvhv_tripdata_2024-03.parquet"
    path.write_bytes(b"invalid")
    monkeypatch.setattr("sys.argv", ["download_tlc", "--data-dir", str(tmp_path)])
    assert download_tlc.main() == 1
    assert "Invalid TLC input" in capsys.readouterr().err
    assert path.read_bytes() == b"invalid"


def test_download_cli_rejects_invalid_month_before_io(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["download_tlc", "--data-dir", str(tmp_path), "--month", "../2024-03"])
    with pytest.raises(SystemExit) as error:
        download_tlc.main()
    assert error.value.code == 2
    assert "--month" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("valid_winner", [True, False])
def test_concurrent_publication_never_overwrites_the_winner(tmp_path, monkeypatch, valid_winner):
    destination = tmp_path / "zones.csv"
    winner = ZONE_CSV.replace(b"Example 1,", b"Updated zone,") if valid_winner else b"invalid"

    def concurrent_response(*args, **kwargs):
        destination.write_bytes(winner)
        return response(ZONE_CSV)

    monkeypatch.setattr(download_tlc, "urlopen", concurrent_response)
    if valid_winner:
        assert download_tlc.download_file("https://example.invalid/zones", destination) == destination
    else:
        with pytest.raises(ValueError, match="Invalid TLC input"):
            download_tlc.download_file("https://example.invalid/zones", destination)
    assert destination.read_bytes() == winner
    assert list(tmp_path.glob("*.part")) == []


def test_unsupported_atomic_publication_fails_without_final_file(tmp_path, monkeypatch):
    destination = tmp_path / "zones.csv"
    monkeypatch.setattr(download_tlc, "urlopen", lambda *args, **kwargs: response(ZONE_CSV))

    def unsupported_link(*args, **kwargs):
        raise OSError("Hard links unsupported")

    monkeypatch.setattr(os, "link", unsupported_link)
    with pytest.raises(OSError, match="atomic"):
        download_tlc.download_file("https://example.invalid/zones", destination)
    assert list(tmp_path.iterdir()) == []
