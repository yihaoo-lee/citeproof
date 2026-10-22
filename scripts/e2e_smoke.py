"""端到端 smoke 测试：连接本地服务，依次验证健康、检索、分析、导出。"""
from __future__ import annotations

import os
import sys
import time

import httpx

BASE_URL = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
QUERY = "large language model hallucination"
TIMEOUT = 300


def _step(name: str, ok: bool) -> bool:
    print(("PASS " if ok else "FAIL ") + name)
    return ok


def main() -> int:
    client = httpx.Client(timeout=60)
    try:
        health = client.get(f"{BASE_URL}/api/health")
    except Exception as exc:  # noqa: BLE001
        print(f"无法连接 {BASE_URL}: {exc}")
        return 1
    if health.status_code != 200 or not health.json().get("ok"):
        _step("GET /api/health", False)
        return 1
    _step("GET /api/health", True)

    try:
        search = client.post(f"{BASE_URL}/api/search", json={"query": QUERY, "limit": 5, "sort": "relevance"})
    except Exception as exc:  # noqa: BLE001
        print(f"检索失败: {exc}")
        return 1
    papers = search.json().get("papers") or []
    if search.status_code != 200 or not papers:
        _step("POST /api/search", False)
        return 1
    _step(f"POST /api/search（{len(papers)} 篇）", True)

    first = papers[0]
    try:
        analyze = client.post(f"{BASE_URL}/api/analyze", json={"query": QUERY, "papers": [{"id": first["id"]}]})
    except Exception as exc:  # noqa: BLE001
        print(f"分析失败: {exc}")
        return 1
    if analyze.status_code != 200:
        _step("POST /api/analyze", False)
        print(analyze.text)
        return 1
    job_id = analyze.json().get("job_id")
    if not job_id:
        _step("POST /api/analyze（无 job_id）", False)
        return 1
    _step("POST /api/analyze", True)

    status = {}
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        try:
            status = client.get(f"{BASE_URL}/api/job/{job_id}").json()
        except Exception as exc:  # noqa: BLE001
            print(f"轮询失败: {exc}")
            return 1
        if status.get("status") in {"done", "error"}:
            break
        time.sleep(2)
    if status.get("status") != "done":
        _step(f"轮询任务（{status.get('status')}）", False)
        print(status)
        return 1
    _step("轮询任务至 done", True)

    export = client.get(f"{BASE_URL}/api/export", params={"job_id": job_id, "format": "csv"})
    if export.status_code != 200:
        _step("GET /api/export", False)
        return 1
    _step("GET /api/export（CSV）", True)

    print("e2e smoke OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
