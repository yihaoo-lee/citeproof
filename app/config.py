"""集中读取配置；密钥只从环境变量 / .env 读，不进代码。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat").strip()
DEMO_MODE = _bool_env("DEMO_MODE", False)
OPENALEX_MAILTO = os.getenv("OPENALEX_MAILTO", "").strip()

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
PDF_MAX_MB = float(os.getenv("PDF_MAX_MB", "50"))
MAX_PAPERS = int(os.getenv("MAX_PAPERS", "30"))
TEXT_CHAR_LIMIT = int(os.getenv("TEXT_CHAR_LIMIT", "30000"))

DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
EVAL_DIR = DATA_DIR / "eval"


def llm_configured() -> bool:
    """是否有可用的 LLM key。"""
    return bool(LLM_API_KEY)
