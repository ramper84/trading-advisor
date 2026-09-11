"""SEC EDGAR filings -> intermediate records, one per filing Item/section.

Uses SEC's documented submissions API (data.sec.gov), not full-text search:
it returns exactly the per-filing metadata (form type, accession number,
filing date) needed to know what's new since the last poll, ordered by
recency, with no best-effort text search involved.

The section split (split_into_sections) is this source's structural
chunking boundary (articles/s07-03/s07-04): a 10-K's "Item 1A. Risk
Factors" and "Item 7. MD&A" are different topics and should not be
recursively chunked as one undifferentiated blob.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from app.ingest.loaders.http import fetch_json, fetch_text

TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:0>10}.json"
FILING_DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{primary_doc}"

TRACKED_FORMS = {"10-K", "10-Q", "8-K"}

# 10-K/10-Q split into numbered "Item N." sections; 8-Ks use the same
# convention for their event items. This finds section boundaries so
# chunking (Phase 7) can be structural rather than purely recursive.
# Depends on strip_html_boilerplate preserving block boundaries as
# newlines — without a line stop, "up to 120 chars" bleeds straight
# through into the next Item's body text.
_ITEM_HEADING_RE = re.compile(r"(Item\s+\d+[A-Z]?\.[^\n]{0,120})", re.IGNORECASE)
_BLOCK_BOUNDARY_RE = re.compile(r"</(?:p|div|tr|li|h[1-6])>|<br\s*/?>", re.IGNORECASE)


@dataclass
class RawFilingSection:
    symbol: str
    accession_number: str
    form_type: str
    filed_at: datetime
    section_title: str
    text: str
    url: str


def resolve_cik(symbol: str, user_agent: str) -> str:
    """SEC's ticker->CIK mapping — a ~1MB file covering every listed
    company. Fetch once per refresh run and reuse, not once per symbol."""
    data = fetch_json(TICKER_CIK_URL, headers={"User-Agent": user_agent})
    for entry in data.values():
        if entry["ticker"].upper() == symbol.upper():
            return str(entry["cik_str"])
    raise ValueError(f"No CIK found for symbol {symbol!r}")


def fetch_recent_filings(
    cik: str, user_agent: str, since: datetime | None = None
) -> list[dict]:
    """Recent filings metadata for one company, filtered to the tracked
    forms and (if given) to filings after `since` — refresh_worker's own
    "what's new since last poll" cursor."""
    data = fetch_json(SUBMISSIONS_URL.format(cik=cik), headers={"User-Agent": user_agent})
    recent = data["filings"]["recent"]
    filings = []
    for i, form in enumerate(recent["form"]):
        if form not in TRACKED_FORMS:
            continue
        filed_at = datetime.fromisoformat(recent["filingDate"][i])
        if since and filed_at <= since:
            continue
        filings.append(
            {
                "accession_number": recent["accessionNumber"][i],
                "form_type": form,
                "filed_at": filed_at,
                "primary_document": recent["primaryDocument"][i],
            }
        )
    return filings


def filing_document_url(cik: str, accession_number: str, primary_document: str) -> str:
    accession_nodash = accession_number.replace("-", "")
    return FILING_DOCUMENT_URL.format(cik=cik, accession_nodash=accession_nodash, primary_doc=primary_document)


def fetch_filing_document(cik: str, accession_number: str, primary_document: str, user_agent: str) -> str:
    url = filing_document_url(cik, accession_number, primary_document)
    return fetch_text(url, headers={"User-Agent": user_agent})


def strip_html_boilerplate(html_text: str) -> str:
    """Cheap boilerplate strip — tags and repeated whitespace only. Full
    layout-aware extraction (articles/s06-03's hi_res discussion) is
    unnecessary here: filings are digitally generated, never scanned.

    Block-level tag ends become newlines BEFORE the remaining tags are
    stripped, so each heading/paragraph keeps its own line — that line
    boundary is what _ITEM_HEADING_RE relies on to stop a heading match at
    the actual end of the heading, not 120 characters into the next Item.
    """
    text = _BLOCK_BOUNDARY_RE.sub("\n", html_text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]*\n+", "\n", text)
    return text.strip()


def split_into_sections(text: str) -> list[tuple[str, str]]:
    """Split at each 'Item N.' heading. Falls back to a single 'Full
    filing' section when no heading is detected (a short 8-K, say)."""
    matches = list(_ITEM_HEADING_RE.finditer(text))
    if not matches:
        return [("Full filing", text)]

    sections = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        title = match.group(1).strip()
        body = text[start:end].strip()
        if body:
            sections.append((title, body))
    return sections


def parse_filing(
    symbol: str,
    accession_number: str,
    form_type: str,
    filed_at: datetime,
    raw_html: str,
    url: str,
) -> list[RawFilingSection]:
    """One filing -> one RawFilingSection per Item — the intermediate
    representation normalizers/canonical.py converts to Document."""
    cleaned = strip_html_boilerplate(raw_html)
    return [
        RawFilingSection(
            symbol=symbol,
            accession_number=accession_number,
            form_type=form_type,
            filed_at=filed_at,
            section_title=title,
            text=text,
            url=url,
        )
        for title, text in split_into_sections(cleaned)
    ]
