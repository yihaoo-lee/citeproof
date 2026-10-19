"""检索层：OpenAlex 为主 + arXiv 兜底；中文问题可经 LLM 转英文检索词。"""
from __future__ import annotations

import re
import functools

import httpx

from .. import config

OPENALEX_SEARCH = "https://api.openalex.org/works"
ARXIV_API = "https://export.arxiv.org/api/query"


def _norm_title(title: str) -> str:
    return re.sub(r"\W+", "", (title or "").lower())


def _reconstruct_abstract(inv) -> str:
    if not inv:
        return ""
    pos: dict[int, str] = {}
    for word, positions in inv.items():
        for p in positions:
            pos[p] = word
    return " ".join(pos[i] for i in sorted(pos))


def search_openalex(query: str, limit: int = 30) -> list[dict]:
    params = {
        "search": query,
        "per-page": str(min(50, max(limit, 30))),
        "mailto": config.OPENALEX_MAILTO or "example@example.com",
        "filter": "open_access.is_oa:true",
    }
    resp = httpx.get(
        OPENALEX_SEARCH,
        params=params,
        timeout=httpx.Timeout(connect=8.0, read=12.0, write=10.0, pool=8.0),
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])

    papers = []
    for w in results:
        doi = (w.get("doi") or "").replace("https://doi.org/", "")
        oa = w.get("open_access") or {}
        best = w.get("best_oa_location") or {}
        primary = w.get("primary_location") or {}
        pdf_url = best.get("pdf_url") or primary.get("pdf_url") or ""
        venue = ((primary.get("source") or {}).get("display_name") or "")
        authors = [
            a.get("author", {}).get("display_name", "")
            for a in (w.get("authorships") or [])
        ]
        authors = [a for a in authors if a]
        papers.append({
            "id": doi or (w.get("id") or ""),
            "title": (w.get("title") or w.get("display_name") or "").strip(),
            "year": w.get("publication_year"),
            "authors": authors,
            "url": f"https://doi.org/{doi}" if doi else (w.get("id") or ""),
            "abstract": _reconstruct_abstract(w.get("abstract_inverted_index")),
            "source": "openalex",
            "venue": venue,
            "cited_by_count": w.get("cited_by_count") or 0,
            "pdf_url": pdf_url,
            "is_oa": bool(oa.get("is_oa")),
            "has_fulltext": bool(pdf_url),
        })
    return papers


def _arxiv_to_paper(entry) -> dict:
    ns = {"a": "http://www.w3.org/2005/Atom"}

    def txt(xpath: str, default: str = "") -> str:
        node = entry.find(xpath, ns)
        return (node.text or "").strip() if node is not None and node.text else default

    title = re.sub(r"\s+", " ", txt("a:title"))
    summary = re.sub(r"\s+", " ", txt("a:summary"))
    link = txt("a:id")
    arxiv_id = re.sub(r"v\d+$", "", link.rstrip("/").split("/abs/")[-1])
    published = txt("a:published")
    year = int(published[:4]) if len(published) >= 4 else None
    authors = [
        n.text.strip() for n in entry.findall("a:author/a:name", ns) if n.text and n.text.strip()
    ]
    return {
        "id": f"arxiv:{arxiv_id}",
        "title": title,
        "year": year,
        "authors": authors,
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "abstract": summary,
        "source": "arxiv",
        "venue": "arXiv",
        "cited_by_count": None,
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
        "is_oa": True,
        "has_fulltext": True,
    }


def search_arxiv(query: str, limit: int = 10) -> list[dict]:
    params = {"search_query": f"all:{query}", "max_results": str(limit)}
    resp = httpx.get(
        ARXIV_API, params=params, timeout=config.HTTP_TIMEOUT, follow_redirects=True
    )
    resp.raise_for_status()
    import xml.etree.ElementTree as ET

    root = ET.fromstring(resp.text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    return [_arxiv_to_paper(e) for e in root.findall("a:entry", ns)][:limit]


@functools.lru_cache(maxsize=64)
def translate_query(query: str) -> str:
    """中文问题转英文检索短语；英文或无 key 时原样返回。"""
    if not config.llm_configured():
        return query
    from .parse import detect_language

    if detect_language(query) != "zh":
        return query

    prompt = (
        "把下面的中文研究问题翻译成用于学术检索的英文短语：去掉语气词，保留关键术语，"
        "只输出一个英文短语。\n" + query
    )
    payload = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
    }
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}
    try:
        resp = httpx.post(
            f"{config.LLM_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=config.HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        out = resp.json()["choices"][0]["message"]["content"].strip()
        return out or query
    except Exception:  # noqa: BLE001
        return query


def search_with_meta(query: str, limit: int = 10, sort: str = "relevance") -> tuple[list[dict], bool]:
    """主入口：OpenAlex 优先，结果太少时用 arXiv 补充；返回 (论文, 是否用了兜底)。"""
    q = translate_query(query)
    merged: list[dict] = []
    seen: set[str] = set()
    used_fallback = False

    def add(papers):
        for p in papers:
            key = _norm_title(p.get("title", ""))
            if key and key not in seen:
                seen.add(key)
                merged.append(p)

    try:
        add(search_openalex(q, max(limit, 30)))
    except Exception:  # noqa: BLE001
        used_fallback = True

    if len(merged) < 3:
        try:
            add(search_arxiv(q, max(5, limit)))
            used_fallback = True
        except Exception:  # noqa: BLE001
            pass

    if sort == "date":
        merged.sort(key=lambda p: -(p.get("year") or 0))
    elif sort == "cited":
        merged.sort(key=lambda p: -(p.get("cited_by_count") or 0))
    return merged[:limit], used_fallback


def search(query: str, limit: int = 10, sort: str = "relevance") -> list[dict]:
    """兼容旧调用：只返回论文列表。"""
    return search_with_meta(query, limit, sort)[0]
