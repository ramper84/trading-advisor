"""Embeds canonical Documents and persists them as document_chunks rows
(Axis 3). Every vector records how it was made (articles/s11-05) — model,
dimensions, normalization, preprocessing — so a future model change can
never silently compare incomparable vectors; Phase 10's retrieval filters
on embedding_version for exactly this reason.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import openai
import psycopg
from psycopg.types.json import Json

from app.config import get_settings
from app.ingest.document import Document
from app.services.db import get_connection

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
PREPROCESSING_ID = "v1"  # bump when the chunking/cleaning strategy changes


@dataclass(frozen=True)
class EmbeddingVersion:
    model: str = EMBEDDING_MODEL
    dimensions: int = EMBEDDING_DIMENSIONS
    normalized: bool = True
    preprocessing_id: str = PREPROCESSING_ID

    @property
    def key(self) -> str:
        return f"{self.model}:{self.dimensions}:{self.normalized}:{self.preprocessing_id}"


CURRENT_EMBEDDING_VERSION = EmbeddingVersion()


def content_hash(text: str) -> str:
    """Detects content drift (articles/s11-05): if a source's text changes
    between polls, its hash changes and Phase 9's refresh_worker knows to
    re-embed rather than skip it as already current."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embed_texts(texts: list[str], api_key: str | None = None) -> list[list[float]]:
    """One batched call to the embedding model — never one call per chunk."""
    if not texts:
        return []
    client = openai.OpenAI(api_key=api_key or get_settings().openai_api_key)
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


@dataclass
class EmbeddedChunk:
    document: Document
    embedding: list[float]
    embedding_version: str
    source_hash: str


def embed_documents(documents: list[Document]) -> list[EmbeddedChunk]:
    """Batch-embed canonical Documents, attaching the current embedding
    version and a content hash to each."""
    if not documents:
        return []
    vectors = embed_texts([doc.content for doc in documents])
    return [
        EmbeddedChunk(
            document=doc,
            embedding=vector,
            embedding_version=CURRENT_EMBEDDING_VERSION.key,
            source_hash=content_hash(doc.content),
        )
        for doc, vector in zip(documents, vectors)
    ]


_UPSERT_SQL = """
    INSERT INTO document_chunks (
        source_name, symbol, document_id, reliability_tier,
        content, embedding, embedding_version, source_hash,
        published_at, url, section_title, metadata
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (source_name, document_id) DO UPDATE SET
        content = EXCLUDED.content,
        embedding = EXCLUDED.embedding,
        embedding_version = EXCLUDED.embedding_version,
        source_hash = EXCLUDED.source_hash,
        published_at = EXCLUDED.published_at,
        url = EXCLUDED.url,
        section_title = EXCLUDED.section_title,
        metadata = EXCLUDED.metadata,
        ingested_at = now()
    WHERE document_chunks.source_hash != EXCLUDED.source_hash
"""


def upsert_chunks(conn: psycopg.Connection, chunks: list[EmbeddedChunk]) -> None:
    """One atomic transaction per source-fetch (Phase 8's own requirement):
    all chunks from one ingest run succeed together or none do. The
    (source_name, document_id) unique constraint makes re-ingestion
    idempotent; the source_hash WHERE clause skips a rewrite when the
    content hasn't actually changed since the last poll.
    """
    if not chunks:
        return
    with conn.transaction(), conn.cursor() as cur:
        for chunk in chunks:
            meta = chunk.document.metadata
            cur.execute(
                _UPSERT_SQL,
                (
                    meta.source_name,
                    meta.symbol,
                    meta.document_id,
                    meta.reliability_tier,
                    chunk.document.content,
                    chunk.embedding,
                    chunk.embedding_version,
                    chunk.source_hash,
                    meta.published_at,
                    meta.url,
                    meta.section_title,
                    Json(meta.extra),
                ),
            )


def embed_and_store(documents: list[Document], conn: psycopg.Connection | None = None) -> int:
    """Embed a batch of Documents from one source-fetch and persist them
    atomically. Opens its own connection when the caller (refresh_worker,
    Phase 9) doesn't supply one already in a larger transaction."""
    chunks = embed_documents(documents)
    if conn is not None:
        upsert_chunks(conn, chunks)
    else:
        with get_connection() as owned_conn:
            upsert_chunks(owned_conn, chunks)
    return len(chunks)
