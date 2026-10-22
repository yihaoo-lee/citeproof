import pytest

from app.services.synthesize import collect_evidence, synthesize


def row(paper_id, entailment):
    claim = {"field": "conclusion", "verified": True, "quote": "Evidence sentence.", "page": 1}
    if entailment is not None:
        claim["entailment"] = entailment
    return {"paper_id": paper_id, "title": paper_id, "fields": {"conclusion": "Conclusion"}, "claims": [claim]}


@pytest.mark.parametrize("entailment", [None, "", "unsupported"])
def test_collect_evidence_excludes_non_supported(entailment):
    assert collect_evidence([row("a", entailment)], "conclusion") == []


def test_collect_evidence_keeps_supported():
    items = collect_evidence([row("a", "supported")], "conclusion")
    assert len(items) == 1
    assert items[0]["entailment"] == "supported"


def test_collect_evidence_keeps_partial():
    items = collect_evidence([row("a", "partial")], "conclusion")
    assert len(items) == 1
    assert items[0]["entailment"] == "partial"


def test_synthesis_reports_insufficient_with_one_supported(monkeypatch):
    monkeypatch.setattr("app.services.synthesize.config.DEMO_MODE", False)
    monkeypatch.setattr("app.services.synthesize.config.LLM_API_KEY", "test")
    result = synthesize([row("a", "supported"), row("b", "unsupported")])
    assert next(item for item in result if item["field"] == "conclusion")["stance"] == "insufficient"


def test_synthesis_includes_partial_as_valid_evidence(monkeypatch):
    monkeypatch.setattr("app.services.synthesize.config.DEMO_MODE", False)
    monkeypatch.setattr("app.services.synthesize.config.LLM_API_KEY", "test")
    monkeypatch.setattr(
        "app.services.synthesize._call_llm",
        lambda prompt: {
            "results": [{
                "field": "conclusion",
                "stance": "partial",
                "summary": "各有侧重",
                "groups": [
                    {"position": "A 观点", "paper_ids": ["a"]},
                    {"position": "B 观点", "paper_ids": ["b"]},
                ],
            }]
        },
    )
    result = synthesize([row("a", "supported"), row("b", "partial")])
    item = next(x for x in result if x["field"] == "conclusion")
    assert item["stance"] == "partial"
    papers = [p for g in item["groups"] for p in g["papers"]]
    assert {p["paper_id"] for p in papers} == {"a", "b"}
    assert {p["entailment"] for p in papers} == {"supported", "partial"}
