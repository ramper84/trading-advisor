from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.retrieval.hybrid_search import ChunkCandidate, lexical_search, reciprocal_rank_fusion


def _candidate(chunk_id, source_name="finnhub_news"):
    return ChunkCandidate(
        chunk_id=chunk_id,
        source_name=source_name,
        symbol="AAPL",
        document_id=f"doc-{chunk_id}",
        reliability_tier=4,
        content="some content",
        published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        url=None,
        section_title=None,
    )


def test_lexical_search_filters_by_symbol_and_query():
    row = (1, "finnhub_news", "AAPL", "doc-1", 4, "Apple beats earnings", None, None, None, {})
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = [row]
    conn.cursor.return_value.__enter__.return_value = cursor

    results = lexical_search("AAPL", "earnings", top_k=8, conn=conn)

    assert len(results) == 1
    assert results[0].chunk_id == 1
    sql, params = cursor.execute.call_args[0]
    assert "content_tsv @@ plainto_tsquery" in sql
    assert params[0] == "AAPL"
    assert params[-1] == 8


def test_reciprocal_rank_fusion_prefers_items_ranked_high_in_both_lists():
    a, b, c = _candidate(1), _candidate(2), _candidate(3)
    semantic = [a, b, c]
    lexical = [b, a, c]

    fused = reciprocal_rank_fusion([semantic, lexical])

    assert [candidate.chunk_id for candidate, _ in fused][0] in (1, 2)
    ids = [candidate.chunk_id for candidate, _ in fused]
    assert set(ids) == {1, 2, 3}


def test_reciprocal_rank_fusion_includes_item_present_in_only_one_list():
    a, b = _candidate(1), _candidate(2)
    fused = reciprocal_rank_fusion([[a], [b]])
    ids = {candidate.chunk_id for candidate, _ in fused}
    assert ids == {1, 2}


def test_reciprocal_rank_fusion_empty_lists():
    assert reciprocal_rank_fusion([[], []]) == []
