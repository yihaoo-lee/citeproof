import httpx
import pytest

from app.services import entail, extract, matrix, synthesize
from app.services.extract import LLMCallError


def timeout(*args, **kwargs):
    raise httpx.ReadTimeout("timed out")


def test_entailment_timeout_is_reported(monkeypatch):
    monkeypatch.setattr(entail.config, "LLM_API_KEY", "test")
    monkeypatch.setattr(entail.httpx, "post", timeout)
    with pytest.raises(LLMCallError, match="超时"):
        entail.judge_claims([{"id": 0, "field": "method", "claim": "summary", "quote": "original"}])


def test_synthesis_timeout_is_reported(monkeypatch):
    monkeypatch.setattr(synthesize.config, "LLM_API_KEY", "test")
    monkeypatch.setattr(synthesize.config, "DEMO_MODE", False)
    monkeypatch.setattr(synthesize.httpx, "post", timeout)
    rows = [
        {"paper_id": str(i), "title": str(i), "fields": {"method": "summary"},
         "claims": [{"field": "method", "quote": "original", "verified": True, "entailment": "supported"}]}
        for i in range(2)
    ]
    with pytest.raises(LLMCallError, match="超时"):
        synthesize.synthesize(rows)


def test_transient_error_retries_once_then_succeeds(monkeypatch):
    monkeypatch.setattr(extract.config, "DEMO_MODE", False)
    monkeypatch.setattr(extract.config, "LLM_API_KEY", "test")
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("first attempt")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"problem":"p","method":"m","conclusion":"c","evidence":[]}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
            request=httpx.Request("POST", "http://example.invalid/"),
        )

    monkeypatch.setattr(extract.httpx, "post", flaky)
    paper = {"id": "p1", "title": "Paper", "pages": ["A method produces a result."]}
    result = matrix.build_matrix("question", [paper])
    assert calls["n"] == 2
    assert result.stats.papers == 1
