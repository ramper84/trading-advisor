from unittest.mock import MagicMock

from app.analysis.analysis_store import add_to_monitor, insert_analysis, remove_from_monitor
from app.schemas import AnalysisSynthesis, Citation, GuardedAnalysis


def _synthesis():
    return AnalysisSynthesis(
        stance="BULLISH", confidence=0.8, rationale="raw model rationale",
        citations=[Citation(chunk_id=1, claim="strong quarter")],
    )


def _guarded():
    return GuardedAnalysis(
        stance="BULLISH", confidence=0.7, quality_status="grounded", rationale="guarded rationale",
        resolved_citations=[1], dangling_citations=[], ungrounded_figures=[], reliability_rule_passed=True,
    )


def test_insert_analysis_persists_guarded_values_not_raw_synthesis():
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = (42,)
    conn.cursor.return_value.__enter__.return_value = cursor

    result_id = insert_analysis("AAPL", "why did AAPL move", _synthesis(), _guarded(), conn=conn)

    assert result_id == 42
    sql, params = cursor.execute.call_args[0]
    assert "INSERT INTO analyses" in sql
    assert params[0] == "AAPL"
    assert params[1] == "why did AAPL move"
    assert params[2] == "BULLISH"  # guarded.stance, not synthesis.stance
    assert params[3] == 0.7  # guarded.confidence, not synthesis.confidence (0.8)
    assert params[4] == "grounded"
    assert params[5] == "guarded rationale"


def test_insert_analysis_serializes_citations_as_json():
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)
    conn.cursor.return_value.__enter__.return_value = cursor

    insert_analysis("AAPL", "q", _synthesis(), _guarded(), conn=conn)

    _, params = cursor.execute.call_args[0]
    assert '"chunk_id": 1' in params[6]
    assert '"claim": "strong quarter"' in params[6]


def test_add_to_monitor_upserts():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    add_to_monitor("AAPL", thesis="long-term hold", conn=conn)

    sql, params = cursor.execute.call_args[0]
    assert "ON CONFLICT (symbol) DO UPDATE" in sql
    assert params == ("AAPL", "long-term hold")


def test_add_to_monitor_none_thesis_preserves_existing():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    add_to_monitor("AAPL", conn=conn)

    sql, params = cursor.execute.call_args[0]
    assert "COALESCE(EXCLUDED.thesis, monitored_symbols.thesis)" in sql
    assert params == ("AAPL", None)


def test_remove_from_monitor_soft_deletes():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    remove_from_monitor("AAPL", conn=conn)

    sql, params = cursor.execute.call_args[0]
    assert "SET active = false" in sql
    assert params == ("AAPL",)
