from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.retrieval.vector_retriever import retrieve, semantic_search

NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


def _semantic_row(chunk_id, distance, source_name="sec_edgar_filings", published_at=None):
    return (
        chunk_id,
        source_name,
        "AAPL",
        f"doc-{chunk_id}",
        4,
        "some retrieved content",
        published_at,
        None,
        None,
        {},
        distance,
    )


def _lexical_row(chunk_id, source_name="finnhub_news", published_at=None):
    return (chunk_id, source_name, "AAPL", f"doc-{chunk_id}", 4, "some retrieved content", published_at, None, None, {})


def test_semantic_search_orders_by_cosine_distance():
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = [_semantic_row(1, 0.12), _semantic_row(2, 0.30)]
    conn.cursor.return_value.__enter__.return_value = cursor

    results = semantic_search("AAPL", [0.1] * 1536, top_k=8, conn=conn)

    assert len(results) == 2
    assert results[0][1] == 0.12
    sql, params = cursor.execute.call_args[0]
    assert "embedding <=> %s" in sql
    assert params[1] == "AAPL"


@patch("app.retrieval.vector_retriever.get_settings")
@patch("app.retrieval.vector_retriever.embed_texts")
@patch("app.retrieval.vector_retriever.lexical_search")
@patch("app.retrieval.vector_retriever.semantic_search")
def test_retrieve_flags_low_confidence_above_distance_threshold(
    mock_semantic, mock_lexical, mock_embed, mock_settings
):
    mock_settings.return_value = Settings(vector_top_k=8, vector_distance_threshold=0.35, hybrid_search_enabled=True)
    mock_embed.return_value = [[0.1] * 1536]
    candidate_row = _semantic_row(1, 0.9)
    from app.retrieval.hybrid_search import ChunkCandidate

    candidate = ChunkCandidate(1, "sec_edgar_filings", "AAPL", "doc-1", 4, "content", None, None, None, {})
    mock_semantic.return_value = [(candidate, 0.9)]
    mock_lexical.return_value = []

    result = retrieve("AAPL", "why did AAPL move", conn=MagicMock(), now=NOW)

    assert result.low_confidence is True
    assert result.best_distance == 0.9


@patch("app.retrieval.vector_retriever.get_settings")
@patch("app.retrieval.vector_retriever.embed_texts")
@patch("app.retrieval.vector_retriever.lexical_search")
@patch("app.retrieval.vector_retriever.semantic_search")
def test_retrieve_confident_when_within_threshold(mock_semantic, mock_lexical, mock_embed, mock_settings):
    mock_settings.return_value = Settings(vector_top_k=8, vector_distance_threshold=0.35, hybrid_search_enabled=True)
    mock_embed.return_value = [[0.1] * 1536]
    from app.retrieval.hybrid_search import ChunkCandidate

    candidate = ChunkCandidate(1, "sec_edgar_filings", "AAPL", "doc-1", 4, "content", None, None, None, {})
    mock_semantic.return_value = [(candidate, 0.1)]
    mock_lexical.return_value = [candidate]

    result = retrieve("AAPL", "why did AAPL move", conn=MagicMock(), now=NOW)

    assert result.low_confidence is False
    assert len(result.candidates) == 1


@patch("app.retrieval.vector_retriever.get_settings")
@patch("app.retrieval.vector_retriever.embed_texts")
@patch("app.retrieval.vector_retriever.lexical_search")
@patch("app.retrieval.vector_retriever.semantic_search")
def test_retrieve_skips_lexical_branch_when_hybrid_disabled(mock_semantic, mock_lexical, mock_embed, mock_settings):
    mock_settings.return_value = Settings(vector_top_k=8, vector_distance_threshold=0.35, hybrid_search_enabled=False)
    mock_embed.return_value = [[0.1] * 1536]
    mock_semantic.return_value = []

    retrieve("AAPL", "why did AAPL move", conn=MagicMock(), now=NOW)

    mock_lexical.assert_not_called()


@patch("app.retrieval.vector_retriever.get_settings")
@patch("app.retrieval.vector_retriever.embed_texts")
@patch("app.retrieval.vector_retriever.semantic_search")
def test_retrieve_low_confidence_when_nothing_retrieved(mock_semantic, mock_embed, mock_settings):
    mock_settings.return_value = Settings(vector_top_k=8, vector_distance_threshold=0.35, hybrid_search_enabled=False)
    mock_embed.return_value = [[0.1] * 1536]
    mock_semantic.return_value = []

    result = retrieve("UNKNOWN", "anything", conn=MagicMock(), now=NOW)

    assert result.low_confidence is True
    assert result.best_distance is None
    assert result.candidates == []
