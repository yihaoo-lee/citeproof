"""从 arXiv 批量下载并按解析质量挑选论文，存入 data/papers。

用法：python scripts/pick_arxiv_demo.py <检索词> [候选数=12] [保留数=3]
说明：下载与解析需要能访问 arxiv.org 的网络环境；挑完后再运行 make_demo_cache_local.py 生成缓存。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.fetch import download_pdf  # noqa: E402
from app.services.parse import extract_page_texts  # noqa: E402
from app.services.search import search_arxiv  # noqa: E402


def _quality(pdf_path) -> int:
    pages, status = extract_page_texts(pdf_path)
    if status not in ("ok", "pypdf") or len(pages) < 3:
        return -1
    joined = "".join(pages)
    if "\ufffd" in joined:
        return -1
    p0 = pages[0]
    alpha = sum(c.isalpha() for c in p0)
    if alpha < 600:
        return -1
    digits = sum(c.isdigit() for c in joined)
    if digits / max(1, len(joined)) > 0.06:
        return -1
    return alpha + sum(len(p) for p in pages[1:4])


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "retrieval augmented generation"
    candidates = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    keep = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    out_dir = PROJECT_ROOT / "data" / "papers"
    pool_dir = PROJECT_ROOT / "data" / "cache" / "pool"
    out_dir.mkdir(parents=True, exist_ok=True)

    papers = search_arxiv(query, candidates)
    scored = []
    for p in papers:
        safe = re.sub(r"[^\w.-]+", "_", p["id"]) + ".pdf"
        path = download_pdf(p.get("pdf_url", ""), pool_dir, safe)
        if not path:
            continue
        q = _quality(path)
        if q >= 0:
            scored.append((q, p, path))

    scored.sort(key=lambda x: -x[0])
    kept = []
    for q, p, path in scored[:keep]:
        dest = out_dir / (re.sub(r"[^\w.-]+", "_", p["id"]) + ".pdf")
        Path(path).replace(dest)
        kept.append(dest.name)
        print("keep", dest.name, "score", q)

    print(f"kept {len(kept)}/{len(papers)}")
    return 0 if kept else 1


if __name__ == "__main__":
    sys.exit(main())
