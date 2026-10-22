"""证据定位：模型只指位置（锚点），原句由服务端从页文本扩出。"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

PARA = "\ue000"  # 段落/块边界占位符（非空白字符，避免被 \s 吃掉）


def _collapse(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", PARA, text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize(text: str) -> str:
    """归一化：NFKC、去软连字符、忽略连字符、去空白、大小写折叠。"""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00ad", "")
    text = text.replace(PARA, "")
    text = re.sub(r"-", "", text)
    text = re.sub(r"\s+", "", text)
    return text.casefold()


def _normalized_with_positions(text: str) -> tuple[str, list[int]]:
    """Return normalized text and the source offset for each output character."""
    chars = []
    positions = []
    for index, char in enumerate(text):
        if char in {"\u00ad", "-"} or char.isspace():
            continue
        for normalized in unicodedata.normalize("NFKC", char).casefold():
            if normalized not in {"\u00ad", "-"} and not normalized.isspace():
                chars.append(normalized)
                positions.append(index)
    return "".join(chars), positions


def _looks_like_table(s: str) -> bool:
    """启发式识别表格碎片：竖线分隔、连续数字、标点列表、大写字词堆叠、中文顿号列表。"""
    if "|" in s:
        return True
    if len(re.findall(r"\d+", s)) >= 4:
        return True
    parts = re.split(r"[、,，]", s)
    if len(parts) >= 4:
        avg = sum(len(p.strip()) for p in parts) / len(parts)
        if avg < 12:  # 每段都很短，才像表格单元格
            return True
    if len(re.findall(r"\b[A-Z][A-Za-z]*(?:-[A-Z][A-Za-z]*)*\b", s)) >= 5:
        return True
    if len(re.findall(r"[０-９]", s)) >= 3:
        return True
    return False


_ABBR_RE = re.compile(
    r"\b(?:i\.e|e\.g|et\s+al|etc|u\.s|u\.k|vs|dr|mr|mrs|ms|fig|eq|no|cf|approx|al)\.(?=\s|,|;|\)|\]|$)",
    re.IGNORECASE,
)


def _protect_abbr(text: str) -> str:
    """把缩写内部句点替换为单字符占位符（长度不变，索引不偏移）。"""
    return _ABBR_RE.sub(lambda m: m.group(0).replace(".", "\u2024"), text)


def _restore_abbr(text: str) -> str:
    return text.replace("\u2024", ".")


def _next_nonspace(text: str, i: int) -> str:
    j = i + 1
    while j < len(text) and text[j] in " \n":
        j += 1
    return text[j] if j < len(text) else ""


def _is_boundary(text: str, i: int) -> bool:
    ch = text[i]
    if ch == PARA:
        return True
    if ch in "。！？":
        return True
    if ch not in ".!?":
        return False
    if ch == ".":
        nxt = _next_nonspace(text, i)
        if nxt and (nxt.islower() or nxt in ",;:"):
            return False
    return True


def _expand_sentence(cp: str, pos: int) -> str:
    """以 cp 中 pos 为锚，向两侧扩到最近的句末标点；跳过 i.e./e.g./et al. 等缩写。"""
    text = _protect_abbr(cp)

    start = 0
    for i in range(pos - 1, -1, -1):
        if _is_boundary(text, i):
            start = i + 1
            break
    while start < len(text) and text[start] in " \n":
        start += 1

    end = len(text)
    for i in range(pos, len(text)):
        if _is_boundary(text, i):
            end = i + 1
            break

    return _restore_abbr(text[start:end]).strip()


def _sentence_start(text: str, pos: int) -> int:
    for i in range(pos - 1, -1, -1):
        if _is_boundary(text, i):
            return i + 1
    return 0


def _sentence_end(text: str, pos: int) -> int:
    for i in range(pos, len(text)):
        if _is_boundary(text, i):
            return i + 1
    return len(text)


def _context_around(text: str, idx: int, qlen: int, max_len: int = 600) -> str:
    """引文所在句 + 前后各至多一句，返回包含引文的段落文本。"""
    protected = _protect_abbr(text)
    s1 = _sentence_start(protected, idx)
    e1 = _sentence_end(protected, idx + qlen)
    s0 = _sentence_start(protected, s1 - 1) if s1 > 0 else 0
    e2 = _sentence_end(protected, e1) if e1 < len(protected) else len(protected)
    ctx = protected[s0:e2]
    if len(ctx) > max_len:
        rel = max(0, idx - s0)
        start = max(0, rel - max_len // 2)
        ctx = ctx[start:start + max_len]
    return _restore_abbr(ctx).replace(PARA, "\n").strip()


def locate_quote(pages: list[str], quote: str) -> dict | None:
    """模型逐字对了就直接用（exact / normalized）。"""
    q = _collapse(quote)
    if not q:
        return None
    for i, page in enumerate(pages, start=1):
        cp = _collapse(page)
        if q in cp:
            if not _looks_like_table(q):
                idx = cp.find(q)
                return {
                    "page": i,
                    "level": "exact",
                    "quote": q,
                    "context": _context_around(cp, idx, len(q)),
                }
    qn = normalize(quote)
    for i, page in enumerate(pages, start=1):
        cp = _collapse(page)
        offset = 0
        for segment in cp.split(PARA):
            normalized, positions = _normalized_with_positions(segment)
            idx = normalized.find(qn) if qn else -1
            if idx >= 0:
                start = offset + positions[idx]
                end = offset + positions[idx + len(qn) - 1] + 1
                actual = cp[start:end]
                sentence = _expand_sentence(cp, start)
                if (normalize(actual) == qn and qn in normalize(sentence)
                        and not _looks_like_table(sentence)):
                    return {
                        "page": i,
                        "level": "normalized",
                        "quote": sentence,
                        "context": _context_around(cp, start, len(sentence)),
                    }
            offset += len(segment) + 1
    return None


_CHINESE_GENERIC = {
    "本文提出", "我们提出", "实验结果表明", "结果表明", "本文介绍", "在本工作中",
    "本文研究了", "本文主要研究", "实验证明", "研究表明",
}


def _is_chinese(s: str) -> bool:
    cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    return cjk >= max(4, len(s) * 0.5)


def _valid_anchor(a: str) -> bool:
    """锚点必须特异：英文 ≥4 词/≥20 字符、含数字/专名/术语；中文 ≥8 个汉字；禁通用短语。"""
    if not a:
        return False
    if _is_chinese(a):
        cjk = sum(1 for ch in a if "\u4e00" <= ch <= "\u9fff")
        if cjk < 8:
            return False
        return not any(g in a for g in _CHINESE_GENERIC)
    if len(a) < 20 or len(a.split()) < 4:
        return False
    low = a.lower().strip()
    generic = {
        "in this paper", "we propose", "we show", "results show", "our method",
        "this work", "in this work", "we present", "experiments show", "our approach",
        "in this study", "we demonstrate", "we introduce", "to this end",
    }
    if any(g in low for g in generic):
        return False
    if re.search(r"\d", a):
        return True
    if re.search(r"\b[A-Z]{2,}\b", a):
        return True
    if re.search(r"\b[A-Z][A-Za-z]{2,}\b", a):
        return True
    if "-" in a:
        return True
    return False


def locate_anchor(pages: list[str], anchor: str, hint_quote: str = "", min_ratio: float = 0.5) -> dict | None:
    """锚点定位：单处命中直接扩句；多处命中用模型 quote 做语义提示选最接近的一句。

    min_ratio=0.5 只是"多候选句消歧"的相似度门槛，不是支持判定门槛；
    断言是否支撑 claim 由 entailment 复审决定。
    """
    a = _collapse(anchor)
    if not a:
        return None
    found: dict[str, tuple[int, str]] = {}
    for i, page in enumerate(pages, start=1):
        cp = _collapse(page)
        positions = [m.start() for m in re.finditer(re.escape(a), cp)]
        if not positions:
            positions = [m.start() for m in re.finditer(re.escape(a.casefold()), cp.casefold())]
        for pos in positions:
            sent = _expand_sentence(cp, pos)
            if sent and not _looks_like_table(sent):
                found.setdefault(normalize(sent), (i, sent))
    if len(found) == 1:
        page, sent = next(iter(found.values()))
        cp = _collapse(pages[page - 1])
        idx = cp.find(sent)
        ctx = _context_around(cp, idx, len(sent)) if idx >= 0 else None
        return {"page": page, "level": "anchored", "quote": sent, "context": ctx}
    if hint_quote:
        hn = normalize(hint_quote)
        best = None
        for key, (page, sent) in found.items():
            r = SequenceMatcher(None, key, hn, autojunk=False).ratio()
            if best is None or r > best[0]:
                best = (r, page, sent)
        if best and best[0] >= min_ratio:
            page, sent = best[1], best[2]
            cp = _collapse(pages[page - 1])
            idx = cp.find(sent)
            ctx = _context_around(cp, idx, len(sent)) if idx >= 0 else None
            return {"page": page, "level": "anchored", "quote": sent, "context": ctx}
    return None


def verify_quote(pages: list[str], quote: str):
    """兼容旧调用：返回 (verified, page, match_level)。"""
    res = locate_quote(pages, quote)
    if res:
        return True, res["page"], res["level"]
    return False, None, ""
