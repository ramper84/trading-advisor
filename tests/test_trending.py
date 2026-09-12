from datetime import datetime, timezone

from app.analysis.trending import percent_change, rank_by_movement
from app.retrieval.sql_retriever import ObservationRow

NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)


def _observation(symbol, price, previous_close, volume=1_000_000.0):
    return ObservationRow(
        symbol, NOW, price, previous_close, volume, price, price, price,
        price, price, price, price, 1_000_000_000.0, "yfinance_quotes",
    )


def test_percent_change_computes_correctly():
    obs = _observation("AAPL", 110.0, 100.0)
    assert percent_change(obs) == 10.0


def test_percent_change_negative_move():
    obs = _observation("AAPL", 90.0, 100.0)
    assert percent_change(obs) == -10.0


def test_percent_change_none_when_no_previous_close():
    obs = _observation("AAPL", 110.0, None)
    assert percent_change(obs) is None


def test_percent_change_none_when_previous_close_zero():
    obs = _observation("AAPL", 110.0, 0.0)
    assert percent_change(obs) is None


def test_rank_by_movement_sorts_by_absolute_change_descending():
    observations = {
        "AAPL": _observation("AAPL", 101.0, 100.0),   # +1%
        "TSLA": _observation("TSLA", 80.0, 100.0),     # -20%
        "MSFT": _observation("MSFT", 105.0, 100.0),    # +5%
    }
    ranked = rank_by_movement(observations)
    assert [e.symbol for e in ranked] == ["TSLA", "MSFT", "AAPL"]


def test_rank_by_movement_symbol_with_no_previous_close_sorts_last():
    observations = {
        "AAPL": _observation("AAPL", 101.0, 100.0),
        "NEWCO": _observation("NEWCO", 50.0, None),
    }
    ranked = rank_by_movement(observations)
    assert ranked[-1].symbol == "NEWCO"
    assert ranked[-1].percent_change is None


def test_rank_by_movement_empty():
    assert rank_by_movement({}) == []
