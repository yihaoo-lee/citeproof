"""组装矩阵与统计；多篇并发处理，带进度回调。"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import config
from ..models import Claim, FIELD_NAMES, Matrix, MatrixRow, Stats
from .entail import judge_claims
from .extract import LLMCallError, extract_fields_and_quotes
from .verify import _valid_anchor, locate_anchor, locate_quote, normalize


def _rate(hit: int, total: int) -> float:
    return round(hit / total, 4) if total else 0.0


def _evidence_level(abstract: str, quote: str) -> str:
    """quote 能比对进 abstract 字段文本 → abstract，否则 fulltext（不用页码猜）。"""
    if abstract and quote and normalize(quote) in normalize(abstract):
        return "abstract"
    return "fulltext"


def _build_row(paper: dict):
    pages = paper.get("pages") or []
    abstract = paper.get("abstract", "")
    fields, quotes, anchors, stub, partial = extract_fields_and_quotes(pages, paper)
    nonempty = sum(1 for f in FIELD_NAMES if fields.get(f))
    if stub:
        if config.DEMO_MODE:
            stub_reason = "演示模式（未调用模型）"
        elif config.llm_configured():
            stub_reason = "模型调用失败，降级启发式抽取"
        else:
            stub_reason = "未配置 LLM key，启发式抽取"
    else:
        stub_reason = ""

    evidence: dict[str, dict] = {}
    for field, quote in quotes:
        evidence.setdefault(field, {})["quote"] = quote
    for field, anchor in anchors:
        evidence.setdefault(field, {})["anchor"] = anchor

    claims = []
    attempts = kept = 0
    for field in FIELD_NAMES:
        ev = evidence.get(field)
        if not ev:
            continue
        attempts += 1
        res = locate_quote(pages, ev.get("quote", ""))
        if res:
            kept += 1
            claims.append(Claim(
                field=field,
                quote=res["quote"],
                page=res["page"],
                verified=True,
                match_level=res["level"],
                evidence_level=_evidence_level(abstract, res["quote"]),
                proposal="" if stub else (ev.get("quote", "") or ""),
                anchor="" if stub else (ev.get("anchor", "") or ""),
                context="" if stub else (res.get("context") or ""),
            ))
            continue
        anchor = ev.get("anchor", "")
        if _valid_anchor(anchor):
            ares = locate_anchor(pages, anchor, hint_quote=ev.get("quote", ""))
            if ares:
                kept += 1
                claims.append(Claim(
                    field=field,
                    quote=ares["quote"],
                    page=ares["page"],
                    verified=True,
                    match_level="anchored",
                    evidence_level=_evidence_level(abstract, ares["quote"]),
                    proposal="" if stub else (ev.get("quote", "") or ""),
                    anchor="" if stub else (ev.get("anchor", "") or ""),
                    context="" if stub else (ares.get("context") or ""),
                ))

    judged = supported = 0
    if claims and (not stub) and config.llm_configured():
        items = [
            {"id": i, "field": c.field, "claim": fields.get(c.field, ""), "quote": c.quote}
            for i, c in enumerate(claims)
        ]
        verdicts = judge_claims(items)
        for c, v in zip(claims, verdicts):
            c.entailment = v["entailment"]
            c.reason = v["reason"]
            judged += 1
            if v["entailment"] == "supported":
                supported += 1

    row = MatrixRow(
        paper_id=paper.get("id", ""),
        title=paper.get("title", ""),
        year=paper.get("year"),
        language=paper.get("language", "en"),
        parse_status=paper.get("parse_status", ""),
        stub_reason=stub_reason,
        fields=fields,
        claims=claims,
        stub=stub,
        partial=partial,
    )
    return row, attempts, kept, nonempty, judged, supported


def build_matrix(query: str, papers: list[dict], progress=None, concurrency: int = 3) -> Matrix:
    """papers: [{id,title,year,authors,url,abstract,source,language,pages,parse_status}]"""
    start = time.perf_counter()
    attempts = kept = judged = supported = nonempty = 0
    total = len(papers)
    results: list = [None] * total
    done = 0

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {ex.submit(_build_row, p): i for i, p in enumerate(papers)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except LLMCallError:
                raise
            except Exception:  # noqa: BLE001
                p = papers[i]
                results[i] = (
                    MatrixRow(
                        paper_id=p.get("id", ""),
                        title=p.get("title", ""),
                        year=p.get("year"),
                        language=p.get("language", "en"),
                        parse_status=p.get("parse_status", ""),
                    ),
                    0,
                    0,
                    0,
                    0,
                    0,
                )
            done += 1
            if progress:
                progress("analyze", done, total)

    rows = []
    for (row, a, k, nf, j, sp) in results:
        rows.append(row)
        attempts += a
        kept += k
        nonempty += nf
        judged += j
        supported += sp

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    stats = Stats(
        papers=len(rows),
        attempts=attempts,
        kept=kept,
        quote_hit_rate=_rate(kept, attempts),
        discard_rate=_rate(attempts - kept, attempts),
        support_rate=_rate(supported, judged),
        field_completeness=_rate(nonempty, len(rows) * len(FIELD_NAMES)),
        elapsed_ms=elapsed_ms,
    )
    return Matrix(
        query=query,
        generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        rows=rows,
        stats=stats,
    )
