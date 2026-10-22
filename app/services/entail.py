"""claim–quote 语义判断（批量）。无 key 时返回空判定。"""
from __future__ import annotations

import json

import httpx

from .. import config
from .llm import LLMCallError, with_retry


def judge_claims(items: list[dict]) -> list[dict]:
    """items: [{id, field, claim, quote}] → [{id, entailment, reason}]"""
    if not config.llm_configured() or not items:
        return [{"id": it["id"], "entailment": "", "reason": ""} for it in items]

    lines = []
    for i, it in enumerate(items):
        lines.append(f'{i}|{it["field"]}|{it["claim"]}|{it["quote"]}')

    prompt = (
        "下面是若干条“字段结论(claim)”和对应的“原文引用(quote)”。"
        "逐条判断 quote 是否真的支撑该 claim，只输出一个 JSON 对象："
        '{"judgements":[{"id":编号,"entailment":"supported|partial|unsupported",'
        '"reason":"一句中文理由"}]}。编号即行首数字；不要输出其他内容。\n'
        "判定标准：supported = quote 直接、明确地支撑 claim 的核心内容；"
        "partial = quote 与 claim 相关但只覆盖一部分或需推断；"
        "unsupported = quote 与 claim 无关、矛盾或不足以支撑。"
        "不要一律判 partial；语义上能对上核心内容就判 supported。\n"
        + "\n".join(lines)
    )
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
        content, _usage = with_retry(_post, "语义复审")
        arr = (json.loads(content) or {}).get("judgements") or []
    except LLMCallError:
        raise
    except (ValueError, TypeError) as exc:
        raise LLMCallError("模型语义复审返回格式错误，请重试") from exc

    verdicts = {}
    for r in arr:
        if isinstance(r, dict) and "id" in r:
            verdicts[str(r["id"])] = {
                "entailment": r.get("entailment", ""),
                "reason": r.get("reason", ""),
            }
    return [
        {
            "id": it["id"],
            "entailment": verdicts.get(str(i), {}).get("entailment", ""),
            "reason": verdicts.get(str(i), {}).get("reason", ""),
        }
        for i, it in enumerate(items)
    ]
