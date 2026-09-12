from datetime import datetime, timezone
from unittest.mock import patch

from app.analysis.discovery import run_discovery
from app.retrieval.sql_retriever import GeneralNewsItemRow
from app.schemas import DiscoverySuggestions, SuggestedCompany


def _article(article_id=1, reliability_tier=4):
    return GeneralNewsItemRow(
        id=article_id, source_name="el_economista_news", reliability_tier=reliability_tier,
        headline="h", summary="s", url="https://x.mx/a", published_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
    )


def test_run_discovery_empty_articles_returns_empty_without_calling_actor():
    with patch("app.analysis.discovery.generate_discovery_suggestions") as mock_generate:
        result = run_discovery([])
    assert result == []
    mock_generate.assert_not_called()


@patch("app.analysis.discovery.discovery_guard.check_symbol_identity", return_value=True)
@patch("app.analysis.discovery.discovery_guard.resolve_symbol", return_value={"longName": "Apple Inc."})
@patch("app.analysis.discovery.generate_discovery_suggestions")
def test_run_discovery_accepts_clean_suggestion_first_try(mock_generate, mock_resolve, mock_identity):
    suggestion = SuggestedCompany(symbol="AAPL", company_name="Apple Inc.", reasoning="r", source_article_ids=[1])
    mock_generate.return_value = DiscoverySuggestions(suggestions=[suggestion])

    result = run_discovery([_article(1)])

    assert result == [suggestion]
    mock_generate.assert_called_once()


@patch("app.analysis.discovery.discovery_guard.check_symbol_identity")
@patch("app.analysis.discovery.discovery_guard.resolve_symbol")
@patch("app.analysis.discovery.generate_discovery_suggestions")
def test_run_discovery_retries_once_with_feedback_then_accepts(mock_generate, mock_resolve, mock_identity):
    bad = SuggestedCompany(symbol="PEMEX.MX", company_name="Pemex", reasoning="r", source_article_ids=[1])
    good = SuggestedCompany(symbol="AAPL", company_name="Apple Inc.", reasoning="r2", source_article_ids=[1])
    mock_generate.side_effect = [
        DiscoverySuggestions(suggestions=[bad]),
        DiscoverySuggestions(suggestions=[good]),
    ]
    # first attempt's symbol fails to resolve at all; retry's resolves and matches
    mock_resolve.side_effect = [None, {"longName": "Apple Inc."}]
    mock_identity.return_value = True

    result = run_discovery([_article(1)])

    assert result == [good]
    assert mock_generate.call_count == 2
    # the retry call must include feedback naming what was wrong
    second_call_kwargs = mock_generate.call_args_list[1]
    assert "feedback" in second_call_kwargs.kwargs
    assert "PEMEX.MX" in second_call_kwargs.kwargs["feedback"]


@patch("app.analysis.discovery.discovery_guard.resolve_symbol", return_value=None)
@patch("app.analysis.discovery.generate_discovery_suggestions")
def test_run_discovery_drops_still_failing_suggestion_after_max_retries(mock_generate, mock_resolve):
    bad = SuggestedCompany(symbol="PEMEX.MX", company_name="Pemex", reasoning="r", source_article_ids=[1])
    mock_generate.return_value = DiscoverySuggestions(suggestions=[bad])

    result = run_discovery([_article(1)])

    assert result == []
    assert mock_generate.call_count == 2  # one original call + one retry, per MAX_RETRIES=1


@patch("app.analysis.discovery.discovery_guard.check_symbol_identity", return_value=False)
@patch("app.analysis.discovery.discovery_guard.resolve_symbol", return_value={"longName": "Pioneer Emerging Markets Equity Fund"})
@patch("app.analysis.discovery.generate_discovery_suggestions")
def test_run_discovery_drops_suggestion_whose_symbol_resolves_to_the_wrong_company(mock_generate, mock_resolve, mock_identity):
    """The real live case (2026-09-12): PEMEX resolves to a real,
    tradeable instrument, just not to Petróleos Mexicanos."""
    bad = SuggestedCompany(symbol="PEMEX", company_name="Petróleos Mexicanos", reasoning="r", source_article_ids=[1])
    mock_generate.return_value = DiscoverySuggestions(suggestions=[bad])

    result = run_discovery([_article(1)])

    assert result == []
    assert mock_generate.call_count == 2


@patch("app.analysis.discovery.discovery_guard.resolve_symbol")
@patch("app.analysis.discovery.discovery_guard.check_symbol_identity")
@patch("app.analysis.discovery.generate_discovery_suggestions")
def test_run_discovery_keeps_already_passing_suggestions_across_a_retry(
    mock_generate, mock_identity, mock_resolve
):
    """Regression guard (2026-09-12, live verification): a real run had
    2 good suggestions + 1 bad one on the first attempt; retrying the
    WHOLE batch discarded the 2 good ones, and the retry's own output
    happened to fail too, going from 2 useful suggestions to 0. Already-
    passing suggestions must survive a retry triggered by a DIFFERENT
    suggestion failing."""
    good_1 = SuggestedCompany(symbol="VWAGY", company_name="Volkswagen AG", reasoning="r1", source_article_ids=[1])
    bad = SuggestedCompany(symbol="PEMEX", company_name="Petróleos Mexicanos", reasoning="r2", source_article_ids=[1])
    good_2_retry = SuggestedCompany(symbol="NFLX", company_name="Netflix", reasoning="r3", source_article_ids=[1])
    mock_generate.side_effect = [
        DiscoverySuggestions(suggestions=[good_1, bad]),
        DiscoverySuggestions(suggestions=[good_2_retry]),  # the retry doesn't re-suggest PEMEX or VWAGY
    ]
    mock_resolve.return_value = {"longName": "resolved"}
    mock_identity.side_effect = [True, False, True]  # good_1 ok, bad fails, retry's good_2 ok

    result = run_discovery([_article(1)])

    assert {s.symbol for s in result} == {"VWAGY", "NFLX"}
    assert mock_generate.call_count == 2


@patch("app.analysis.discovery.discovery_guard.check_symbol_identity", return_value=True)
@patch("app.analysis.discovery.discovery_guard.resolve_symbol", return_value={"longName": "Apple Inc."})
@patch("app.analysis.discovery.generate_discovery_suggestions")
def test_run_discovery_no_suggestions_is_a_valid_empty_result(mock_generate, mock_resolve, mock_identity):
    mock_generate.return_value = DiscoverySuggestions(suggestions=[])
    result = run_discovery([_article(1)])
    assert result == []
    mock_generate.assert_called_once()
