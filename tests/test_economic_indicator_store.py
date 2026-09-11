from datetime import date
from unittest.mock import MagicMock

from app.ingest.economic_indicator_store import upsert_economic_observations
from app.ingest.parsers.economic_data_parser import RawEconomicObservation


def _record():
    return RawEconomicObservation(
        series_id="FEDFUNDS",
        series_name="Federal Funds Effective Rate",
        value=4.33,
        observed_on=date(2026, 8, 1),
        source_name="fred_economic_data",
        country="US",
    )


def test_upsert_economic_observations_writes_expected_params():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    count = upsert_economic_observations([_record()], conn=conn)

    assert count == 1
    sql, params = cursor.execute.call_args[0]
    assert "ON CONFLICT (series_id, observed_on) DO UPDATE" in sql
    assert params[0] == "FEDFUNDS"
    assert params[3] == date(2026, 8, 1)


def test_upsert_economic_observations_noop_on_empty_list():
    conn = MagicMock()
    assert upsert_economic_observations([], conn=conn) == 0
    conn.transaction.assert_not_called()
