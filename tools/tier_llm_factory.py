"""
tier_llm_factory — build a dict[tier, LLMClient] for the OperationPool.

The ai-town port (agent-stack-aitown-port Phase E task 19) routes ops to
different LLM tiers via OperationPool's tier_for_kind:

    do_something / generate_message  → sonnet  (richer reasoning)
    remember_conversation / reflect  → haiku   (summarization)
    score_importance                 → nano    (single-token-ish)

Anthropic's lineup doesn't have a "nano" model, so the nano tier maps to
haiku at smaller max_tokens. The factory returns a flat dict keyed by
tier name; OperationPool selects from it via DEFAULT_TIER_FOR_KIND.

Usage:

    from tools.tier_llm_factory import build_tier_clients
    clients = build_tier_clients(provider="anthropic")
    pool = OperationPool(handlers=..., llm_clients=clients)

For tests / dry-runs use `provider="stub"`, which returns deterministic
no-cost stubs for each tier.

2026-05-15 run-resilience: all three real-provider clients (Gemini /
DeepSeek / Anthropic) inject a custom httpx async client with
`max_keepalive_connections=0` (block D1' CLOSE_WAIT accumulation), share a
single `RetryPolicy`, each key tracked by a `PerKeyCircuitBreaker`, and
recycle the underlying httpx pool every `recycle_after_calls` to guard
against any SDK state residue. Set `RESILIENCE_DISABLE=1` to fall back to
SDK defaults (escape hatch; not for publishable runs).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Mapping, TypeVar

from synthetic_socio_wind_tunnel.run_resilience import (
    AllKeysOpenError,
    PerKeyCircuitBreaker,
    RetryPolicy,
)

logger = logging.getLogger(__name__)


Tier = Literal["sonnet", "haiku", "nano"]
Provider = Literal["anthropic", "gemini", "deepseek", "stub"]


# Default model per tier. Override via env or build_tier_clients(models=...).
DEFAULT_MODELS: dict[Tier, str] = {
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
    # "nano" tier maps to haiku (no nano model exists); the OperationPool
    # uses it for score_importance which is cheap (single int).
    "nano": "claude-haiku-4-5-20251001",
}

# Gemini equivalents — Flash Lite is fastest/cheapest. All 3 tiers route to
# the same model for v1; tier routing differentiates max_tokens only.
# 2026-05-13: switched from gemini-3-flash-preview → gemini-3.1-flash-lite
# after D1' DeepSeek stability issues. Gemini 3.1 Flash Lite probed at
# 1.54s mean / 2.43s wall for 50 concurrent calls, 100% success rate
# (vs DeepSeek 23% connection-error rate at the same scale).
GEMINI_MODELS: dict[Tier, str] = {
    "sonnet": "gemini-3.1-flash-lite",
    "haiku": "gemini-3.1-flash-lite",
    "nano": "gemini-3.1-flash-lite",
}

# DeepSeek equivalents — added 2026-05-11 for higher RPM / lower cost.
# Per user spec: high-cost reasoning tier → v4-pro; low-cost tiers → v4-flash.
# DeepSeek API is OpenAI-compatible (https://api-docs.deepseek.com/zh-cn/),
# so we use the openai SDK with custom base_url.
DEEPSEEK_MODELS: dict[Tier, str] = {
    "sonnet": "deepseek-v4-pro",
    "haiku": "deepseek-v4-flash",
    "nano": "deepseek-v4-flash",
}


# Per-tier max_tokens hints. Smaller for nano so prompt + completion stays
# tight when scoring importance.
#
# 2026-05-17 (setup-content-cache D1 prewarm bug): sonnet bumped 1024 →
# 393216 (= 384K, DeepSeek v4 family documented output cap per user-cited
# API docs). The original 1024 default caused 38% of life_history JSON
# responses to truncate mid-record (20 records × ~300-char Chinese
# narratives easily exceed 1024 tokens). max_tokens is a ceiling, not a
# target — real responses stay well under it; this just removes the bug.
DEFAULT_MAX_TOKENS: dict[Tier, int] = {
    "sonnet": 393216,  # 384K — DeepSeek v4 max output
    "haiku": 32768,    # 32K headroom for reflection / summary
    "nano": 256,       # importance score short by design
}


# ---------------------------------------------------------------------------
# run-resilience helpers (D1' incident fix; see openspec/specs/run-resilience)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HttpxPoolConfig:
    """Connection-pool config passed into every real-provider tier client.

    Defaults match openspec/specs/run-resilience/spec.md (keepalive=0
    blocks CLOSE_WAIT accumulation observed in the D1' Gemini deadlock).
    """

    max_connections: int = 600
    max_keepalive_connections: int = 0
    connect_timeout: float = 10.0
    # read_timeout 2026-05-17: 45s → 300s. At 384K max_tokens with rich
    # Chinese narrative prompts (life_history × 20 records), DeepSeek
    # v4-pro takes 30-90s to finish a single response; the previous 45s
    # ceiling caused 100% APITimeoutError in smoke. 300s = 5min absorbs
    # any reasonable response while still bounding hung connections.
    read_timeout: float = 300.0
    write_timeout: float = 10.0
    pool_timeout: float = 30.0

    @classmethod
    def from_env(cls) -> HttpxPoolConfig:
        return cls(
            max_connections=_env_int(
                "RESILIENCE_POOL_MAX_CONNECTIONS", cls.max_connections,
            ),
            max_keepalive_connections=_env_int(
                "RESILIENCE_POOL_MAX_KEEPALIVE", cls.max_keepalive_connections,
            ),
            connect_timeout=_env_float(
                "RESILIENCE_POOL_CONNECT_TIMEOUT", cls.connect_timeout,
            ),
            read_timeout=_env_float(
                "RESILIENCE_POOL_READ_TIMEOUT", cls.read_timeout,
            ),
            write_timeout=_env_float(
                "RESILIENCE_POOL_WRITE_TIMEOUT", cls.write_timeout,
            ),
            pool_timeout=_env_float(
                "RESILIENCE_POOL_TIMEOUT", cls.pool_timeout,
            ),
        )


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r 无法解析为 int，使用默认 %s", key, raw, default)
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s=%r 无法解析为 float，使用默认 %s", key, raw, default)
        return default


def _build_httpx_async_client(cfg: HttpxPoolConfig) -> Any:
    """Build httpx.AsyncClient from a HttpxPoolConfig. Lazy-imports httpx
    so providers that don't use it (e.g. stub) don't need it installed."""
    import httpx
    return httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=cfg.max_connections,
            max_keepalive_connections=cfg.max_keepalive_connections,
        ),
        timeout=httpx.Timeout(
            connect=cfg.connect_timeout,
            read=cfg.read_timeout,
            write=cfg.write_timeout,
            pool=cfg.pool_timeout,
        ),
    )


@dataclass
class _KeyContext:
    """Per-API-key state container: one client + one breaker + call counter.

    Used by multi-key Gemini and DeepSeek clients. Anthropic only has one
    api_key so its client wraps a single _KeyContext.
    """

    key_value: str
    sdk_client: Any  # genai.Client | openai.AsyncOpenAI | anthropic.Anthropic
    httpx_client: Any | None  # the httpx.AsyncClient (for aclose on recycle)
    breaker: PerKeyCircuitBreaker
    call_count: int = 0
    rebuild_fn: Callable[[], tuple[Any, Any]] | None = field(
        default=None, repr=False,
    )

    def maybe_recycle(self, *, threshold: int) -> None:
        """If call_count ≥ threshold, aclose + rebuild via rebuild_fn.

        Schedules httpx_client.aclose() but does not await it here —
        caller should `await self._aclose_old(old_http)` once it has the
        old reference. To keep things sync we instead let the next event
        loop iteration close the old client; new traffic uses the new
        one immediately."""
        if threshold <= 0 or self.rebuild_fn is None:
            return
        if self.call_count < threshold:
            return
        old_httpx = self.httpx_client
        try:
            self.sdk_client, self.httpx_client = self.rebuild_fn()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "tier client recycle failed (will keep old): %s", exc,
            )
            return
        self.call_count = 0
        if old_httpx is not None:
            asyncio.create_task(_safe_aclose(old_httpx))


async def _safe_aclose(httpx_client: Any) -> None:
    try:
        await httpx_client.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("aclose 旧 httpx client 失败 (忽略): %s", exc)


def _pick_open_aware(
    contexts: list[_KeyContext], *, start_idx: int,
) -> tuple[int, _KeyContext]:
    """Round-robin starting at start_idx, skipping contexts whose breaker
    is open. Raises AllKeysOpenError if all keys are open."""
    n = len(contexts)
    next_avail: float | None = None
    for offset in range(n):
        idx = (start_idx + offset) % n
        ctx = contexts[idx]
        if ctx.breaker.should_allow():
            return idx, ctx
        na = ctx.breaker.next_available_at
        if na is not None and (next_avail is None or na < next_avail):
            next_avail = na
    raise AllKeysOpenError(n_keys=n, next_available_at=next_avail)


T = TypeVar("T")


async def _run_with_retry(
    *,
    operation: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    breaker: PerKeyCircuitBreaker,
) -> T:
    """Run `operation()` under retry + breaker.

    - retryable: backoff + retry up to max_attempts
    - fatal: re-raise immediately, record_failure
    - unknown: re-raise immediately (safer default than blind retry),
      record_failure
    - exhausted: re-raise last exception, record_failure
    - success: record_success, return result
    """
    last_exc: BaseException | None = None
    for attempt in range(policy.max_attempts):
        try:
            result = await operation()
        except BaseException as exc:  # noqa: BLE001
            verdict = policy.classify(exc)
            if verdict in ("fatal", "unknown"):
                breaker.record_failure()
                raise
            last_exc = exc
            if attempt + 1 >= policy.max_attempts:
                break
            await asyncio.sleep(policy.next_backoff(attempt))
            continue
        else:
            breaker.record_success()
            return result
    breaker.record_failure()
    assert last_exc is not None
    raise last_exc


def _resilience_disabled() -> bool:
    return os.environ.get("RESILIENCE_DISABLE") == "1"


# ---------------------------------------------------------------------------
# stub client (unchanged — no resilience needed)
# ---------------------------------------------------------------------------

class _StubTierClient:
    """Deterministic no-cost client for tests / dry runs.

    Returns a fixed canned response per tier. Useful for `--dry-run` /
    fitness-audit paths where we want the OperationPool wired but no real
    LLM calls.
    """

    def __init__(self, tier: Tier) -> None:
        self._tier = tier
        self.calls: list[tuple[str, str]] = []

    async def generate(self, prompt: str, *, model: str = "", **_: Any) -> str:
        self.calls.append((self._tier, prompt))
        # Detect prompt shape and return a parseable canned response so
        # downstream parsers don't fall back. Order matters — match more
        # specific patterns first.

        # life_history (JSON array of records) — sample_population path
        if "life history backstory" in prompt or "n_records" in prompt:
            import json as _json
            return _json.dumps([
                {
                    "title": f"事件 {i}", "content": f"我 {i} 年前的某个经历。",
                    "years_ago": float(i), "location_hint": None,
                    "importance": 0.5, "tags": ["stub"],
                }
                for i in range(1, 11)
            ])

        # reflection prompt (ai-town 1:1 port: "[Output only JSON]" + insights)
        if "[Output only JSON]" in prompt and "insights" in prompt:
            import json as _json
            return _json.dumps([
                {"insight": f"stub insight {i}", "source_event_ids": []}
                for i in range(3)
            ])

        # identity_text generation prompt — JSON {identity, plan}
        if "identity" in prompt.lower() and "plan" in prompt.lower():
            return '{"identity": "Stub identity persona.", "plan": "Stub today plan."}'

        # do_something prompt
        if '"action"' in prompt and "invite_dialogue" in prompt:
            return '{"action":"wait"}'

        # generate_message prompt
        if "you just started a conversation" in prompt or \
           "currently in a conversation" in prompt:
            return "Hi there, nice to see you."

        # remember_conversation
        if "summarize the conversation" in prompt:
            return "(stub conversation summary)"

        # Per-tier fallback
        if self._tier == "nano":
            return "5"
        if self._tier == "haiku":
            return "(stub haiku summary)"
        return '{"action":"wait"}'


# ---------------------------------------------------------------------------
# Gemini tier client (multi-key + httpx-injected + retry + breaker)
# ---------------------------------------------------------------------------

def _gemini_keys_from_env(api_keys: list[str] | None) -> list[str]:
    if api_keys:
        return api_keys
    multi = os.environ.get("GEMINI_API_KEYS")
    if multi:
        keys = [k.strip() for k in multi.split(",") if k.strip()]
        if keys:
            return keys
    for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        single = os.environ.get(env_name)
        if single:
            return [single]
    return []


class _GeminiTierClient:
    """Gemini-backed client. Uses the **async** Gemini SDK (client.aio).

    Critical for performance: the OperationPool's asyncio.gather over
    in-flight ops only parallelizes if the underlying network call is
    truly async. The previous sync wrapper made gather degenerate to
    serial 5-sec calls per op; with `client.aio.models.generate_content`
    a tick's 10 protag reflections can run in parallel (~5x speedup).

    run-resilience (2026-05-15): supports `GEMINI_API_KEYS` multi-key
    rotation, per-key circuit breaker, and a custom httpx.AsyncClient
    injected via `HttpOptions.httpx_async_client` with
    `max_keepalive_connections=0` to block the CLOSE_WAIT pool poisoning
    seen in D1'.
    """

    def __init__(
        self,
        *,
        tier: Tier,
        model: str,
        max_tokens: int,
        api_keys: list[str] | None = None,
        api_key: str | None = None,
        retry_policy: RetryPolicy | None = None,
        pool_config: HttpxPoolConfig | None = None,
        recycle_after_calls: int = 1000,
        circuit_breaker_factory: Callable[[], PerKeyCircuitBreaker] | None = None,
    ) -> None:
        try:
            from google import genai  # type: ignore[import-not-found]
            from google.genai import types as genai_types  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "google-genai SDK not installed; pip install google-genai",
            ) from exc

        self._types = genai_types
        self._tier = tier
        self._model = model
        self._max_tokens = max_tokens

        # Multi-key resolution. Backward compat: api_key kwarg becomes a
        # single-key list.
        if api_keys is None and api_key is not None:
            api_keys = [api_key]
        keys = _gemini_keys_from_env(api_keys)
        if not keys:
            raise RuntimeError(
                "GEMINI_API_KEYS / GEMINI_API_KEY / GOOGLE_API_KEY missing; "
                "set one of them in env or pass api_key(s) kwarg",
            )

        self._retry_policy: RetryPolicy = retry_policy or RetryPolicy.from_env()
        self._pool_config: HttpxPoolConfig = pool_config or HttpxPoolConfig.from_env()
        self._recycle_after_calls = max(0, recycle_after_calls)
        cb_factory = circuit_breaker_factory or PerKeyCircuitBreaker.from_env

        def _build_pair(key: str) -> tuple[Any, Any]:
            httpx_client = _build_httpx_async_client(self._pool_config)
            http_options = genai_types.HttpOptions(
                httpx_async_client=httpx_client,
            )
            sdk_client = genai.Client(api_key=key, http_options=http_options)
            return sdk_client, httpx_client

        self._contexts: list[_KeyContext] = []
        for key in keys:
            sdk_client, httpx_client = _build_pair(key)
            self._contexts.append(_KeyContext(
                key_value=key,
                sdk_client=sdk_client,
                httpx_client=httpx_client,
                breaker=cb_factory(),
                rebuild_fn=(lambda k=key: _build_pair(k)),  # type: ignore[misc]
            ))
        self._key_idx = 0
        # B6 fix: cache last call's token usage so OperationPool can stamp
        # OperationResult.prompt_tokens / completion_tokens for cost_breakdown.
        self._last_usage: dict[str, int] | None = None

    async def generate(
        self, prompt: str, *, model: str = "", **_: Any,
    ) -> str:
        # IGNORE external model parameter — handlers pass profile.base_model
        # (e.g. "claude-sonnet-4-6") which Gemini doesn't recognize → 404.
        used_model = self._model
        # thinking_budget=0 — flash-preview defaults to thinking ON which
        # adds latency for ai-town ops. Force off.
        config = self._types.GenerateContentConfig(
            thinking_config=self._types.ThinkingConfig(thinking_budget=0),
        )

        idx, ctx = _pick_open_aware(self._contexts, start_idx=self._key_idx)
        self._key_idx = (idx + 1) % len(self._contexts)

        async def _do_call() -> Any:
            return await ctx.sdk_client.aio.models.generate_content(
                model=used_model,
                contents=prompt,
                config=config,
            )

        try:
            response = await _run_with_retry(
                operation=_do_call,
                policy=self._retry_policy,
                breaker=ctx.breaker,
            )
        except BaseException:
            self._last_usage = None
            raise

        ctx.call_count += 1
        ctx.maybe_recycle(threshold=self._recycle_after_calls)

        try:
            usage = getattr(response, "usage_metadata", None)
            if usage is not None:
                self._last_usage = {
                    "prompt_tokens": int(getattr(usage, "prompt_token_count", 0) or 0),
                    "completion_tokens": int(
                        getattr(usage, "candidates_token_count", 0) or 0,
                    ),
                }
            else:
                self._last_usage = None
        except Exception:
            self._last_usage = None
        return response.text or ""


# ---------------------------------------------------------------------------
# DeepSeek tier client (multi-key + per-key breaker + retry + keepalive=0)
# ---------------------------------------------------------------------------

def _deepseek_keys_from_env(api_key: str | None) -> list[str]:
    if api_key is not None:
        return [api_key]
    multi = os.environ.get("DEEPSEEK_API_KEYS")
    if multi:
        keys = [k.strip() for k in multi.split(",") if k.strip()]
        if keys:
            return keys
    single = os.environ.get("DEEPSEEK_API_KEY")
    return [single] if single else []


class _DeepSeekTierClient:
    """DeepSeek-backed async client. Uses the openai SDK with custom
    base_url (DeepSeek's API is OpenAI-compatible).

    Reference: https://api-docs.deepseek.com/zh-cn/

    Tier routing via DEEPSEEK_MODELS:
    - sonnet → deepseek-v4-pro (reasoning / decision / dialogue)
    - haiku  → deepseek-v4-flash (summary / reflection)
    - nano   → deepseek-v4-flash (importance scoring)

    Reads DEEPSEEK_API_KEY[S] from env (or explicit api_key kwarg).

    run-resilience (2026-05-15): `max_keepalive_connections=0` on the
    injected httpx client blocks CLOSE_WAIT accumulation; openai SDK's
    own `max_retries` set to 0 because RetryPolicy owns the retry loop.
    Each key gets its own PerKeyCircuitBreaker.
    """

    def __init__(
        self,
        *,
        tier: Tier,
        model: str,
        max_tokens: int,
        api_key: str | None = None,
        api_keys: list[str] | None = None,
        base_url: str = "https://api.deepseek.com",
        retry_policy: RetryPolicy | None = None,
        pool_config: HttpxPoolConfig | None = None,
        recycle_after_calls: int = 1000,
        circuit_breaker_factory: Callable[[], PerKeyCircuitBreaker] | None = None,
    ) -> None:
        try:
            from openai import AsyncOpenAI  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "openai SDK not installed (used for DeepSeek's "
                "OpenAI-compatible API); pip install openai",
            ) from exc

        # Multi-key resolution
        if api_keys is None:
            keys = _deepseek_keys_from_env(api_key)
        else:
            keys = api_keys
        if not keys:
            raise RuntimeError(
                "DEEPSEEK_API_KEY[S] missing — set DEEPSEEK_API_KEYS (comma-"
                "separated) or DEEPSEEK_API_KEY in env, or pass api_key kwarg",
            )

        self._tier = tier
        self._model = model
        self._max_tokens = max_tokens
        self._base_url = base_url
        self._retry_policy: RetryPolicy = retry_policy or RetryPolicy.from_env()
        self._pool_config: HttpxPoolConfig = pool_config or HttpxPoolConfig.from_env()
        self._recycle_after_calls = max(0, recycle_after_calls)
        cb_factory = circuit_breaker_factory or PerKeyCircuitBreaker.from_env

        def _build_pair(key: str) -> tuple[Any, Any]:
            httpx_client = _build_httpx_async_client(self._pool_config)
            sdk_client = AsyncOpenAI(
                api_key=key,
                base_url=base_url,
                timeout=self._pool_config.read_timeout,
                # max_retries=0: RetryPolicy owns the retry loop. openai SDK's
                # default retry would double-count attempts.
                max_retries=0,
                http_client=httpx_client,
            )
            return sdk_client, httpx_client

        self._contexts: list[_KeyContext] = []
        for k in keys:
            sdk_client, httpx_client = _build_pair(k)
            self._contexts.append(_KeyContext(
                key_value=k,
                sdk_client=sdk_client,
                httpx_client=httpx_client,
                breaker=cb_factory(),
                rebuild_fn=(lambda kk=k: _build_pair(kk)),  # type: ignore[misc]
            ))
        self._key_idx = 0
        # B6 contract
        self._last_usage: dict[str, int] | None = None

    async def generate(
        self, prompt: str, *, model: str = "", **_: Any,
    ) -> str:
        used_model = self._model

        idx, ctx = _pick_open_aware(self._contexts, start_idx=self._key_idx)
        self._key_idx = (idx + 1) % len(self._contexts)

        async def _do_call() -> Any:
            # 2026-05-11: Force-disable chain-of-thought reasoning.
            # `thinking={"type": "disabled"}` cuts latency from 7.7s → 1.7s
            # on v4-pro; `enable_thinking=False` is the suspenders+belt
            # variant covering different DeepSeek model versions.
            return await ctx.sdk_client.chat.completions.create(
                model=used_model,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": prompt}],
                extra_body={
                    "thinking": {"type": "disabled"},
                    "enable_thinking": False,
                },
            )

        try:
            response = await _run_with_retry(
                operation=_do_call,
                policy=self._retry_policy,
                breaker=ctx.breaker,
            )
        except BaseException:
            self._last_usage = None
            raise

        ctx.call_count += 1
        ctx.maybe_recycle(threshold=self._recycle_after_calls)

        try:
            usage = getattr(response, "usage", None)
            if usage is not None:
                self._last_usage = {
                    "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(
                        getattr(usage, "completion_tokens", 0) or 0,
                    ),
                }
            else:
                self._last_usage = None
        except Exception:
            self._last_usage = None

        if not response.choices:
            return ""
        msg = response.choices[0].message
        return msg.content or ""


# ---------------------------------------------------------------------------
# Anthropic tier client (single-key, sync SDK wrapped in to_thread + retry)
# ---------------------------------------------------------------------------

class _AnthropicTierClient:
    """Anthropic-backed client with per-tier model + max_tokens.

    Wraps the synchronous Anthropic SDK in an `async def generate`
    matching `LLMClient` protocol. run-resilience (2026-05-15): SDK
    instantiated with a custom httpx.Client (sync) bound to our pool
    config; calls run in `asyncio.to_thread` then go through the
    standard RetryPolicy + circuit-breaker layer.
    """

    def __init__(
        self,
        *,
        tier: Tier,
        model: str,
        max_tokens: int,
        api_key: str | None = None,
        retry_policy: RetryPolicy | None = None,
        pool_config: HttpxPoolConfig | None = None,
        recycle_after_calls: int = 1000,
        circuit_breaker_factory: Callable[[], PerKeyCircuitBreaker] | None = None,
    ) -> None:
        try:
            from anthropic import Anthropic  # type: ignore[import-not-found]
            import httpx  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "anthropic SDK not installed; pip install anthropic",
            ) from exc

        self._tier = tier
        self._model = model
        self._max_tokens = max_tokens
        self._retry_policy: RetryPolicy = retry_policy or RetryPolicy.from_env()
        self._pool_config: HttpxPoolConfig = pool_config or HttpxPoolConfig.from_env()
        self._recycle_after_calls = max(0, recycle_after_calls)
        cb_factory = circuit_breaker_factory or PerKeyCircuitBreaker.from_env

        def _build_pair() -> tuple[Any, Any]:
            httpx_client = httpx.Client(
                limits=httpx.Limits(
                    max_connections=self._pool_config.max_connections,
                    max_keepalive_connections=self._pool_config.max_keepalive_connections,
                ),
                timeout=httpx.Timeout(
                    connect=self._pool_config.connect_timeout,
                    read=self._pool_config.read_timeout,
                    write=self._pool_config.write_timeout,
                    pool=self._pool_config.pool_timeout,
                ),
            )
            if api_key:
                sdk_client = Anthropic(api_key=api_key, http_client=httpx_client)
            else:
                sdk_client = Anthropic(http_client=httpx_client)
            return sdk_client, httpx_client

        sdk_client, httpx_client = _build_pair()
        self._ctx = _KeyContext(
            key_value=api_key or "<env>",
            sdk_client=sdk_client,
            httpx_client=httpx_client,
            breaker=cb_factory(),
            rebuild_fn=_build_pair,
        )

    async def generate(
        self, prompt: str, *, model: str = "", **_: Any,
    ) -> str:
        used_model = model or self._model
        ctx = self._ctx
        if not ctx.breaker.should_allow():
            raise AllKeysOpenError(
                n_keys=1,
                next_available_at=ctx.breaker.next_available_at,
            )

        async def _do_call() -> Any:
            return await asyncio.to_thread(
                ctx.sdk_client.messages.create,
                model=used_model,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

        response = await _run_with_retry(
            operation=_do_call,
            policy=self._retry_policy,
            breaker=ctx.breaker,
        )
        ctx.call_count += 1
        ctx.maybe_recycle(threshold=self._recycle_after_calls)

        text_parts: list[str] = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
        return "".join(text_parts)


# ---------------------------------------------------------------------------
# Legacy unhardened path (RESILIENCE_DISABLE=1 escape hatch only)
# ---------------------------------------------------------------------------

class _LegacyAnthropicTierClient:
    """Original Anthropic client without resilience hardening. Used only
    when RESILIENCE_DISABLE=1 — emergency escape hatch for in-flight D2
    style runs that cannot be restarted."""

    def __init__(
        self, *, tier: Tier, model: str, max_tokens: int,
        api_key: str | None = None,
    ) -> None:
        from anthropic import Anthropic  # type: ignore[import-not-found]
        self._client = Anthropic(api_key=api_key) if api_key else Anthropic()
        self._tier, self._model, self._max_tokens = tier, model, max_tokens

    async def generate(
        self, prompt: str, *, model: str = "", **_: Any,
    ) -> str:
        used_model = model or self._model
        response = await asyncio.to_thread(
            self._client.messages.create,
            model=used_model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text_parts: list[str] = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
        return "".join(text_parts)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_tier_clients(
    *,
    provider: Provider = "stub",
    models: Mapping[Tier, str] | None = None,
    max_tokens: Mapping[Tier, int] | None = None,
    api_key: str | None = None,
    retry_policy: RetryPolicy | None = None,
    pool_config: HttpxPoolConfig | None = None,
    recycle_after_calls: int | None = None,
    circuit_breaker_factory: Callable[[], PerKeyCircuitBreaker] | None = None,
) -> dict[str, Any]:
    """Return a `{tier_name: LLMClient}` mapping for OperationPool.

    Args:
        provider: "anthropic" / "gemini" / "deepseek" for real calls;
            "stub" for deterministic no-cost test clients.
        models: optional override per tier; missing tiers fall back to
            DEFAULT_MODELS.
        max_tokens: optional override per tier.
        api_key: explicit API key (else picked from env). For Gemini /
            DeepSeek, prefer setting *_API_KEYS (comma-separated) in env
            to enable multi-key rotation.
        retry_policy: shared RetryPolicy instance for all tier clients
            (None → built from RESILIENCE_RETRY_* env vars).
        pool_config: shared HttpxPoolConfig for all real-provider clients
            (None → built from RESILIENCE_POOL_* env vars).
        recycle_after_calls: every N calls per-key, aclose() + rebuild the
            httpx client to dodge any SDK state residue. None → read
            RESILIENCE_RECYCLE_AFTER_CALLS env (default 1000).
        circuit_breaker_factory: per-key breaker constructor. None →
            PerKeyCircuitBreaker.from_env.

    Returns:
        dict[str, LLMClient] with keys "sonnet", "haiku", "nano".

    Set RESILIENCE_DISABLE=1 in env to fall back to the pre-2026-05-15
    SDK-default behavior — escape hatch only; not for publishable runs.
    """
    model_map: dict[Tier, str] = {**DEFAULT_MODELS, **(models or {})}
    tokens_map: dict[Tier, int] = {**DEFAULT_MAX_TOKENS, **(max_tokens or {})}

    if provider == "stub":
        return {
            "sonnet": _StubTierClient("sonnet"),
            "haiku": _StubTierClient("haiku"),
            "nano": _StubTierClient("nano"),
        }

    # All real providers go through resilient or legacy path
    if _resilience_disabled():
        print(
            "WARN: RESILIENCE_DISABLE=1, skipping run-resilience hardening "
            "(escape hatch path; not for publishable runs)",
            file=sys.stderr,
        )
        return _build_legacy(
            provider=provider,
            model_map=model_map, tokens_map=tokens_map, api_key=api_key,
        )

    eff_recycle = (
        recycle_after_calls
        if recycle_after_calls is not None
        else _env_int("RESILIENCE_RECYCLE_AFTER_CALLS", 1000)
    )
    eff_policy = retry_policy or RetryPolicy.from_env()
    eff_pool = pool_config or HttpxPoolConfig.from_env()

    if provider == "anthropic":
        eff_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if eff_key is None:
            logger.warning(
                "tier_llm_factory: provider=anthropic but no api_key found "
                "in args or ANTHROPIC_API_KEY env; SDK may fail at first call",
            )
        return {
            tier: _AnthropicTierClient(
                tier=tier, model=model_map[tier], max_tokens=tokens_map[tier],
                api_key=eff_key,
                retry_policy=eff_policy,
                pool_config=eff_pool,
                recycle_after_calls=eff_recycle,
                circuit_breaker_factory=circuit_breaker_factory,
            )
            for tier in ("sonnet", "haiku", "nano")
        }
    if provider == "gemini":
        gemini_model_map = {**GEMINI_MODELS, **(models or {})}
        keys = _gemini_keys_from_env([api_key] if api_key else None)
        if not keys:
            logger.warning(
                "tier_llm_factory: provider=gemini but no GEMINI_API_KEYS / "
                "GEMINI_API_KEY / GOOGLE_API_KEY in env; SDK will fail at "
                "first call",
            )
        return {
            tier: _GeminiTierClient(
                tier=tier, model=gemini_model_map[tier],
                max_tokens=tokens_map[tier],
                api_keys=keys or None,
                retry_policy=eff_policy,
                pool_config=eff_pool,
                recycle_after_calls=eff_recycle,
                circuit_breaker_factory=circuit_breaker_factory,
            )
            for tier in ("sonnet", "haiku", "nano")
        }
    if provider == "deepseek":
        deepseek_model_map = {**DEEPSEEK_MODELS, **(models or {})}
        keys = _deepseek_keys_from_env(api_key)
        if not keys:
            logger.warning(
                "tier_llm_factory: provider=deepseek but no DEEPSEEK_API_KEY "
                "in env; SDK will fail at first call",
            )
        return {
            tier: _DeepSeekTierClient(
                tier=tier, model=deepseek_model_map[tier],
                max_tokens=tokens_map[tier],
                api_keys=keys or None,
                retry_policy=eff_policy,
                pool_config=eff_pool,
                recycle_after_calls=eff_recycle,
                circuit_breaker_factory=circuit_breaker_factory,
            )
            for tier in ("sonnet", "haiku", "nano")
        }
    raise ValueError(f"unknown provider {provider!r}")


def _build_legacy(
    *,
    provider: Provider,
    model_map: dict[Tier, str],
    tokens_map: dict[Tier, int],
    api_key: str | None,
) -> dict[str, Any]:
    """Pre-resilience clients — used only when RESILIENCE_DISABLE=1.

    Note: only Anthropic has a true legacy path here; Gemini / DeepSeek
    legacy still construct the resilient class but with the *legacy* env
    defaults (we cannot reconstruct the exact pre-2026-05-15 behavior in
    this branch — that file no longer exists in HEAD). For Gemini /
    DeepSeek, RESILIENCE_DISABLE primarily disables the per-key breaker
    by feeding it an effectively-infinite threshold."""
    if provider == "anthropic":
        eff_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        return {
            tier: _LegacyAnthropicTierClient(
                tier=tier, model=model_map[tier],
                max_tokens=tokens_map[tier], api_key=eff_key,
            )
            for tier in ("sonnet", "haiku", "nano")
        }
    # Gemini / DeepSeek: build resilient clients but with breaker thresholds
    # raised so they effectively don't trip. keepalive=0 stays — losing it
    # would re-introduce the D1' deadlock root cause even under RESILIENCE_DISABLE.
    null_breaker = lambda: PerKeyCircuitBreaker(  # noqa: E731
        failure_threshold=1_000_000, cooldown_seconds=1.0,
    )
    relaxed_policy = RetryPolicy(max_attempts=2)
    if provider == "gemini":
        gemini_model_map = {**GEMINI_MODELS, **{}}
        return {
            tier: _GeminiTierClient(
                tier=tier, model=gemini_model_map[tier],
                max_tokens=tokens_map[tier],
                retry_policy=relaxed_policy,
                circuit_breaker_factory=null_breaker,
                recycle_after_calls=0,
            )
            for tier in ("sonnet", "haiku", "nano")
        }
    if provider == "deepseek":
        deepseek_model_map = {**DEEPSEEK_MODELS, **{}}
        return {
            tier: _DeepSeekTierClient(
                tier=tier, model=deepseek_model_map[tier],
                max_tokens=tokens_map[tier], api_key=api_key,
                retry_policy=relaxed_policy,
                circuit_breaker_factory=null_breaker,
                recycle_after_calls=0,
            )
            for tier in ("sonnet", "haiku", "nano")
        }
    raise ValueError(f"unknown provider {provider!r}")


__all__ = [
    "Tier",
    "Provider",
    "DEFAULT_MODELS",
    "GEMINI_MODELS",
    "DEEPSEEK_MODELS",
    "DEFAULT_MAX_TOKENS",
    "HttpxPoolConfig",
    "build_tier_clients",
]
