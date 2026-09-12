from unittest.mock import MagicMock

from app.analysis.discovery_store import insert_suggestions
from app.schemas import SuggestedCompany


def _suggestion():
    return SuggestedCompany(symbol="AAPL", company_name="Apple Inc.", reasoning="r", source_article_ids=[1, 2])


def test_insert_suggestions_writes_one_row_per_suggestion():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    count = insert_suggestions([_suggestion(), _suggestion()], conn=conn)

    assert count == 2
    assert cursor.execute.call_count == 2
    sql, params = cursor.execute.call_args_list[0][0]
    assert "INSERT INTO suggestions" in sql
    assert params[0] == "AAPL"
    assert '[1, 2]' in params[3]


def test_insert_suggestions_noop_on_empty_list():
    conn = MagicMock()
    assert insert_suggestions([], conn=conn) == 0
    conn.transaction.assert_not_called()
