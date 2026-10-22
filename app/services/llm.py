"""LLM 调用公共层：异常类型、瞬时错误重试、token 统计日志。"""
from __future__ import annotations

import time

import httpx

from ..logging_config import get_logger


class LLMCallError(RuntimeError):
    pass


def _log_llm(kind: str, attempt: int, elapsed: float, usage: dict) -> None:
    logger = get_logger("llm")
    logger.info(
        "llm_call kind=%s attempt=%d elapsed=%.3fs prompt_tokens=%s completion_tokens=%s total_tokens=%s",
        kind,
        attempt,
        elapsed,
        usage.get("prompt_tokens", -1),
        usage.get("completion_tokens", -1),
        usage.get("total_tokens", -1),
    )


def with_retry(fn, kind: str, attempts: int = 2, delay: float = 1.5):
    """调用 fn()，返回 (content, usage)。超时/5xx/429 瞬时错误重试一次，其余直接抛错。"""
    last = None
    for attempt in range(1, attempts + 1):
        start = time.time()
        try:
            content, usage = fn()
        except httpx.TimeoutException as exc:
            last = LLMCallError(f"模型{kind}超时，请重试")
            if attempt >= attempts:
                raise last from exc
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code >= 500 or code == 429:
                last = LLMCallError(f"模型{kind}返回 {code}，请重试")
                if attempt >= attempts:
                    raise last from exc
            else:
                raise LLMCallError(f"模型{kind}返回 {code}，请重试") from exc
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            raise LLMCallError(f"模型{kind}失败或返回格式错误，请重试") from exc
        else:
            _log_llm(kind, attempt, time.time() - start, usage)
            return content, usage
        time.sleep(delay)
    raise last
