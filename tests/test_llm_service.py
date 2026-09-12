from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.analysis.synthesis import EvidenceAggregate
from app.retrieval.sql_retriever import GeneralNewsItemRow
from app.schemas import AnalysisSynthesis, Citation, DiscoverySuggestions, SuggestedCompany, SymbolIdentityVerdict
from app.services.llm_service import (
    generate_discovery_suggestions,
    generate_synthesis,
    render_discovery_prompts,
    render_prompts,
    verify_symbol_identity,
)


def _aggregate(contested=False):
    return EvidenceAggregate(anchor_lean=0.2, strong_low=-0.1, strong_high=0.4, contested=contested, citation_signals=[])


def test_render_prompts_produces_real_content_from_the_actual_templates():
    system_prompt, user_prompt = render_prompts(
        "AAPL", "why did AAPL move", "<market_data symbol=\"AAPL\" />", _aggregate(), low_confidence=False
    )
    assert "BULLISH" in system_prompt
    assert "BEARISH" in system_prompt
    assert "NEUTRAL" in system_prompt
    assert "AAPL" in user_prompt
    assert "anchor_lean: 0.2" in user_prompt
    assert "<market_data" in user_prompt


def test_render_prompts_includes_contested_flag():
    _, user_prompt = render_prompts("AAPL", "q", "<market_data />", _aggregate(contested=True), low_confidence=False)
    assert "contested: True" in user_prompt


@patch("app.services.llm_service._client")
def test_generate_synthesis_uses_primary_model_on_success(mock_client):
    expected = AnalysisSynthesis(stance="BULLISH", confidence=0.8, rationale="Strong evidence.", citations=[Citation(chunk_id=1, claim="x")])
    mock_client.chat.completions.create.return_value = expected

    result = generate_synthesis("AAPL", "why did AAPL move", "<market_data />", _aggregate(), low_confidence=False)

    assert result is expected
    mock_client.chat.completions.create.assert_called_once()
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["response_model"] is AnalysisSynthesis


@patch("app.services.llm_service._client")
def test_generate_synthesis_falls_back_when_primary_raises(mock_client):
    fallback_result = AnalysisSynthesis(stance="NEUTRAL", confidence=0.3, rationale="Fallback.", citations=[])
    mock_client.chat.completions.create.side_effect = [RuntimeError("primary down"), fallback_result]

    result = generate_synthesis("AAPL", "why did AAPL move", "<market_data />", _aggregate(), low_confidence=False)

    assert result is fallback_result
    assert mock_client.chat.completions.create.call_count == 2
    first_call_model = mock_client.chat.completions.create.call_args_list[0].kwargs["model"]
    second_call_model = mock_client.chat.completions.create.call_args_list[1].kwargs["model"]
    assert first_call_model != second_call_model


def _article(article_id=1):
    return GeneralNewsItemRow(
        id=article_id, source_name="el_economista_news", reliability_tier=4,
        headline="ACME sube tras resultados", summary="ACME reportó ingresos récord.",
        url="https://example.mx/a", published_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
    )


def test_render_discovery_prompts_includes_articles():
    system_prompt, user_prompt = render_discovery_prompts([_article()])
    assert "experienced trader" in system_prompt
    assert "ACME sube tras resultados" in user_prompt
    assert 'id="1"' in user_prompt


def test_render_discovery_prompts_includes_feedback_when_given():
    _, user_prompt = render_discovery_prompts([_article()], feedback="Suggestion for XYZ cited article 99, which was not provided.")
    assert "checker rejected" in user_prompt
    assert "article 99" in user_prompt


def test_render_discovery_prompts_omits_feedback_section_when_none():
    _, user_prompt = render_discovery_prompts([_article()], feedback=None)
    assert "checker rejected" not in user_prompt


@patch("app.services.llm_service._client")
def test_generate_discovery_suggestions_uses_primary_model_on_success(mock_client):
    expected = DiscoverySuggestions(suggestions=[SuggestedCompany(symbol="ACME", company_name="ACME Corp", reasoning="Record earnings.", source_article_ids=[1])])
    mock_client.chat.completions.create.return_value = expected

    result = generate_discovery_suggestions([_article()])

    assert result is expected
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["response_model"] is DiscoverySuggestions


@patch("app.services.llm_service._client")
def test_generate_discovery_suggestions_falls_back_when_primary_raises(mock_client):
    fallback_result = DiscoverySuggestions(suggestions=[])
    mock_client.chat.completions.create.side_effect = [RuntimeError("primary down"), fallback_result]

    result = generate_discovery_suggestions([_article()])

    assert result is fallback_result
    assert mock_client.chat.completions.create.call_count == 2


@patch("app.services.llm_service._client")
def test_verify_symbol_identity_uses_fallback_model_as_its_own_primary(mock_client):
    """s11-04's "a different, cheaper model than the generator"
    discipline — this judge's primary is generate_synthesis's fallback."""
    expected = SymbolIdentityVerdict(matches=True, reason="same company")
    mock_client.chat.completions.create.return_value = expected

    result = verify_symbol_identity("Volaris", "Controladora Vuela Compañía de Aviación, S.A.B. de C.V.")

    assert result is expected
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["response_model"] is SymbolIdentityVerdict
    from app.config import get_settings
    assert kwargs["model"] == get_settings().generation_model_fallback


@patch("app.services.llm_service._client")
def test_verify_symbol_identity_falls_back_to_primary_model_when_judge_model_raises(mock_client):
    fallback_result = SymbolIdentityVerdict(matches=False, reason="unrelated fund")
    mock_client.chat.completions.create.side_effect = [RuntimeError("judge model down"), fallback_result]

    result = verify_symbol_identity("Petróleos Mexicanos", "Pioneer Emerging Markets Equity Fund")

    assert result is fallback_result
    assert mock_client.chat.completions.create.call_count == 2
