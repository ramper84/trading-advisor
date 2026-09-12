from datetime import datetime, timezone
from unittest.mock import patch

from app.guardrails.discovery_guard import (
    STRONG_RELIABILITY_TIER_FLOOR,
    check_article_citations,
    check_reliability,
    check_symbol_identity,
    resolve_symbol,
    review,
)
from app.retrieval.sql_retriever import GeneralNewsItemRow
from app.schemas import SuggestedCompany, SymbolIdentityVerdict


def _article(article_id, reliability_tier=4):
    return GeneralNewsItemRow(
        id=article_id, source_name="el_economista_news", reliability_tier=reliability_tier,
        headline="h", summary="s", url="https://x.mx/a", published_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
    )


def _suggestion(symbol="AAPL", company_name="Apple Inc.", source_article_ids=(1,)):
    return SuggestedCompany(symbol=symbol, company_name=company_name, reasoning="r", source_article_ids=list(source_article_ids))


def test_check_article_citations_splits_resolved_and_dangling():
    resolved, dangling = check_article_citations(_suggestion(source_article_ids=[1, 99]), article_ids={1, 2})
    assert resolved == [1]
    assert dangling == [99]


@patch("app.guardrails.discovery_guard.market_data.get_instrument_info")
def test_resolve_symbol_returns_info_for_real_symbol(mock_info):
    mock_info.return_value = {"symbol": "AAPL", "quoteType": "EQUITY", "longName": "Apple Inc."}
    result = resolve_symbol("AAPL")
    assert result is not None
    assert result["longName"] == "Apple Inc."


@patch("app.guardrails.discovery_guard.market_data.get_instrument_info")
def test_resolve_symbol_none_for_bogus_symbol(mock_info):
    """Matches the real live behavior confirmed 2026-09-12: yfinance
    returns a near-empty dict for a bogus/non-equity symbol, not an
    exception."""
    mock_info.return_value = {"trailingPegRatio": None}
    assert resolve_symbol("PEMEX.MX") is None


@patch("app.guardrails.discovery_guard.market_data.get_instrument_info")
def test_resolve_symbol_none_on_exception(mock_info):
    mock_info.side_effect = RuntimeError("network error")
    assert resolve_symbol("AAPL") is None


@patch("app.guardrails.discovery_guard.verify_symbol_identity")
def test_check_symbol_identity_true_when_judge_says_matches(mock_verify):
    mock_verify.return_value = SymbolIdentityVerdict(matches=True, reason="same airline, legal vs brand name")
    assert check_symbol_identity("Volaris", {"longName": "Controladora Vuela Compañía de Aviación, S.A.B. de C.V."}) is True


@patch("app.guardrails.discovery_guard.verify_symbol_identity")
def test_check_symbol_identity_false_when_judge_says_no_match(mock_verify):
    """Matches the real live case (2026-09-12): PEMEX resolves to an
    unrelated mutual fund, not Petróleos Mexicanos."""
    mock_verify.return_value = SymbolIdentityVerdict(matches=False, reason="unrelated mutual fund")
    assert check_symbol_identity("Petróleos Mexicanos", {"longName": "Pioneer Series Trust XIV - Pioneer Emerging Markets Equity Fund"}) is False


def test_check_symbol_identity_false_when_resolved_info_has_no_name():
    assert check_symbol_identity("Apple Inc.", {}) is False


def test_check_reliability_true_when_a_resolved_article_clears_the_floor():
    articles_by_id = {1: _article(1, reliability_tier=STRONG_RELIABILITY_TIER_FLOOR)}
    assert check_reliability([1], articles_by_id) is True


def test_check_reliability_false_when_no_resolved_article_clears_the_floor():
    articles_by_id = {1: _article(1, reliability_tier=STRONG_RELIABILITY_TIER_FLOOR - 1)}
    assert check_reliability([1], articles_by_id) is False


def test_check_reliability_false_when_resolved_is_empty():
    assert check_reliability([], {}) is False


@patch("app.guardrails.discovery_guard.check_symbol_identity", return_value=True)
@patch("app.guardrails.discovery_guard.resolve_symbol", return_value={"longName": "Apple Inc."})
def test_review_passes_clean_suggestion(mock_resolve, mock_identity):
    articles_by_id = {1: _article(1)}
    verdict = review(_suggestion(source_article_ids=[1]), articles_by_id)
    assert verdict.passed is True
    assert verdict.dangling_article_ids == []
    assert verdict.reason == ""


@patch("app.guardrails.discovery_guard.check_symbol_identity", return_value=True)
@patch("app.guardrails.discovery_guard.resolve_symbol", return_value={"longName": "Apple Inc."})
def test_review_fails_on_dangling_citation(mock_resolve, mock_identity):
    articles_by_id = {1: _article(1)}
    verdict = review(_suggestion(source_article_ids=[1, 99]), articles_by_id)
    assert verdict.passed is False
    assert 99 in verdict.dangling_article_ids
    assert "99" in verdict.reason


@patch("app.guardrails.discovery_guard.resolve_symbol", return_value=None)
def test_review_fails_on_unresolved_symbol_without_calling_identity_judge(mock_resolve):
    articles_by_id = {1: _article(1)}
    with patch("app.guardrails.discovery_guard.check_symbol_identity") as mock_identity:
        verdict = review(_suggestion(symbol="PEMEX.MX", source_article_ids=[1]), articles_by_id)
        mock_identity.assert_not_called()  # cheap check excludes first; no reason to spend the judge call
    assert verdict.passed is False
    assert "PEMEX.MX" in verdict.reason


@patch("app.guardrails.discovery_guard.check_symbol_identity", return_value=False)
@patch("app.guardrails.discovery_guard.resolve_symbol", return_value={"longName": "Pioneer Emerging Markets Equity Fund"})
def test_review_fails_when_symbol_resolves_but_identity_does_not_match(mock_resolve, mock_identity):
    """The real live case (2026-09-12): PEMEX resolves to something real
    but not to Petróleos Mexicanos."""
    articles_by_id = {1: _article(1)}
    verdict = review(_suggestion(symbol="PEMEX", company_name="Petróleos Mexicanos", source_article_ids=[1]), articles_by_id)
    assert verdict.passed is False
    assert verdict.symbol_resolved is True
    assert verdict.symbol_identity_matched is False
    assert "PEMEX" in verdict.reason


@patch("app.guardrails.discovery_guard.check_symbol_identity", return_value=True)
@patch("app.guardrails.discovery_guard.resolve_symbol", return_value={"longName": "Apple Inc."})
def test_review_fails_on_low_reliability(mock_resolve, mock_identity):
    articles_by_id = {1: _article(1, reliability_tier=1)}
    verdict = review(_suggestion(source_article_ids=[1]), articles_by_id)
    assert verdict.passed is False
    assert "reliability" in verdict.reason
