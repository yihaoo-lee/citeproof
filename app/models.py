"""Pydantic 数据结构。"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

FIELD_NAMES = ["problem", "method", "dataset", "conclusion", "limitation", "reproducibility"]


class Paper(BaseModel):
    id: str
    title: str
    year: Optional[int] = None
    authors: List[str] = Field(default_factory=list)
    url: str = ""
    abstract: str = ""
    source: str = ""
    pdf_url: str = ""
    language: str = "en"
    has_fulltext: bool = False


class Claim(BaseModel):
    field: str
    quote: str
    page: Optional[int] = None
    verified: bool = False
    match_level: str = ""            # exact | normalized | anchored
    evidence_level: str = "abstract"  # fulltext | abstract
    entailment: str = ""             # supported | partial | unsupported（模型判定，自评）
    reason: str = ""
    proposal: Optional[str] = None   # 模型对原文的逐字复制尝试
    anchor: Optional[str] = None     # 模型给的短锚点
    context: Optional[str] = None    # 引文上下文（引文句 + 前后各一句）


class MatrixRow(BaseModel):
    paper_id: str
    title: str
    year: Optional[int] = None
    language: str = "en"
    parse_status: str = ""
    stub_reason: str = ""
    fields: dict = Field(default_factory=dict)
    claims: List[Claim] = Field(default_factory=list)
    stub: bool = False
    partial: bool = False


class Stats(BaseModel):
    papers: int = 0
    attempts: int = 0
    kept: int = 0
    quote_hit_rate: float = 0.0
    discard_rate: float = 0.0
    support_rate: float = 0.0
    field_completeness: float = 0.0
    elapsed_ms: int = 0


class Matrix(BaseModel):
    query: str = ""
    generated_at: str = ""
    rows: List[MatrixRow] = Field(default_factory=list)
    stats: Stats = Field(default_factory=Stats)
    synthesis: Optional[List[dict]] = None
