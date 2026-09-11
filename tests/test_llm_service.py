from unittest.mock import MagicMock, patch

from app.analysis.synthesis import EvidenceAggregate
from app.schemas import AnalysisSynthesis, Citation
from app.services.llm_service import generate_synthesis, render_prompts


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
