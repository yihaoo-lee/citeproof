"""生成现场兜底缓存：真实检索 + 抽取 + 校验 + 语义判断，存 data/cache/demo.json。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.pipeline import analyze  # noqa: E402
from app.services.search import search  # noqa: E402

DEFAULT_QUERY = "solid-state battery interface"


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERY
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    papers = search(query, n)
    if not papers:
        print("no papers found")
        return 1

    with_pdf = [p for p in papers if p.get("pdf_url")]
    chosen = with_pdf[:n] if len(with_pdf) >= 3 else papers[:n]
    matrix = analyze(query, chosen)

    cache_dir = PROJECT_ROOT / "data" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {"query": query, "papers": chosen, "matrix": matrix}
    (cache_dir / "demo.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    s = matrix["stats"]
    print(
        f"papers={s['papers']} attempts={s['attempts']} kept={s['kept']} "
        f"hit_rate={s['quote_hit_rate']} discard={s['discard_rate']} "
        f"support_rate={s['support_rate']} completeness={s['field_completeness']}"
    )
    print("cache saved ->", cache_dir / "demo.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
