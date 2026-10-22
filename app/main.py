"""FastAPI 入口：异步任务 + 进度轮询。"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .logging_config import get_logger
from .services import pipeline
from .services import search as search_service
from .services.fetch import download_pdf
from .services.metadata import backfill_pdf

STATIC_DIR = Path(__file__).resolve().parent / "static"
UPLOAD_DIR = config.DATA_DIR / "papers"

app = FastAPI(title="有据 CiteProof")
JOBS: dict[str, dict] = {}
PAPER_REGISTRY: dict[str, dict] = {}
DEMO_MATRIX: dict | None = None
STATE_LOCK = threading.Lock()
MAX_ACTIVE_JOBS = 2
MAX_PAPERS_PER_JOB = 20
MAX_RETAINED_JOBS = 100
MAX_REGISTERED_PAPERS = 1000
MAX_ANALYSIS_CACHE = 50

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _register_paper(paper: dict) -> None:
    with STATE_LOCK:
        PAPER_REGISTRY[paper["id"]] = paper
        while len(PAPER_REGISTRY) > MAX_REGISTERED_PAPERS:
            PAPER_REGISTRY.pop(next(iter(PAPER_REGISTRY)))


def _analysis_cache_key(query: str, ids: list[str]) -> str:
    raw = query + "\n" + ",".join(sorted(ids))
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _analysis_cache_load(key: str):
    path = config.CACHE_DIR / f"analysis_{key}.json"
    if not path.exists():
        return None
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _analysis_cache_save(key: str, result: dict) -> None:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    final = config.CACHE_DIR / f"analysis_{key}.json"
    tmp = config.CACHE_DIR / f"analysis_{key}.json.tmp"
    tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, final)
    _prune_analysis_cache()


def _prune_analysis_cache() -> None:
    files = sorted(config.CACHE_DIR.glob("analysis_*.json"), key=lambda f: f.stat().st_mtime)
    while len(files) > MAX_ANALYSIS_CACHE:
        try:
            files.pop(0).unlink()
        except OSError:
            break


def _demo_paper(paper_id: str) -> dict | None:
    cache_file = config.CACHE_DIR / "demo.json"
    if not cache_file.exists():
        return None
    try:
        payload = json.load(open(cache_file, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    for paper in payload.get("papers") or []:
        if paper.get("id") == paper_id:
            return paper
    return None


def _locate_pdf(paper_id: str) -> str | None:
    paper = PAPER_REGISTRY.get(paper_id) or _demo_paper(paper_id)
    if not paper:
        return None
    pdf_path = paper.get("pdf_path")
    if pdf_path:
        path = Path(pdf_path)
        if not path.is_absolute():
            path = config.PROJECT_ROOT / path
        if path.exists():
            return str(path)
    pdf_url = paper.get("pdf_url")
    if pdf_url:
        name = Path(pdf_url.split("?")[0]).name or "paper.pdf"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        cached = config.CACHE_DIR / name
        if cached.exists():
            return str(cached)
        return download_pdf(pdf_url, config.CACHE_DIR)
    return None


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "demo_mode": config.DEMO_MODE,
        "llm_configured": config.llm_configured(),
    }


@app.get("/api/local")
def local_papers():
    papers = []
    if UPLOAD_DIR.exists():
        for f in sorted(UPLOAD_DIR.glob("*.pdf")):
            title, year, _src = backfill_pdf(f)
            paper = {
                "id": "local:" + f.stem,
                "title": title,
                "year": year,
                "source": "upload",
                "pdf_path": str(f),
                "has_fulltext": True,
            }
            papers.append(paper)
            _register_paper(paper)
    return {"papers": papers}


@app.post("/api/upload")
async def upload_papers(files: list[UploadFile] = File(...)):
    if len(files) > MAX_PAPERS_PER_JOB:
        raise HTTPException(status_code=400, detail="每次最多上传 20 篇 PDF")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    errors = []
    for f in files:
        name = Path((f.filename or "paper.pdf").replace("\\", "/")).name
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        content = await f.read(int(config.PDF_MAX_MB * 1024 * 1024) + 1)
        if len(content) > int(config.PDF_MAX_MB * 1024 * 1024):
            errors.append(f"{name}（超过 {config.PDF_MAX_MB:g}MB）")
            continue
        if content[:5] != b"%PDF-":
            errors.append(f"{name}（不是有效的 PDF）")
            continue
        stem = Path(name).stem
        dest = UPLOAD_DIR / f"{stem}-{uuid.uuid4().hex[:8]}.pdf"
        dest.write_bytes(content)
        title, year, _src = backfill_pdf(dest)
        paper = {
            "id": "local:" + dest.stem,
            "title": title,
            "year": year,
            "source": "upload",
            "pdf_path": str(dest),
            "has_fulltext": True,
        }
        saved.append(paper)
        _register_paper(paper)
    return {"papers": saved, "errors": errors}


@app.get("/api/demo")
def demo_cache():
    global DEMO_MATRIX
    cache_file = config.CACHE_DIR / "demo.json"
    if not cache_file.exists():
        return {"error": "没有缓存，请先运行 scripts/make_demo_cache_local.py"}
    payload = json.load(open(cache_file, encoding="utf-8"))
    matrix = payload.get("matrix")
    if not matrix:
        return {"error": "缓存内容为空"}
    DEMO_MATRIX = matrix
    return matrix


@app.get("/api/pdf/{paper_id:path}")
def pdf_endpoint(paper_id: str):
    pdf_path = _locate_pdf(paper_id)
    if not pdf_path or not Path(pdf_path).exists():
        raise HTTPException(status_code=404, detail="找不到 PDF 原文")
    safe = paper_id.replace("/", "-").replace("\\", "-")
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{safe}.pdf")


@app.post("/api/search")
def search_api(body: dict):
    query = str((body or {}).get("query", "")).strip()
    limit = max(1, min(MAX_PAPERS_PER_JOB, int((body or {}).get("limit", 10) or 10)))
    sort = str((body or {}).get("sort", "relevance"))
    papers, fallback = search_service.search_with_meta(query, limit, sort) if query else ([], False)
    for paper in papers:
        _register_paper(paper)
    return {"query": query, "papers": papers, "fallback": fallback}


def _run_job(job_id: str, query: str, papers: list[dict], cache_key: str | None = None):
    logger = get_logger("task")
    started = time.time()
    logger.info("analyze_start job_id=%s papers=%d query=%s", job_id, len(papers), query)

    def progress(stage: str, done: int, total: int):
        JOBS[job_id].update({"status": "running", "stage": stage, "done": done, "total": total})

    try:
        result = pipeline.analyze(query, papers, progress=progress)
        JOBS[job_id].update({"status": "done", "result": result, "done": len(papers)})
        if cache_key:
            _analysis_cache_save(cache_key, result)
        logger.info("analyze_ok job_id=%s papers=%d elapsed=%.3fs", job_id, len(papers), time.time() - started)
    except Exception as exc:  # noqa: BLE001
        JOBS[job_id].update({"status": "error", "error": str(exc)})
        logger.error(
            "analyze_failed job_id=%s papers=%d elapsed=%.3fs error=%s",
            job_id,
            len(papers),
            time.time() - started,
            exc,
        )


@app.post("/api/analyze")
def analyze_api(body: dict):
    query = str((body or {}).get("query", "")).strip()
    papers = (body or {}).get("papers") or []
    if not isinstance(papers, list) or not papers:
        raise HTTPException(status_code=400, detail="没有选择论文")
    if len(papers) > MAX_PAPERS_PER_JOB:
        raise HTTPException(status_code=400, detail="每次最多分析 20 篇论文")
    if any(not isinstance(p, dict) or set(p) != {"id"} or not isinstance(p["id"], str) for p in papers):
        raise HTTPException(status_code=400, detail="只接受已登记的论文标识")
    refresh = bool((body or {}).get("refresh"))
    cache_key = _analysis_cache_key(query, [p["id"] for p in papers])
    with STATE_LOCK:
        try:
            registered = [PAPER_REGISTRY[p["id"]].copy() for p in papers]
        except KeyError:
            raise HTTPException(status_code=400, detail="论文未登记，请重新检索或上传") from None
        if not refresh:
            cached = _analysis_cache_load(cache_key)
            if cached is not None:
                job_id = uuid.uuid4().hex
                JOBS[job_id] = {
                    "status": "done",
                    "stage": "done",
                    "done": len(registered),
                    "total": len(registered),
                    "result": cached,
                }
                return {"job_id": job_id}
        if sum(job["status"] in {"queued", "running"} for job in JOBS.values()) >= MAX_ACTIVE_JOBS:
            raise HTTPException(status_code=429, detail="当前分析任务已满，请稍后重试")
        for old_id in list(JOBS):
            if len(JOBS) < MAX_RETAINED_JOBS:
                break
            if JOBS[old_id]["status"] in {"done", "error"}:
                del JOBS[old_id]
        job_id = uuid.uuid4().hex
        JOBS[job_id] = {"status": "queued", "stage": "prepare", "done": 0, "total": len(registered), "result": None}
    threading.Thread(target=_run_job, args=(job_id, query, registered, cache_key), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
def job_status(job_id: str):
    return JOBS.get(job_id, {"status": "unknown"})


@app.get("/api/export")
def export_api(job_id: str, format: str = "xlsx"):
    from pathlib import Path as _Path

    from .models import Matrix
    from .services.export import export_matrix

    result = DEMO_MATRIX if job_id == "demo" else JOBS.get(job_id, {}).get("result")
    if not result:
        raise HTTPException(status_code=404, detail="未找到已完成的矩阵")
    matrix = Matrix(**result)
    out = export_matrix(matrix, config.DATA_DIR / "tmp" / job_id / uuid.uuid4().hex)
    path = {"csv": out["csv"], "xlsx": out["xlsx"], "docx": out["docx"]}.get(format, out["xlsx"])
    return FileResponse(path, filename=job_id + "-" + _Path(path).name)


@app.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"name": "有据 CiteProof", "status": "已就绪"}
