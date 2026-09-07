from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.ingest.document import Document, DocumentMetadata
from app.ingest.embedding import (
    CURRENT_EMBEDDING_VERSION,
    content_hash,
    embed_documents,
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
