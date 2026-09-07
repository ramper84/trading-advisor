"""Converts each unstructured parser's intermediate representation into
Document(content, metadata) — articles/s06-03's contract. Downstream
chunking (Phase 7) and embedding (Phase 8) operate only on Document, never
on a parser-specific type.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.ingest.catalog import CatalogSource
from app.ingest.document import Document, DocumentMetadata
from app.ingest.parsers.edgar_parser import RawFilingSection
from app.ingest.parsers.news_parser import RawArticle
from app.ingest.parsers.reddit_parser import RawRedditPost


def from_filing_section(section: RawFilingSection, catalog_source: CatalogSource) -> Document:
    return Document(
        content=section.text,
        metadata=DocumentMetadata(
            source_name=catalog_source.name,
            symbol=section.symbol,
            reliability_tier=catalog_source.reliability_tier,
            ingested_at=datetime.now(timezone.utc),
            document_id=f"{section.accession_number}#{section.section_title}",
            published_at=section.filed_at,
            url=section.url,
            section_title=section.section_title,
            extra={"form_type": section.form_type, "accession_number": section.accession_number},
        ),
    )


def from_article(article: RawArticle, catalog_source: CatalogSource) -> Document:
    return Document(
        content=f"{article.headline}\n\n{article.summary}",
        metadata=DocumentMetadata(
            source_name=catalog_source.name,
            symbol=article.symbol,
            reliability_tier=catalog_source.reliability_tier,
            ingested_at=datetime.now(timezone.utc),
            document_id=article.article_id,
            published_at=article.published_at,
            url=article.url,
            extra={"outlet": article.source},
        ),
    )


def from_reddit_post(post: RawRedditPost, catalog_source: CatalogSource) -> Document:
    return Document(
        content=f"{post.title}\n\n{post.body}".strip(),
        metadata=DocumentMetadata(
            source_name=catalog_source.name,
            symbol=post.symbol,
            reliability_tier=catalog_source.reliability_tier,
            ingested_at=datetime.now(timezone.utc),
            document_id=post.post_id,
            published_at=post.created_at,
            url=post.url,
            extra={"subreddit": post.subreddit, "score": post.score},
        ),
    )
