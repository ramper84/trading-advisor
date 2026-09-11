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
    """Shared by finnhub_news and yfinance_news — both parsers converge on
    the same RawArticle shape, so one normalizer covers either source; only
    catalog_source (passed by the caller) tells them apart."""
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
