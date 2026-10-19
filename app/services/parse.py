"""PDF 分页文本提取：双栏感知（按文本块坐标分栏），降级 pypdf。"""
from __future__ import annotations

import re


def detect_language(text: str) -> str:
    """粗判语言：CJK 字符占比高则视为中文。"""
    if not text:
        return "en"
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return "zh" if cjk >= max(3, len(text) * 0.05) else "en"


def _page_text(page) -> str:
    """按文本块坐标分栏：标题/摘要等通栏块在前，左栏、右栏各自按 y 排序。"""
    width = page.rect.width
    blocks = []
    for b in page.get_text("blocks"):
        x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], (b[4] or "")
        if not text.strip():
            continue
        blocks.append({"x0": x0, "y0": y0, "x1": x1, "text": text})
    if not blocks:
        return page.get_text("text", sort=True)

    full, left, right = [], [], []
    for b in blocks:
        w = b["x1"] - b["x0"]
        cx = (b["x0"] + b["x1"]) / 2
        if w > 0.65 * width:
            full.append(b)
        elif cx < width * 0.5:
            left.append(b)
        else:
            right.append(b)

    two_col = bool(left) and bool(right)
    if two_col:
        seq = (
            sorted(full, key=lambda b: (b["y0"], b["x0"]))
            + sorted(left, key=lambda b: (b["y0"], b["x0"]))
            + sorted(right, key=lambda b: (b["y0"], b["x0"]))
        )
    else:
        seq = sorted(blocks, key=lambda b: (b["y0"], b["x0"]))
    return "\n\n".join(b["text"] for b in seq)  # 双换行 = 块边界，供上下文扩句使用


def _dehyphenate_doc(texts: list[str]) -> list[str]:
    """文档级断行连字符恢复：若 X-Y 是文档中真实存在的复合词则保留连字符，否则拼接。"""
    joined = "\n".join(texts)
    vocab = {
        (m.group(1) + "-" + m.group(2)).lower()
        for m in re.finditer(
            r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]*)-([A-Za-z][A-Za-z0-9]*)(?![A-Za-z0-9])",
            joined,
        )
    }

    def fix(t: str) -> str:
        return re.sub(
            r"([A-Za-z][A-Za-z0-9]*)-(\n)([A-Za-z][A-Za-z0-9]*)",
            lambda m: (
                m.group(1) + "-" + m.group(3)
                if (m.group(1) + "-" + m.group(3)).lower() in vocab
                else m.group(1) + m.group(3)
            ),
            t,
        )

    return [fix(t) for t in texts]


def extract_page_texts(pdf_path) -> tuple[list[str], str]:
    """返回 (page_texts, status)。page_texts 为 1-based 每页文本。"""
    pdf_path = str(pdf_path)
    status = "ok"
    texts: list[str] = []
    try:
        import pymupdf

        with pymupdf.open(pdf_path) as doc:
            texts = [_page_text(page) for page in doc]
        texts = _dehyphenate_doc(texts)
    except Exception:
        texts = []
        try:
            from pypdf import PdfReader

            reader = PdfReader(pdf_path)
            texts = [page.extract_text() or "" for page in reader.pages]
            status = "pypdf"
        except Exception as exc:  # noqa: BLE001
            return [], f"failed:{type(exc).__name__}"

    if not any(t.strip() for t in texts):
        status = "scanned_or_empty"
    return texts, status
