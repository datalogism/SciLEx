"""Tests for LLM abstract screening (HTTP mocked)."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

from scilex import llm_relevance as llm
from scilex.llm_relevance import LLMScreeningConfig


def _response(content, status=200):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    response.raise_for_status.return_value = None
    return response


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"score": 0.8}', 0.8),
        ('```json\n{"score": 1}\n```', 1.0),
        ('Sure! {"score": "0.25"} done', 0.25),
        ("0.5", 0.5),
    ],
)
def test_parse_score_valid(text, expected):
    assert llm.parse_score(text) == expected


@pytest.mark.parametrize("text", ["", "no idea", '{"score": 7}', '{"score": null}'])
def test_parse_score_invalid(text):
    with pytest.raises(ValueError):
        llm.parse_score(text)


def test_config_defaults_disabled():
    config = LLMScreeningConfig.from_dict(None)
    assert config.enabled is False and config.threshold is None


def test_api_key_resolution(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert llm.resolve_api_key({}) is None
    assert llm.resolve_api_key({"openrouter": {"api_key": "k"}}) == "k"
    monkeypatch.setenv("OPENROUTER_API_KEY", "env")
    assert llm.resolve_api_key({}) == "env"


def test_request_score_retries_then_succeeds():
    responses = [_response("", 503), _response("garbage"), _response('{"score": 0.4}')]
    with (
        patch.object(llm._get_session(), "post", side_effect=responses) as post,
        patch("tenacity.nap.time.sleep"),
    ):
        assert llm.request_score("t", "a", "topic", "m", "key") == 0.4
    assert post.call_count == 3


def test_request_score_network_error_exhausts():
    with (
        patch.object(
            llm._get_session(),
            "post",
            side_effect=requests.exceptions.ConnectionError("x"),
        ),
        patch("tenacity.nap.time.sleep"),
        pytest.raises(llm._RetryableLLMError),
    ):
        llm.request_score("t", "a", "topic", "m", "key")


def _frame():
    return pd.DataFrame(
        {
            "title": ["Good", "Bad", "Other"],
            "abstract": ["about graphs"] * 3,
            "DOI": ["10.1/a", "10.1/b", "NA"],
        }
    )


def test_apply_screening_threshold_and_cache(tmp_path):
    config = LLMScreeningConfig(
        enabled=True, topic="knowledge graphs", threshold=0.5, workers=2
    )
    cache_path = str(tmp_path / "cache.json")
    answers = {"Good": 0.9, "Bad": 0.1, "Other": 0.6}

    def fake_request(title, abstract, topic, model, api_key, **kwargs):
        return answers[title]

    with patch.object(llm, "request_score", side_effect=fake_request) as request:
        result = llm.apply_llm_screening(
            _frame(), config, {"openrouter": {"api_key": "k"}}, cache_path
        )
        assert sorted(result["title"]) == ["Good", "Other"]
        assert request.call_count == 3

    # Second run: everything cached, no request issued.
    with patch.object(llm, "request_score") as request:
        result = llm.apply_llm_screening(
            _frame(), config, {"openrouter": {"api_key": "k"}}, cache_path
        )
        request.assert_not_called()
        assert len(result) == 2


def test_cache_key_depends_on_topic_and_model():
    assert llm.cache_key("t", "10.1/A", "m", "x") == llm.cache_key(
        "t", "10.1/a", "m", "x"
    )
    assert llm.cache_key("t", "10.1/a", "m", "x") != llm.cache_key(
        "t", "10.1/a", "m", "y"
    )
    assert llm.cache_key("t", "10.1/a", "m", "x") != llm.cache_key(
        "t", "10.1/a", "n", "x"
    )


def test_max_papers_leaves_rest_unscored_and_kept(tmp_path):
    config = LLMScreeningConfig(enabled=True, topic="t", max_papers=1, threshold=0.5)
    with patch.object(llm, "request_score", return_value=0.9):
        result = llm.apply_llm_screening(
            _frame(), config, {"openrouter": {"api_key": "k"}}, None
        )
    assert len(result) == 3
    assert result[llm.SCORE_COLUMN].notna().sum() == 1


def test_failed_scoring_keeps_paper():
    config = LLMScreeningConfig(enabled=True, topic="t", threshold=0.5)
    with patch.object(llm, "request_score", side_effect=RuntimeError("boom")):
        result = llm.apply_llm_screening(
            _frame(), config, {"openrouter": {"api_key": "k"}}, None
        )
    assert len(result) == 3


def test_missing_key_or_topic_raises(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(llm.LLMScreeningError):
        llm.apply_llm_screening(_frame(), LLMScreeningConfig(topic="t"), {}, None)
    with pytest.raises(llm.LLMScreeningError):
        llm.apply_llm_screening(_frame(), LLMScreeningConfig(topic=""), {}, None)


def test_estimate_cost_scales_with_papers():
    config = LLMScreeningConfig(topic="topic")
    _, _, small = llm.estimate_cost(_frame().iloc[:1], config)
    _, _, large = llm.estimate_cost(_frame(), config)
    assert 0 < small < large


def test_scoring_runs_requests_concurrently():
    """Workers overlap: 8 papers taking 0.2 s each finish well under 1.6 s."""
    import threading
    import time

    df = pd.DataFrame({"title": [f"paper {index}" for index in range(8)]})
    config = llm.LLMScreeningConfig(enabled=True, topic="kg", workers=8)
    active = 0
    peak = 0
    lock = threading.Lock()

    def slow_request(*args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.2)
        with lock:
            active -= 1
        return 0.5

    start = time.monotonic()
    with patch.object(llm, "request_score", side_effect=slow_request):
        scored = llm.score_dataframe(df, config, "key")
    assert time.monotonic() - start < 1.0
    assert peak > 1
    assert scored[llm.SCORE_COLUMN].tolist() == [0.5] * 8


def test_workers_capped():
    assert (
        llm.LLMScreeningConfig.from_dict({"workers": 1000}).workers == llm.MAX_WORKERS
    )


def test_request_score_disables_reasoning():
    """Reasoning models must not spend the token budget before answering."""
    with patch.object(
        llm._get_session(), "post", return_value=_response('{"score": 0.6}')
    ) as post:
        assert llm.request_score("t", "a", "topic", "m", "key") == 0.6
    payload = post.call_args.kwargs["json"]
    assert payload["reasoning"] == {"enabled": False}
    assert payload["max_tokens"] >= 100


def _error_response(status, message):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = {"error": {"message": message}}
    return response


def test_request_score_access_denied_not_retried():
    with (
        patch.object(
            llm._get_session(),
            "post",
            return_value=_error_response(403, "Key limit exceeded (monthly limit)."),
        ) as post,
        pytest.raises(llm.LLMAccessError, match="Key limit exceeded"),
    ):
        llm.request_score("t", "a", "topic", "m", "key")
    assert post.call_count == 1


def test_access_denied_stops_screening_and_keeps_papers(caplog):
    frame = pd.DataFrame(
        {
            "title": [f"P{i}" for i in range(20)],
            "abstract": ["x"] * 20,
            "DOI": ["NA"] * 20,
        }
    )
    config = LLMScreeningConfig(enabled=True, topic="t", threshold=0.5, workers=1)
    with patch.object(
        llm, "request_score", side_effect=llm.LLMAccessError("HTTP 403: limit")
    ) as request:
        result = llm.apply_llm_screening(
            frame, config, {"openrouter": {"api_key": "k"}}
        )
    assert request.call_count == 1
    assert len(result) == 20
    assert "refused the API key" in caplog.text
