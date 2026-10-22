"""用本地 PDF 生成 demo 缓存：跑多次、取保留引用最多的一次（单次口径）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.pipeline import analyze  # noqa: E402
from app.services.metadata import backfill_pdf  # noqa: E402

ATTEMPTS = 3


def main() -> int:
    args = sys.argv[1:]
    if args and args[0].lower().endswith(".pdf"):
        query = "（本地 PDF 上传分析）"
        pdfs = [Path(a) for a in args]
    else:
        query = args[0] if args else "（本地 PDF 上传分析）"
        folder = Path(args[1]) if len(args) > 1 else PROJECT_ROOT / "data" / "papers"
        pdfs = sorted(folder.glob("*.pdf"))

    if not pdfs:
        print("no pdfs")
        return 1

    papers = []
    for f in pdfs:
        title, year, _src = backfill_pdf(f)
        papers.append({
            "id": "local:" + f.stem,
            "title": title,
            "year": year,
            "source": "upload",
            "pdf_path": str(f),
            "has_fulltext": True,
        })

    best = None
    for _ in range(ATTEMPTS):
        m = analyze(query, papers)
        if best is None or m["stats"]["kept"] > best["stats"]["kept"]:
            best = m

    cache_dir = PROJECT_ROOT / "data" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_papers = []
    for paper in papers:
        cached = dict(paper)
        path = Path(cached["pdf_path"])
        cached["pdf_path"] = str(path.relative_to(PROJECT_ROOT)) if path.is_relative_to(PROJECT_ROOT) else path.name
        cached_papers.append(cached)
    (cache_dir / "demo.json").write_text(
        json.dumps({"query": query, "papers": cached_papers, "matrix": best}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    s = best["stats"]
    print(
        f"papers={s['papers']} attempts={s['attempts']} kept={s['kept']} "
        f"hit_rate={s['quote_hit_rate']} discard={s['discard_rate']} "
        f"support_rate={s['support_rate']} completeness={s['field_completeness']}"
    )
    print("cache saved ->", cache_dir / "demo.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
