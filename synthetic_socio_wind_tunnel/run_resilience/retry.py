"""
RetryPolicy — 跨 provider 统一重试策略。

D1' 事故（2026-05-15）暴露三处 LLM client 重试逻辑碎片化：Gemini 用
asyncio.wait_for(45s) + 手写 1-retry；DeepSeek 走 openai SDK
timeout=45/max_retries=1；Anthropic 完全靠 SDK 默认。retryable / fatal 分类
未统一定义。本模块提供单一 RetryPolicy 类，所有 tier client 共用。

调用约定（async tier client 主循环模板）：

    policy = RetryPolicy.from_env()
    last_exc = None
    for attempt in range(policy.max_attempts):
        try:
            return await sdk_call(...)
        except Exception as exc:  # noqa: BLE001
            verdict = policy.classify(exc)
            if verdict == "fatal":
                raise
            last_exc = exc
            if attempt + 1 < policy.max_attempts:
                await asyncio.sleep(policy.next_backoff(attempt))
    raise last_exc  # 用尽
"""

from __future__ import annotations

import logging
import os
import random
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


Verdict = Literal["retryable", "fatal", "unknown"]


_DEFAULT_RETRYABLE_HTTP: tuple[int, ...] = (408, 425, 429, 500, 502, 503, 504)
_DEFAULT_FATAL_HTTP: tuple[int, ...] = (400, 401, 403, 404, 422)


# retry-network-blip-tolerance (2026-05-19): duck-typed SDK network exc
# class names. We can't use `isinstance(exc, openai.APIConnectionError)`
# because (a) openai SDK is optional, and (b) those classes don't
# inherit Python builtin `ConnectionError` (which is OSError-subclass).
# Class-name match is stable across SDK module reorgs and stub-friendly.
_DEFAULT_RETRYABLE_EXC_CLASS_NAMES: frozenset[str] = frozenset({
    # openai + anthropic SDK (same names by convention)
    "APIConnectionError",
    "APITimeoutError",
    # httpx (underlying transport for openai/anthropic/google clients)
    "ConnectError",
    "ReadError",
    "WriteError",
    "ConnectTimeout",
    "ReadTimeout",
    "WriteTimeout",
    "PoolTimeout",
    "RemoteProtocolError",  # TLS / chunked transfer mid-flight break
    # google-genai (Gemini provider in our fallback chain)
    "DeadlineExceeded",
    "ServiceUnavailable",
})


def _default_retryable_excs() -> tuple[type[BaseException], ...]:
    import asyncio

    return (
        TimeoutError,
        ConnectionError,
        asyncio.TimeoutError,
    )


def _default_retryable_exc_class_names() -> frozenset[str]:
    return _DEFAULT_RETRYABLE_EXC_CLASS_NAMES


class RetryPolicy(BaseModel):
    """统一重试策略。frozen + 不可变；所有 tier client 共享同一实例。"""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    max_attempts: int = Field(default=3, ge=1, le=10)
    base_backoff_seconds: float = Field(default=0.5, gt=0)
    max_backoff_seconds: float = Field(default=8.0, gt=0)
    jitter_ratio: float = Field(default=0.2, ge=0, le=1)
    retryable_exceptions: tuple[type[BaseException], ...] = Field(
        default_factory=_default_retryable_excs,
    )
    retryable_exc_class_names: frozenset[str] = Field(
        default_factory=_default_retryable_exc_class_names,
    )
    retryable_http_statuses: tuple[int, ...] = _DEFAULT_RETRYABLE_HTTP
    fatal_http_statuses: tuple[int, ...] = _DEFAULT_FATAL_HTTP

    def next_backoff(self, attempt_idx: int) -> float:
        """指数退避 + jitter；attempt_idx 从 0 起。"""
        base = self.base_backoff_seconds * (2 ** max(0, attempt_idx))
        capped = min(base, self.max_backoff_seconds)
        if self.jitter_ratio <= 0:
            return capped
        lo = capped * (1.0 - self.jitter_ratio)
        hi = capped * (1.0 + self.jitter_ratio)
        return random.uniform(lo, hi)

    def classify(self, exc: BaseException) -> Verdict:
        """归类一个异常为 retryable / fatal / unknown。

        优先级：fatal HTTP > retryable HTTP > retryable exception types。
        未匹配的归 "unknown"——调用方应当视为 fatal（默认不重试）以避免
        重试 bug。
        """
        status = _extract_status_code(exc)
        if status is not None:
            if status in self.fatal_http_statuses:
                return "fatal"
            if status in self.retryable_http_statuses:
                return "retryable"
        # retry-network-blip-tolerance (2026-05-19): duck-typed class name
        # check covers SDK network exceptions (openai.APIConnectionError /
        # httpx.ConnectError / etc.) that don't inherit Python builtin
        # ConnectionError. O(1) frozenset lookup; placed before isinstance
        # loop since SDK errors are more frequent in practice.
        if type(exc).__name__ in self.retryable_exc_class_names:
            return "retryable"
        for exc_type in self.retryable_exceptions:
            if isinstance(exc, exc_type):
                return "retryable"
        return "unknown"

    @classmethod
    def from_env(cls) -> RetryPolicy:
        """从 RESILIENCE_RETRY_* 环境变量构造；缺失字段走默认。"""
        kwargs: dict[str, Any] = {}
        for env_key, field_name, parser in (
            ("RESILIENCE_RETRY_MAX_ATTEMPTS", "max_attempts", int),
            ("RESILIENCE_RETRY_BASE_BACKOFF", "base_backoff_seconds", float),
            ("RESILIENCE_RETRY_MAX_BACKOFF", "max_backoff_seconds", float),
            ("RESILIENCE_RETRY_JITTER_RATIO", "jitter_ratio", float),
        ):
            raw = os.environ.get(env_key)
            if raw is None or raw == "":
                continue
            try:
                kwargs[field_name] = parser(raw)
            except (ValueError, TypeError):
                logger.warning(
                    "RetryPolicy.from_env: %s=%r 无法解析，使用默认值",
                    env_key, raw,
                )

        # retry-network-blip-tolerance: append-only union with defaults.
        # User-provided names ADD to coverage; never replace the
        # built-in 12 SDK names (those are load-bearing safety).
        raw_names = os.environ.get("RESILIENCE_RETRY_EXC_CLASS_NAMES")
        if raw_names:
            try:
                extra = frozenset(
                    n.strip() for n in raw_names.split(",")
                    if n and n.strip()
                )
                kwargs["retryable_exc_class_names"] = (
                    _DEFAULT_RETRYABLE_EXC_CLASS_NAMES | extra
                )
            except (AttributeError, TypeError) as exc:
                logger.warning(
                    "RetryPolicy.from_env: RESILIENCE_RETRY_EXC_CLASS_NAMES"
                    "=%r unparseable (%s); using default 12-name frozenset",
                    raw_names, exc,
                )

        return cls(**kwargs)


def _extract_status_code(exc: BaseException) -> int | None:
    """从 openai / google-genai / httpx 异常里提取 HTTP status code。

    Duck-typed：依次尝试常见 attribute 路径，避免硬依赖三家 SDK。
    """
    direct = getattr(exc, "status_code", None)
    if isinstance(direct, int):
        return direct
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    response = getattr(exc, "response", None)
    if response is not None:
        rs = getattr(response, "status_code", None)
        if isinstance(rs, int):
            return rs
    return None
