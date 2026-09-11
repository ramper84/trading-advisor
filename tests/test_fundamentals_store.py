from datetime import date
from unittest.mock import MagicMock

from app.ingest.fundamentals_store import upsert_fundamentals
from app.ingest.parsers.fundamentals_parser import FundamentalsRecord


def test_upsert_fundamentals_writes_expected_params():
    record = FundamentalsRecord(
        symbol="AAPL",
        snapshot_date=date(2026, 6, 30),
        pe_ratio=36.09,
        pb_ratio=44.37,
        ev_ebitda=27.53,
        dividend_yield=0.34,
        fcf_yield=0.0226,
        market_cap=4_766_021_713_920.0,
        revenue=50_000_000_000.0,
        net_income=109_417_000_000.0,
        eps=1.85,
        gross_margin=0.6,
        operating_margin=0.4,
        debt_to_equity=1.67,
        roe=1.82,
        source_name="yfinance_fundamentals",
        reliability_tier=4,
    )
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    upsert_fundamentals(record, conn=conn)

    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args[0]
    assert "ON CONFLICT (symbol, snapshot_date) DO UPDATE" in sql
    assert params[0] == "AAPL"
    assert params[1] == date(2026, 6, 30)
