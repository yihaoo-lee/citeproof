"""离线自测：stub 端到端 + 导出 + 缓存校验 + 锚点/校验单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import config  # noqa: E402
from app.services.export import export_matrix  # noqa: E402
from app.services.matrix import build_matrix  # noqa: E402
from app.services.synthesize import _sanitize, collect_evidence  # noqa: E402
from app.services.verify import (  # noqa: E402
    PARA,
    _expand_sentence,
    _looks_like_table,
    _valid_anchor,
    locate_anchor,
    locate_quote,
)

config.DEMO_MODE = True
config.LLM_API_KEY = ""

SAMPLE = (
    "We propose a hallucination detection method. "
    "We sample multiple responses and measure self-consistency. "
    "Experiments show a 12% improvement in factuality. "
    "Our approach is reproducible with public data."
)


def test_verify() -> None:
    # 1) 正常锚点扩句
    pages = ["This paper proposes RAG models. We combine parametric and non-parametric memory. Results improve."]
    res = locate_anchor(pages, "combine parametric and non-parametric memory")
    assert res and res["level"] == "anchored", "正常锚点应定位成功"
    assert "non-parametric memory" in res["quote"], "扩句应包含原句"

    # 2) 通用短语被拒
    assert _valid_anchor("in this paper we propose a method") is False, "通用短语应被拒"

    # 3) 歧义锚点丢弃
    ambiguous = ["A uses method X to solve it. B uses method X differently."]
    assert locate_anchor(ambiguous, "method X") is None, "多处命中应判歧义丢弃"

    # 4) 表格碎片被拒
    assert _looks_like_table("Table 1 45.7 36.9 37.7 37.3") is True, "表格碎片应被识别"

    # 5) 中文锚点 + 中文扩句
    assert _valid_anchor("提出一种基于采样的幻觉检测方法") is True, "中文锚点应有效"
    cp = "本文提出一种方法。实验结果表明该方法有效。"
    sent = _expand_sentence(cp, cp.find("实验结果表明该方法有效"))
    assert sent == "实验结果表明该方法有效。", f"中文扩句应为整句，得到：{sent}"

    # 6) 英文缩写不截断
    en = "To generate these samples automatically, we propose a two-stage framework, i.e., sampling-then-filtering. We then evaluate."
    sent = _expand_sentence(en, en.find("sampling-then-filtering"))
    assert sent.startswith("To generate these samples automatically"), f"i.e. 前文应保留：{sent}"
    assert sent.endswith("sampling-then-filtering."), f"i.e. 不应截断：{sent}"
    en2 = "We use models, e.g., GPT-3, for generation. Next sentence."
    sent2 = _expand_sentence(en2, en2.find("GPT-3"))
    assert sent2.endswith("for generation."), f"e.g. 不应截断：{sent2}"

    # 7) 上下文包含引文与前后句
    page = "First sentence sets the stage. We propose a two-stage framework, i.e., sampling-then-filtering. Last sentence wraps up."
    res = locate_quote([page], "two-stage framework, i.e., sampling-then-filtering")
    assert res and res.get("context"), "应返回上下文"
    assert "First sentence" in res["context"] and "Last sentence" in res["context"], res["context"]
    assert res["context"].find("two-stage framework") >= 0, "上下文应包含引文"

    # 8) 上下文不含段落占位符
    page2 = "First paragraph sentence.\n\nSecond paragraph has the quote, i.e., here. Last sentence."
    res2 = locate_quote([page2], "the quote, i.e., here")
    assert res2 and PARA not in res2["context"], f"上下文不应含段落占位符：{res2 and res2['context']}"


def test_synthesis() -> None:
    rows = [
        {"paper_id": "p1", "title": "A", "year": 2024, "fields": {"conclusion": "甲"},
         "claims": [{"field": "conclusion", "quote": "quote A", "verified": True, "page": 1}]},
        {"paper_id": "p2", "title": "B", "year": 2025, "fields": {"conclusion": "乙"},
         "claims": [{"field": "conclusion", "quote": "quote B", "verified": True, "page": 2}]},
    ]
    ev = collect_evidence(rows, "conclusion")
    assert len(ev) == 2 and ev[0]["quote"] == "quote A", "证据聚合应基于已验证 quote"

    evidence = {"conclusion": ev}
    raw = {"results": [{"field": "conclusion", "stance": "partial", "summary": "两派", "groups": [
        {"position": "甲派", "paper_ids": ["p1"]},
        {"position": "乙派", "paper_ids": ["p2"]},
    ]}]}
    out = _sanitize(raw, evidence)
    concl = next(x for x in out if x["field"] == "conclusion")
    assert concl["stance"] == "partial" and len(concl["groups"]) == 2
    assert concl["groups"][0]["papers"][0]["quote"] == "quote A", "原文必须由系统回填"

    bad = {"results": [{"field": "conclusion", "stance": "consensus", "summary": "x",
                        "groups": [{"position": "x", "paper_ids": ["nope"]}]}]}
    bad_out = next(x for x in _sanitize(bad, evidence) if x["field"] == "conclusion")
    assert bad_out["stance"] == "insufficient", "坏 paper_id 应回退证据不足"

    bad2 = {"results": [{"field": "conclusion", "stance": "maybe", "summary": "x", "groups": []}]}
    bad2_out = next(x for x in _sanitize(bad2, evidence) if x["field"] == "conclusion")
    assert bad2_out["stance"] == "insufficient", "非法 stance 应回退证据不足"

    assert _sanitize([], evidence) is None, "坏 JSON 结构应整置空"
    assert _sanitize({"results": "nope"}, evidence) is None, "坏 results 应整置空"


def main() -> int:
    test_verify()
    test_synthesis()

    papers = [
        {
            "id": "demo:1",
            "title": "Demo Paper on Hallucination Detection",
            "year": 2024,
            "authors": ["A. Author"],
            "url": "",
            "abstract": SAMPLE,
            "source": "demo",
            "language": "en",
            "pages": [SAMPLE],
        }
    ]
    matrix = build_matrix("hallucination detection", papers)

    assert matrix.stats.papers == 1, "矩阵应有一篇论文"
    assert matrix.stats.attempts > 0, "应有抽取尝试"
    assert matrix.stats.kept > 0, "至少保留一条 claim"
    for row in matrix.rows:
        for claim in row.claims:
            assert claim.verified is True, "展示的 claim 必须通过校验"

    out = export_matrix(matrix, PROJECT_ROOT / "data" / "tmp")
    for p in out.values():
        assert Path(p).exists() and Path(p).stat().st_size > 0, f"导出文件应为非空：{p}"

    cache_file = PROJECT_ROOT / "data" / "cache" / "demo.json"
    if cache_file.exists():
        import json

        payload = json.load(open(cache_file, encoding="utf-8"))
        cache_rows = (payload.get("matrix") or {}).get("rows") or []
        assert cache_rows, "demo 缓存应包含矩阵行"
        for row in cache_rows:
            for claim in row.get("claims") or []:
                assert claim.get("verified") is True, "demo 缓存中的 claim 必须已校验"
                assert "anchor" in claim, "claim 应含 anchor 字段"
                assert "proposal" in claim, "claim 应含 proposal 字段"
                assert PARA not in (claim.get("context") or ""), "context 不应含段落占位符"
        print(f"demo cache ok: {len(cache_rows)} rows")

    print("selftest OK")
    print(
        f"  papers={matrix.stats.papers} attempts={matrix.stats.attempts} "
        f"kept={matrix.stats.kept} hit_rate={matrix.stats.quote_hit_rate}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
