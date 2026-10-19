"""六字段抽取 + 锚点：模型只产出字段摘要与短锚点，展示用原句由服务端扩出。"""
from __future__ import annotations

import json
import re

import httpx

from .. import config
from ..models import FIELD_NAMES
from .parse import detect_language

_SENT_SPLIT = re.compile(r"(?<=[.!?。！？；;])\s+")


def _sentences(text: str, min_len: int = 20) -> list[str]:
    parts = _SENT_SPLIT.split(text or "")
    return [p.strip() for p in parts if len(p.strip()) >= min_len]


def _sample_pages(pages: list[str], limit: int) -> str:
    """多段取样：开头 + 中段 + 结尾，避免首页摘要区一乱整篇作废。"""
    n = len(pages)
    if n == 0:
        return ""
    if n == 1:
        return pages[0][:limit]
    head_b = int(limit * 0.4)
    mid_b = int(limit * 0.2)
    tail_b = int(limit * 0.4)
    parts = [pages[0][:head_b]]
    if n >= 4:
        parts.append(pages[n // 2][:mid_b])
    parts.append("".join(pages[max(1, n - 2):])[:tail_b])
    return "\n\n".join(p for p in parts if p.strip())


def _stub(pages: list[str], abstract: str):
    """启发式抽取：从首页取句，quote 即句子（保证可校验）。无锚点。"""
    source = next((p for p in pages if p.strip()), "")
    pool = _sentences(source) or _sentences(abstract) or ["（无可用文本，演示模式）"]
    n = len(pool)
    fields = {
        "problem": pool[0] if n > 0 else "",
        "method": pool[1] if n > 1 else "",
        "dataset": pool[2] if n > 2 else "",
        "conclusion": pool[-1] if n > 0 else "",
        "limitation": "（演示模式，启发式抽取，未做人工标注）",
        "reproducibility": pool[3] if n > 3 else "",
    }
    quotes = [
        (f, fields[f])
        for f in FIELD_NAMES
        if fields.get(f) and not fields[f].startswith("（演示模式")
    ]
    return fields, quotes, [], True, False


def _llm(pages: list[str], abstract: str, paper_title: str):
    """真实抽取：DeepSeek JSON 输出六字段 + evidence(quote 尝试 + anchor 短锚点)。"""
    total_chars = sum(len(p) for p in pages)
    full_text = _sample_pages(pages, config.TEXT_CHAR_LIMIT)
    partial = total_chars > config.TEXT_CHAR_LIMIT
    lang = detect_language(full_text or abstract)

    prompt = (
        f"你是文献结构化助手。论文标题：{paper_title}（语言：{'中文' if lang == 'zh' else '英文'}）。\n"
        "下面给出论文文本（节选：开头/中段/结尾，可能不连续）。请只输出一个 JSON 对象：\n"
        '{"problem":"…","method":"…","dataset":"…","conclusion":"…","limitation":"…","reproducibility":"…",'
        '"evidence":[{"field":"conclusion","quote":"…","anchor":"…"},{"field":"method","quote":"…","anchor":"…"}]}\n'
        "要求：六字段全部用中文、每字段不超过 60 字；evidence 中 conclusion 和 method 必须有，"
        "problem/dataset/limitation/reproducibility 原文有对应句也尽量给；每篇目标 3–5 条、每字段最多 1 条；不许编造。\n"
        "quote：你对原文的逐字复制尝试（完整连续句子，做不到逐字可留空字符串）；\n"
        "anchor：原文中真实存在的一段短片段，4 个词以上，最好含数字、专有名词或专业术语，"
        "用于系统定位原句；禁止通用短语（in this paper / we propose / results show 等）；\n"
        "不要输出页码。只返回 JSON。\n\n"
        f"论文文本：\n{full_text}"
    )

    payload = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}
    try:
        resp = httpx.post(
            f"{config.LLM_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=config.HTTP_TIMEOUT * 3,
        )
        resp.raise_for_status()
        data = resp.json()["choices"][0]["message"]["content"]
        obj = json.loads(data)
    except Exception:  # noqa: BLE001
        return None, [], [], False, False

    fields = {f: str(obj.get(f, ""))[:60] for f in FIELD_NAMES}
    quotes = []
    anchors = []
    for e in obj.get("evidence") or []:
        f = e.get("field")
        if f not in FIELD_NAMES:
            continue
        q = str(e.get("quote", "")).strip()
        if 20 <= len(q) <= 200:
            quotes.append((f, q))
        a = str(e.get("anchor", "")).strip()
        if a:
            anchors.append((f, a))
    return fields, quotes, anchors, False, partial


def extract_fields_and_quotes(pages: list[str], paper: dict):
    """统一入口。返回 (fields, quotes, anchors, stub, partial)。"""
    if config.DEMO_MODE or not config.llm_configured():
        return _stub(pages, paper.get("abstract", ""))
    res = _llm(pages, paper.get("abstract", ""), paper.get("title", ""))
    if res[0] is None:
        return _stub(pages, paper.get("abstract", ""))
    return res
