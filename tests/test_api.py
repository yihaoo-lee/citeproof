import copy
import csv
import io
import json

from fastapi.testclient import TestClient

from app import main
from app.services.extract import LLMCallError


class _NoopThread:
    def __init__(self, target, args, daemon):
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self):
        pass


def test_analyze_rejects_forged_file_and_url(monkeypatch):
    client = TestClient(main.app)
    for paper in ({"id": "fake", "pdf_path": "C:/Windows/win.ini"}, {"id": "fake", "pdf_url": "http://127.0.0.1/"}):
        response = client.post("/api/analyze", json={"query": "test", "papers": [paper]})
        assert response.status_code == 400


def test_analyze_rejects_more_than_twenty_papers():
    client = TestClient(main.app)
    response = client.post("/api/analyze", json={"papers": [{"id": str(i)} for i in range(21)]})
    assert response.status_code == 400


def test_upload_rejects_more_than_twenty_files():
    files = [("files", (f"{index}.pdf", b"%PDF-1.4", "application/pdf")) for index in range(21)]
    response = TestClient(main.app).post("/api/upload", files=files)
    assert response.status_code == 400


def test_export_uses_requested_job_and_demo_snapshot(tmp_path, monkeypatch):
    client = TestClient(main.app)
    monkeypatch.setattr(main.config, "DATA_DIR", tmp_path)
    first = {"query": "first", "rows": [{"paper_id": "a", "title": "First paper"}], "stats": {}}
    second = {"query": "second", "rows": [{"paper_id": "b", "title": "Second paper"}], "stats": {}}
    monkeypatch.setattr(main, "JOBS", {"job-a": {"status": "done", "result": first}, "job-b": {"status": "done", "result": second}})
    monkeypatch.setattr(main, "DEMO_MATRIX", copy.deepcopy(first), raising=False)
    a = client.get("/api/export?format=csv&job_id=job-a")
    b = client.get("/api/export?format=csv&job_id=job-b")
    demo = client.get("/api/export?format=csv&job_id=demo")
    assert a.status_code == b.status_code == demo.status_code == 200
    assert "job-a" in a.headers["content-disposition"]
    assert "job-b" in b.headers["content-disposition"]
    assert a.content != b.content
    assert demo.content == a.content


def test_analyze_rejects_when_active_limit_reached(monkeypatch):
    monkeypatch.setattr(main, "JOBS", {"a": {"status": "running"}, "b": {"status": "queued"}})
    monkeypatch.setattr(main, "PAPER_REGISTRY", {"ok": {"id": "ok", "title": "Paper"}}, raising=False)
    response = TestClient(main.app).post("/api/analyze", json={"papers": [{"id": "ok"}]})
    assert response.status_code == 429


def test_analyze_uses_server_registered_paper(monkeypatch):
    submitted = []

    class FakeThread:
        def __init__(self, target, args, daemon):
            submitted.append(args)

        def start(self):
            pass

    monkeypatch.setattr(main.threading, "Thread", FakeThread)
    monkeypatch.setattr(main, "JOBS", {})
    monkeypatch.setattr(main, "PAPER_REGISTRY", {"p1": {"id": "p1", "title": "Trusted", "pdf_url": "https://arxiv.org/pdf/1234.56789"}})
    response = TestClient(main.app).post("/api/analyze", json={"papers": [{"id": "p1"}]})
    assert response.status_code == 200
    assert submitted[0][2] == [{"id": "p1", "title": "Trusted", "pdf_url": "https://arxiv.org/pdf/1234.56789"}]


def test_concurrent_exports_get_distinct_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(main.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "JOBS", {"same": {"status": "done", "result": {"rows": [], "stats": {}}}})
    first = main.export_api(job_id="same", format="csv")
    second = main.export_api(job_id="same", format="csv")
    assert first.path != second.path


def test_real_demo_export_matches_cached_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(main.config, "DATA_DIR", tmp_path)
    client = TestClient(main.app)
    demo = client.get("/api/demo").json()
    exported = client.get("/api/export?job_id=demo&format=csv")
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert exported.status_code == 200
    assert [row["paper_id"] for row in rows] == [row["paper_id"] for row in demo["rows"]]


def test_model_error_is_visible_in_job_status(monkeypatch):
    def fail(*args, **kwargs):
        raise LLMCallError("模型调用超时，请重试")

    monkeypatch.setattr(main.pipeline, "analyze", fail)
    monkeypatch.setattr(main, "JOBS", {"job": {"status": "queued"}})
    main._run_job("job", "query", [{"id": "p1"}])
    status = TestClient(main.app).get("/api/job/job").json()
    assert status["status"] == "error"
    assert "超时" in status["error"]


def test_upload_same_name_does_not_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(main.config, "CACHE_DIR", tmp_path / "cache")
    client = TestClient(main.app)
    first = client.post("/api/upload", files=[("files", ("same.pdf", b"%PDF-1.4", "application/pdf"))])
    second = client.post("/api/upload", files=[("files", ("same.pdf", b"%PDF-1.4", "application/pdf"))])
    assert first.status_code == second.status_code == 200
    p1 = first.json()["papers"][0]
    p2 = second.json()["papers"][0]
    assert p1["id"] != p2["id"]
    assert p1["pdf_path"] != p2["pdf_path"]
    assert len(list(tmp_path.glob("*.pdf"))) == 2


def test_analyze_cache_hit_and_refresh(monkeypatch, tmp_path):
    monkeypatch.setattr(main.config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(main, "PAPER_REGISTRY", {"p1": {"id": "p1", "title": "T", "pdf_url": "https://arxiv.org/pdf/1234.56789"}}, raising=False)
    monkeypatch.setattr(main, "JOBS", {})
    key = main._analysis_cache_key("q", ["p1"])
    (tmp_path / f"analysis_{key}.json").write_text(json.dumps({"query": "q", "rows": [], "stats": {}}), encoding="utf-8")

    client = TestClient(main.app)
    resp = client.post("/api/analyze", json={"query": "q", "papers": [{"id": "p1"}]})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    assert main.JOBS[job_id]["status"] == "done"
    assert main.JOBS[job_id]["result"]["query"] == "q"

    main.JOBS.clear()
    monkeypatch.setattr(main.threading, "Thread", _NoopThread)
    resp2 = client.post("/api/analyze", json={"query": "q", "papers": [{"id": "p1"}], "refresh": True})
    assert resp2.status_code == 200
    job_id2 = resp2.json()["job_id"]
    assert main.JOBS[job_id2]["status"] == "queued"
