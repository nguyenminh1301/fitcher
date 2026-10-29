from datetime import date
from decimal import Decimal

import duckdb
import pytest

from scripts.check_tlc import QUERY_DIR, initialize_views


@pytest.fixture
def dataset(tmp_path):
    directory = tmp_path / "driver's samples"
    directory.mkdir()
    with duckdb.connect() as connection:
        connection.sql("""
            SELECT * FROM (VALUES
                ('HV0003', TIMESTAMP '2024-03-01 10:00:00', 1, 2, 10.25),
                ('HV0005', TIMESTAMP '2024-03-01 11:00:00', 1, 2, 999.00),
                ('HV0003', TIMESTAMP '2024-03-01 12:00:00', 2, 1, 20.00),
                ('HV0003', TIMESTAMP '2024-03-04 10:00:00', 999, 1, 5.50)
            ) AS source(hvfhs_license_num, pickup_datetime, PULocationID,
                        DOLocationID, base_passenger_fare)
        """).write_parquet(str(directory / "fhvhv_tripdata_2024-03.parquet"))
    (directory / "taxi_zone_lookup.csv").write_text(
        'LocationID,Borough,Zone,service_zone\n1,Manhattan,Alpha,Yellow Zone\n2,Brooklyn,Beta,Boro Zone\n',
        encoding="utf-8",
    )
    return directory


@pytest.fixture
def connection(dataset):
    with duckdb.connect() as connection:
        initialize_views(connection, dataset, "2024-03")
        yield connection


def test_trips_only_contains_uber_and_preserves_source_columns(connection):
    assert connection.execute("SELECT hvfhs_license_num, count(*) FROM trips GROUP BY 1").fetchall() == [("HV0003", 3)]
    assert {row[0] for row in connection.execute("DESCRIBE trips").fetchall()} == {
        "hvfhs_license_num", "pickup_datetime", "PULocationID", "DOLocationID", "base_passenger_fare",
    }


def test_daily_query_counts_each_uber_trip_once(connection):
    rows = connection.execute((QUERY_DIR / "daily_trip_counts.sql").read_text()).fetchall()
    assert rows == [(date(2024, 3, 1), 2), (date(2024, 3, 4), 1)]


def test_weekly_query_uses_monday_boundaries_and_exact_base_fares(connection):
    rows = connection.execute((QUERY_DIR / "weekly_base_fares.sql").read_text()).fetchall()
    assert rows == [
        (date(2024, 2, 26), 2, Decimal("30.25")),
        (date(2024, 3, 4), 1, Decimal("5.50")),
    ]


def test_zone_join_preserves_unmatched_pickups_and_has_deterministic_ties(connection):
    rows = connection.execute((QUERY_DIR / "top_pickup_zones.sql").read_text()).fetchall()
    assert rows == [
        (1, "Manhattan", "Alpha", 1),
        (2, "Brooklyn", "Beta", 1),
        (999, "Unknown", "Unknown", 1),
    ]


def test_missing_month_fails_before_initializing_views(dataset):
    with duckdb.connect() as connection:
        with pytest.raises(FileNotFoundError, match="2024-04"):
            initialize_views(connection, dataset, "2024-04")
        assert connection.execute("SHOW TABLES").fetchall() == []
