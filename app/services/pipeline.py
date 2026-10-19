"""端到端：下载/解析 → 并发抽取/校验/语义判断 → 矩阵。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .. import config
from .fetch import download_pdf
from .matrix import build_matrix
from .parse import extract_page_texts
from .synthesize import synthesize


def _prepare(paper: dict) -> dict:
    p = dict(paper)
    pages: list[str] = []
    status = "abstract_only"

    pdf_path = p.get("pdf_path", "")
    pdf_url = p.get("pdf_url", "")
    if pdf_path and Path(pdf_path).exists():
        pages, pstatus = extract_page_texts(pdf_path)
        status = "uploaded" if pstatus in ("ok", "pypdf") else pstatus
    elif pdf_url:
        path = download_pdf(pdf_url, config.CACHE_DIR)
        if path:
            pages, pstatus = extract_page_texts(path)
            status = "downloaded" if pstatus in ("ok", "pypdf") else pstatus
        else:
            status = "download_failed"

    if not any(t.strip() for t in pages):
        pages = [p.get("abstract", "")]
        if status in ("uploaded", "downloaded"):
            status = "scanned_or_empty"

    p["pages"] = pages
    p["parse_status"] = status
    return p


def analyze(query: str, papers: list[dict], progress=None) -> dict:
    total = len(papers)
    prepared: list[dict | None] = [None] * total
    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_prepare, p): i for i, p in enumerate(papers)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                prepared[i] = fut.result()
            except Exception:  # noqa: BLE001
                p = dict(papers[i])
                p["pages"] = [p.get("abstract", "")]
                p["parse_status"] = "failed"
                prepared[i] = p
            done += 1
            if progress:
                progress("prepare", done, total)
    matrix = build_matrix(query, prepared, progress=progress).model_dump()
    matrix["synthesis"] = synthesize(matrix["rows"])
    return matrix
