"""本地 PDF 元数据回填：PDF metadata → ACL Anthology / arXiv → 文件名兜底。"""
from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

from .. import config

_ARXIV_ID = re.compile(r"^(\d{4}\.\d{4,5})(?:v\d+)?(?:\s*\(\d+\))?$")
_ACL_ID = re.compile(r"^(\d{4})\.([a-z0-9]+-[a-z0-9]+)\.(\d+)$")
_CACHE_FILE = config.CACHE_DIR / "local_meta.json"


def _load_cache() -> dict:
    try:
        return json.load(open(_CACHE_FILE, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _pdf_meta(path: Path) -> tuple[str, int | None]:
    title = ""
    year = None
    try:
        import pymupdf

        with pymupdf.open(str(path)) as doc:
            meta = doc.metadata or {}
            title = (meta.get("title") or "").strip()
            for key in ("creationDate", "modDate"):
                m = re.search(r"D:(\d{4})", meta.get(key) or "")
                if m:
                    year = int(m.group(1))
                    break
    except Exception:  # noqa: BLE001
        pass
    return title, year


def _meaningful(title: str, stem: str) -> bool:
    if not title:
        return False
    t = title.strip()
    if t.lower() == stem.lower():
        return False
    if re.match(r"^\d{4}\.\d{4,5}", t):
        return False
    if re.match(r"^(untitled|no title|microsoft word|document)\b", t, re.IGNORECASE):
        return False
    return len(t) >= 8


def _fetch_acl(stem: str) -> tuple[str, int | None]:
    m = _ACL_ID.match(stem)
    if not m:
        return "", None
    year = int(m.group(1))
    try:
        r = httpx.get(
            f"https://aclanthology.org/{stem}/",
            timeout=httpx.Timeout(connect=8.0, read=12.0, write=10.0, pool=8.0),
            follow_redirects=True,
        )
        r.raise_for_status()
        tm = re.search(r'<meta name="citation_title" content="([^"]+)"', r.text)
        if tm:
            return re.sub(r"\s+", " ", tm.group(1)).strip(), year
        tm = re.search(r"<title>([^<]+)</title>", r.text, re.IGNORECASE)
        if tm:
            title = re.sub(r"\s*-\s*ACL Anthology\s*$", "", tm.group(1), flags=re.IGNORECASE)
            title = re.sub(r"\s+", " ", title).strip()
            if title:
                return title, year
    except Exception:  # noqa: BLE001
        pass
    return "", None


def _fetch_arxiv(stem: str) -> tuple[str, int | None]:
    m = _ARXIV_ID.match(stem)
    if not m:
        return "", None
    arxiv_id = m.group(1)
    try:
        r = httpx.get(
            "https://export.arxiv.org/api/query",
            params={"id_list": arxiv_id},
            timeout=httpx.Timeout(connect=8.0, read=12.0, write=10.0, pool=8.0),
            follow_redirects=True,
        )
        r.raise_for_status()
        import xml.etree.ElementTree as ET

        ns = {"a": "http://www.w3.org/2005/Atom"}
        entry = ET.fromstring(r.text).find("a:entry", ns)
        if entry is None:
            return "", None
        title = re.sub(r"\s+", " ", entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        published = entry.findtext("a:published", default="", namespaces=ns) or ""
        year = int(published[:4]) if len(published) >= 4 else None
        if title:
            return title, year
    except Exception:  # noqa: BLE001
        pass
    return "", None


def backfill_pdf(path) -> tuple[str, int | None, str]:
    """返回 (title, year, source)。优先级：PDF metadata → ACL → arXiv → 文件名。"""
    path = Path(path)
    stem = path.stem
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0
    cache = _load_cache()
    c = cache.get(stem)
    if c and abs(float(c.get("mtime", 0)) - mtime) < 1:
        return c.get("title", stem), c.get("year"), c.get("source", "cache")

    title, year = _pdf_meta(path)
    source = "pdf_meta"
    if not _meaningful(title, stem):
        title, year = "", None
        title, year = _fetch_acl(stem)
        source = "aclanthology"
        if not title:
            title, year = _fetch_arxiv(stem)
            source = "arxiv"
    if not title:
        title, year = stem, year
        source = "filename"

    cache[stem] = {"title": title, "year": year, "source": source, "mtime": mtime}
    _save_cache(cache)
    return title, year, source
