import httpx
import pytest

from app.services import extract, matrix


def test_llm_timeout_fails_analysis_instead_of_heuristic_fallback(monkeypatch):
    monkeypatch.setattr(extract.config, "DEMO_MODE", False)
    monkeypatch.setattr(extract.config, "LLM_API_KEY", "test")

    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(extract.httpx, "post", timeout)
    paper = {"id": "p1", "title": "Paper", "pages": ["A method produces a result."]}
    with pytest.raises(extract.LLMCallError, match="超时"):
        matrix.build_matrix("question", [paper])
