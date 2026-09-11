from unittest.mock import MagicMock

from app.ingest.instrument_store import upsert_instrument
from app.ingest.parsers.instrument_parser import InstrumentRecord


def test_upsert_instrument_writes_expected_params():
    record = InstrumentRecord(
        symbol="AAPL",
        name="Apple Inc.",
        exchange="NMS",
        currency="USD",
        quote_type="EQUITY",
        sector="Technology",
        industry="Consumer Electronics",
        country="United States",
        source_name="yfinance_quotes",
        reliability_tier=4,
    )
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    upsert_instrument(record, conn=conn)

    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args[0]
    assert "INSERT INTO instruments" in sql
    assert "ON CONFLICT (symbol) DO UPDATE" in sql
    assert params[0] == "AAPL"
    assert params[1] == "Apple Inc."
