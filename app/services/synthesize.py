"""跨论文共识/分歧综合：只依据已校验原文，模型只输出立场判断。"""
from __future__ import annotations

import json

import httpx

from .. import config
from ..models import FIELD_NAMES
from .llm import LLMCallError, with_retry

STANCES = {"consensus", "partial", "conflict", "insufficient"}
FIELD_LABEL_ZH = {
    "problem": "问题",
    "method": "方法",
    "dataset": "数据集",
    "conclusion": "结论",
    "limitation": "局限",
    "reproducibility": "可复现性",
}


def collect_evidence(rows: list[dict], field: str) -> list[dict]:
    """收集定位成功且语义复审为支持或部分支持的引用；unsupported / 未判定不参与。"""
    items = []
    for row in rows:
        claim = next(
            (
                c
                for c in (row.get("claims") or [])
                if c.get("field") == field and c.get("verified") and c.get("quote")
                and c.get("entailment") in {"supported", "partial"}
            ),
            None,
        )
        if not claim:
            continue
        items.append({
            "paper_id": row.get("paper_id", ""),
            "title": row.get("title", ""),
            "year": row.get("year"),
            "summary": (row.get("fields") or {}).get(field, ""),
            "quote": claim.get("quote", ""),
            "page": claim.get("page"),
            "entailment": claim.get("entailment", "partial"),
        })
    return items


def _insufficient(field: str) -> dict:
    return {
        "field": field,
        "stance": "insufficient",
        "summary": "证据不足（该字段少于 2 篇支持或部分支持的证据）",
        "groups": [],
    }


def _sanitize(raw, evidence_by_field: dict[str, list[dict]]):
    """清洗模型输出；坏结构返回 None，坏字段/坏 paper_id 回退 insufficient。"""
    if not isinstance(raw, dict):
        return None
    results = raw.get("results")
    if not isinstance(results, list):
        return None

    by_field = {}
    for item in results:
        if isinstance(item, dict) and item.get("field") in evidence_by_field:
            by_field[item["field"]] = item

    out = []
    for field in FIELD_NAMES:
        ev = evidence_by_field.get(field) or []
        if len(ev) < 2:
            out.append(_insufficient(field))
            continue
        item = by_field.get(field)
        if not isinstance(item, dict):
            out.append(_insufficient(field))
            continue

        stance = item.get("stance")
        summary = str(item.get("summary", ""))[:160]
        valid_ids = {e["paper_id"] for e in ev}
        by_id = {e["paper_id"]: e for e in ev}
        groups = []
        for g in item.get("groups") or []:
            if not isinstance(g, dict):
                continue
            ids = [pid for pid in (g.get("paper_ids") or []) if pid in valid_ids]
            if not ids:
                continue
            groups.append({
                "position": str(g.get("position", ""))[:80],
                "paper_ids": ids,
                "papers": [by_id[pid] for pid in ids],
            })

        if stance not in STANCES or stance == "insufficient":
            out.append(_insufficient(field))
            continue
        if stance == "consensus":
            if len(groups) != 1:
                out.append(_insufficient(field))
                continue
        elif len(groups) < 2:
            out.append(_insufficient(field))
            continue

        out.append({"field": field, "stance": stance, "summary": summary, "groups": groups})
    return out


def _call_llm(prompt: str):
    payload = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}

    def _post():
        resp = httpx.post(
            f"{config.LLM_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=config.HTTP_TIMEOUT * 3,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"], (data.get("usage") or {})

    try:
        content, _usage = with_retry(_post, "跨论文综合")
        return json.loads(content)
    except LLMCallError:
        raise
    except (ValueError, TypeError) as exc:
        raise LLMCallError("模型跨论文综合返回格式错误，请重试") from exc


def build_prompt(evidence_by_field: dict[str, list[dict]]) -> str:
    lines = []
    for field, ev in evidence_by_field.items():
        lines.append(f"## 字段：{field}（{FIELD_LABEL_ZH[field]}）")
        for e in ev:
            tag = "（部分支持）" if e.get("entailment") == "partial" else ""
            lines.append(
                f"- paper_id={e['paper_id']} | 标题：{e['title']} ({e['year']}){tag}"
            )
            lines.append(f"  中文概括：{e['summary']}")
            lines.append(f"  原文引用：{e['quote']}")

    return (
        "你在做跨论文证据综合。下面按字段列出若干篇论文的中文概括和已校验原文引用。\n"
        "必须为以下每个字段各输出一条结果（缺一不可）：problem、method、dataset、conclusion、limitation、reproducibility；"
        "无法判定的字段也必须输出 stance=insufficient、groups=[]。\n"
        "只能依据给定内容判断，禁止使用任何外部知识。\n"
        "证据强度：标注“（部分支持）”的证据强度较弱，综合表述须如实反映，不得当成强支持。\n"
        "判定四档：consensus（实质相同的结论或做法）、partial（有共同基础，但方法/数据集/适用范围/结论强弱有差异）、"
        "conflict（对同一问题给出明确相反的结论）、insufficient（证据不足或无法可靠判定）。\n"
        "硬规则：不同任务/数据集上的“各自有效”不算分歧，归 partial；原文没有明确相反结论时禁止判 conflict；宁可不判。\n"
        "立场相同的论文合并到同一组，不要一篇论文单独一组。\n"
        '输出 JSON：{"results":[{"field":"conclusion","stance":"consensus|partial|conflict|insufficient",'
        '"summary":"一句中文综合","groups":[{"position":"该立场中文概括","paper_ids":["..."]}]}]}\n'
        "consensus 只给 1 个组；partial/conflict 给 2 个及以上组；insufficient 给空数组。只输出 JSON。\n\n"
        + "\n".join(lines)
    )


def synthesize(rows: list[dict]):
    """返回 synthesis 列表；无 key/DEMO/调用失败返回 None（前端隐藏面板）。"""
    evidence_by_field = {}
    for field in FIELD_NAMES:
        ev = collect_evidence(rows, field)
        if len(ev) >= 2:
            evidence_by_field[field] = ev

    if not evidence_by_field:
        return [_insufficient(f) for f in FIELD_NAMES]
    if config.DEMO_MODE or not config.llm_configured():
        return None

    raw = _call_llm(build_prompt(evidence_by_field))
    result = _sanitize(raw, evidence_by_field)
    if result is None:
        raise LLMCallError("模型跨论文综合返回格式错误，请重试")
    return result
