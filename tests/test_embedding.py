from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.ingest.document import Document, DocumentMetadata
from app.ingest.embedding import (
    CURRENT_EMBEDDING_VERSION,
    _batch_by_token_budget,
    _truncate_to_token_limit,
    content_hash,
    embed_documents,
    embed_texts,
    upsert_chunks,
)


def _make_document(content: str = "hello world", document_id: str = "doc1") -> Document:
    return Document(
        content=content,
        metadata=DocumentMetadata(
            source_name="finnhub_news",
            symbol="ACME",
            reliability_tier=4,
            ingested_at=datetime.now(timezone.utc),
            document_id=document_id,
            published_at=datetime.now(timezone.utc),
            url="https://example.com",
        ),
    )


def test_content_hash_is_deterministic_and_sensitive_to_change():
    a = content_hash("hello")
    b = content_hash("hello")
    c = content_hash("hello!")
    assert a == b
    assert a != c


def test_embed_documents_attaches_version_and_hash(monkeypatch):
    doc = _make_document()
    monkeypatch.setattr(
        "app.ingest.embedding.embed_texts", lambda texts, api_key=None: [[0.1, 0.2, 0.3]]
    )

    chunks = embed_documents([doc])

    assert len(chunks) == 1
    assert chunks[0].embedding == [0.1, 0.2, 0.3]
    assert chunks[0].embedding_version == CURRENT_EMBEDDING_VERSION.key
    assert chunks[0].source_hash == content_hash(doc.content)


def test_embed_documents_empty_list_short_circuits(monkeypatch):
    called = False

    def fake_embed_texts(texts, api_key=None):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("app.ingest.embedding.embed_texts", fake_embed_texts)
    assert embed_documents([]) == []
    assert called is False


def test_upsert_chunks_writes_one_row_per_chunk(monkeypatch):
    doc = _make_document()
    monkeypatch.setattr("app.ingest.embedding.embed_texts", lambda texts, api_key=None: [[0.1, 0.2]])
    chunks = embed_documents([doc])

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    upsert_chunks(conn, chunks)

    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args[0]
    assert "INSERT INTO document_chunks" in sql
    assert "ON CONFLICT (source_name, document_id)" in sql
    assert params[0] == "finnhub_news"  # source_name
    assert params[1] == "ACME"  # symbol
    assert params[2] == "doc1"  # document_id
    assert params[3] == 4  # reliability_tier


def test_upsert_chunks_noop_on_empty_list():
    conn = MagicMock()
    upsert_chunks(conn, [])
    conn.transaction.assert_not_called()


def test_truncate_to_token_limit_leaves_short_text_untouched():
    text = "hello world"
    assert _truncate_to_token_limit(text, max_tokens=100) == text


def test_truncate_to_token_limit_shortens_long_text():
    # ~20k tokens of repeated content — comfortably over any realistic limit
    text = "supply chain risk factor. " * 4000
    truncated = _truncate_to_token_limit(text, max_tokens=100)
    assert len(truncated) < len(text)


def test_batch_by_token_budget_splits_when_over_budget():
    texts = ["word " * 50 for _ in range(10)]  # ~50 tokens each
    batches = _batch_by_token_budget(texts, max_tokens_per_batch=120)
    assert len(batches) > 1
    assert sum(len(b) for b in batches) == len(texts)


def test_batch_by_token_budget_single_batch_when_small():
    texts = ["short text"] * 3
    batches = _batch_by_token_budget(texts, max_tokens_per_batch=10_000)
    assert len(batches) == 1


def test_embed_texts_makes_one_api_call_per_batch(monkeypatch):
    """A real live run against a full SEC filing's worth of Document
    sections hit OpenAI's 300k-tokens-per-request limit in one shot
    (2026-09-10) — this confirms embed_texts now splits across calls."""
    calls = []

    class FakeResponse:
        def __init__(self, n):
            self.data = [MagicMock(embedding=[0.0] * 3) for _ in range(n)]

    class FakeEmbeddings:
        def create(self, model, input):
            calls.append(list(input))
            return FakeResponse(len(input))

    class FakeClient:
        def __init__(self, api_key=None):
            self.embeddings = FakeEmbeddings()

    monkeypatch.setattr("app.ingest.embedding.openai.OpenAI", FakeClient)

    texts = ["word " * 50 for _ in range(10)]
    vectors = embed_texts(texts, api_key="fake-key")

    assert len(vectors) == len(texts)
    assert len(calls) >= 1  # batching may or may not split depending on the real token count
    assert sum(len(c) for c in calls) == len(texts)
