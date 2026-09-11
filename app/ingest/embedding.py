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
import tiktoken
from psycopg.types.json import Json

from app.config import get_settings
from app.ingest.document import Document
from app.services.db import get_connection

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
PREPROCESSING_ID = "v1"  # bump when the chunking/cleaning strategy changes

# OpenAI's real limits are 8191 tokens per input and 300,000 per request —
# both leave headroom below the hard limit. Live-confirmed 2026-09-10: a
# real 10-K's "structural by Item" sections (edgar_parser.split_into_sections)
# still add up past 300k tokens in aggregate, and Item 7 (MD&A) alone can
# exceed 8191 on its own — this project's own "structural chunking" was
# never followed by the recursive within-Item sub-split PLAYBOOK.md's Phase
# 7 named as a follow-up if a section was "still too large." Truncating and
# batching here is the stopgap that keeps ingestion from crashing; real
# recursive sub-chunking is that still-open follow-up, not done here.
MAX_TOKENS_PER_INPUT = 8000
MAX_TOKENS_PER_BATCH = 250_000
_ENCODING = tiktoken.get_encoding("cl100k_base")  # text-embedding-3-small's tokenizer


def _truncate_to_token_limit(text: str, max_tokens: int = MAX_TOKENS_PER_INPUT) -> str:
    tokens = _ENCODING.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return _ENCODING.decode(tokens[:max_tokens])


def _batch_by_token_budget(texts: list[str], max_tokens_per_batch: int = MAX_TOKENS_PER_BATCH) -> list[list[str]]:
    batches: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0
    for text in texts:
        token_count = len(_ENCODING.encode(text))
        if current and current_tokens + token_count > max_tokens_per_batch:
            batches.append(current)
            current = []
            current_tokens = 0
        current.append(text)
        current_tokens += token_count
    if current:
        batches.append(current)
    return batches


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
    """Batched calls to the embedding model, never one call per chunk — but
    batched respecting OpenAI's own per-input and per-request token limits,
    since a single ingest run (e.g. one filing's worth of Document sections)
    can exceed both."""
    if not texts:
        return []
    client = openai.OpenAI(api_key=api_key or get_settings().openai_api_key)
    truncated = [_truncate_to_token_limit(text) for text in texts]
    embeddings: list[list[float]] = []
    for batch in _batch_by_token_budget(truncated):
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        embeddings.extend(item.embedding for item in response.data)
    return embeddings


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
