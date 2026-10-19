"""FastAPI 入口：异步任务 + 进度轮询。"""
from __future__ import annotations

import threading
import uuid
import json
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .services import pipeline
from .services import search as search_service
from .services.metadata import backfill_pdf

STATIC_DIR = Path(__file__).resolve().parent / "static"
UPLOAD_DIR = config.DATA_DIR / "papers"

app = FastAPI(title="有据 CiteProof")
LAST_MATRIX: dict | None = None
JOBS: dict[str, dict] = {}

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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
            papers.append({
                "id": "local:" + f.stem,
                "title": title,
                "year": year,
                "source": "upload",
                "pdf_path": str(f),
                "has_fulltext": True,
            })
    return {"papers": papers}


@app.post("/api/upload")
async def upload_papers(files: list[UploadFile] = File(...)):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    errors = []
    for f in files:
        name = Path(f.filename or "paper.pdf").name  # 只取 basename，防路径穿越
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        content = await f.read()
        if len(content) > int(config.PDF_MAX_MB * 1024 * 1024):
            errors.append(f"{name}（超过 {config.PDF_MAX_MB:g}MB）")
            continue
        if content[:5] != b"%PDF-":
            errors.append(f"{name}（不是有效的 PDF）")
            continue
        dest = UPLOAD_DIR / name
        dest.write_bytes(content)
        title, year, _src = backfill_pdf(dest)
        saved.append({
            "id": "local:" + dest.stem,
            "title": title,
            "year": year,
            "source": "upload",
            "pdf_path": str(dest),
            "has_fulltext": True,
        })
    return {"papers": saved, "errors": errors}


@app.get("/api/demo")
def demo_cache():
    global LAST_MATRIX
    cache_file = config.CACHE_DIR / "demo.json"
    if not cache_file.exists():
        return {"error": "没有缓存，请先运行 scripts/make_demo_cache_local.py"}
    payload = json.load(open(cache_file, encoding="utf-8"))
    matrix = payload.get("matrix")
    if not matrix:
        return {"error": "缓存内容为空"}
    LAST_MATRIX = matrix  # 让离线演示后的导出与屏幕一致
    return matrix


@app.post("/api/search")
def search_api(body: dict):
    query = str((body or {}).get("query", "")).strip()
    limit = int((body or {}).get("limit", 10) or 10)
    sort = str((body or {}).get("sort", "relevance"))
    papers, fallback = search_service.search_with_meta(query, limit, sort) if query else ([], False)
    return {"query": query, "papers": papers, "fallback": fallback}


def _run_job(job_id: str, query: str, papers: list[dict]):
    global LAST_MATRIX

    def progress(stage: str, done: int, total: int):
        JOBS[job_id].update({"status": "running", "stage": stage, "done": done, "total": total})

    try:
        result = pipeline.analyze(query, papers, progress=progress)
        JOBS[job_id].update({"status": "done", "result": result, "done": len(papers)})
        LAST_MATRIX = result
    except Exception as exc:  # noqa: BLE001
        JOBS[job_id].update({"status": "error", "error": str(exc)})


@app.post("/api/analyze")
def analyze_api(body: dict):
    query = str((body or {}).get("query", "")).strip()
    papers = (body or {}).get("papers") or []
    if not papers:
        raise HTTPException(status_code=400, detail="没有选择论文")
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "queued", "stage": "prepare", "done": 0, "total": len(papers), "result": None}
    threading.Thread(target=_run_job, args=(job_id, query, papers), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
def job_status(job_id: str):
    return JOBS.get(job_id, {"status": "unknown"})


@app.get("/api/export")
def export_api(format: str = "xlsx"):
    from pathlib import Path as _Path

    from .models import Matrix
    from .services.export import export_matrix

    if not LAST_MATRIX:
        return {"error": "还没有生成矩阵"}
    matrix = Matrix(**LAST_MATRIX)
    out = export_matrix(matrix, config.DATA_DIR / "tmp")
    path = {"csv": out["csv"], "xlsx": out["xlsx"], "docx": out["docx"]}.get(format, out["xlsx"])
    return FileResponse(path, filename=_Path(path).name)


@app.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"name": "有据 CiteProof", "status": "已就绪"}
