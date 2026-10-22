import json
from pathlib import Path


def test_demo_synthesis_uses_only_supported_quotes():
    path = Path(__file__).resolve().parents[1] / "data" / "cache" / "demo.json"
    matrix = json.loads(path.read_text(encoding="utf-8"))["matrix"]
    claims = {
        (row["paper_id"], claim["field"]): claim
        for row in matrix["rows"] for claim in row["claims"]
    }
    for item in matrix["synthesis"]:
        for group in item["groups"]:
            for paper in group["papers"]:
                assert claims[(paper["paper_id"], item["field"])]["entailment"] == "supported"


def test_demo_cache_does_not_contain_machine_paths():
    path = Path(__file__).resolve().parents[1] / "data" / "cache" / "demo.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert all(not Path(paper["pdf_path"]).is_absolute() for paper in payload["papers"])
