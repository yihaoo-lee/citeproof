"""PDF 下载：超时、大小上限、Content-Type 校验。"""
from __future__ import annotations

import time
from pathlib import Path

import httpx

from .. import config


def download_pdf(url: str, dest_dir, filename: str = "") -> str | None:
    if not url:
        return None
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        timeout = httpx.Timeout(connect=6.0, read=12.0, write=10.0, pool=6.0)
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as resp:
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            max_bytes = int(config.PDF_MAX_MB * 1024 * 1024)
            total = 0
            chunks: list[bytes] = []
            started = time.time()
            for chunk in resp.iter_bytes():
                if time.time() - started > 15.0:  # 单篇硬上限，慢流也切断
                    return None
                total += len(chunk)
                if total > max_bytes:
                    return None
                chunks.append(chunk)
            data = b"".join(chunks)

        if data[:5] != b"%PDF-" and "pdf" not in ctype.lower():
            return None

        name = filename or Path(url.split("?")[0]).name or "paper.pdf"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        path = dest_dir / name
        path.write_bytes(data)
        return str(path)
    except Exception:  # noqa: BLE001
        return None
