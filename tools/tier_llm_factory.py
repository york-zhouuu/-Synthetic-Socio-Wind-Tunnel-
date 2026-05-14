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
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Literal, Mapping

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
DEFAULT_MAX_TOKENS: dict[Tier, int] = {
    "sonnet": 1024,
    "haiku": 512,
    "nano": 32,
}


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


class _GeminiTierClient:
    """Gemini-backed client. Uses the **async** Gemini SDK (client.aio).

    Critical for performance: the OperationPool's asyncio.gather over
    in-flight ops only parallelizes if the underlying network call is
    truly async. The previous sync wrapper made gather degenerate to
    serial 5-sec calls per op; with `client.aio.models.generate_content`
    a tick's 10 protag reflections can run in parallel (~5x speedup).
    """

    def __init__(
        self,
        *,
        tier: Tier,
        model: str,
        max_tokens: int,
        api_key: str | None = None,
    ) -> None:
        try:
            from google import genai  # type: ignore[import-not-found]
            from google.genai import types as genai_types  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "google-genai SDK not installed; pip install google-genai"
            ) from exc
        # google.genai picks up GEMINI_API_KEY / GOOGLE_API_KEY from env.
        self._client = genai.Client()
        self._types = genai_types
        self._tier = tier
        self._model = model
        self._max_tokens = max_tokens
        # B6 fix: cache last call's token usage so OperationPool can stamp
        # OperationResult.prompt_tokens / completion_tokens for cost_breakdown.
        # Gemini SDK exposes this as response.usage_metadata.{prompt_token_count,
        # candidates_token_count}. None when SDK API path doesn't return it.
        self._last_usage: dict[str, int] | None = None

    async def generate(
        self, prompt: str, *, model: str = "", **_: Any,
    ) -> str:
        # IGNORE external model parameter — handlers pass profile.base_model
        # (e.g. "claude-sonnet-4-6") which Gemini doesn't recognize → 404.
        # Always use self._model (the Gemini-tier model picked at construction).
        # Per-agent model dispatch is the future model-budget capability.
        used_model = self._model
        # thinking_budget=0 — flash-preview defaults to thinking ON which
        # adds latency for ai-town ops. Force off.
        config = self._types.GenerateContentConfig(
            thinking_config=self._types.ThinkingConfig(thinking_budget=0),
        )
        # Timeout + retry (mirrors DeepSeek client tuning, 2026-05-13).
        # Google SDK doesn't expose timeout/max_retries kwargs directly, so
        # wrap with asyncio.wait_for + manual 1-retry. 45s matches DeepSeek
        # tier client; OperationPool task cap (120s) gives 2 attempts headroom.
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                response = await asyncio.wait_for(
                    self._client.aio.models.generate_content(
                        model=used_model,
                        contents=prompt,
                        config=config,
                    ),
                    timeout=45.0,
                )
                break
            except (asyncio.TimeoutError, Exception) as e:
                last_exc = e
                if attempt == 0:
                    # Brief backoff before retry to dodge transient blips
                    await asyncio.sleep(0.5)
                    continue
                raise
        else:
            # All attempts exhausted (shouldn't reach: raise above)
            assert last_exc is not None
            raise last_exc
        # B6 fix: extract token counts from usage_metadata. SDK might omit
        # this on errors / fallback paths — guard with try/except.
        try:
            usage = getattr(response, "usage_metadata", None)
            if usage is not None:
                self._last_usage = {
                    "prompt_tokens": int(getattr(usage, "prompt_token_count", 0) or 0),
                    "completion_tokens": int(
                        getattr(usage, "candidates_token_count", 0) or 0
                    ),
                }
            else:
                self._last_usage = None
        except Exception:
            self._last_usage = None
        return response.text or ""


class _DeepSeekTierClient:
    """DeepSeek-backed async client. Uses the openai SDK with custom
    base_url (DeepSeek's API is OpenAI-compatible).

    Reference: https://api-docs.deepseek.com/zh-cn/

    Tier routing via DEEPSEEK_MODELS:
    - sonnet → deepseek-v4-pro (reasoning / decision / dialogue)
    - haiku  → deepseek-v4-flash (summary / reflection)
    - nano   → deepseek-v4-flash (importance scoring)

    Reads DEEPSEEK_API_KEY from env (or explicit api_key kwarg).

    Token usage recording follows the same `_last_usage` pattern as
    `_GeminiTierClient` so OperationPool can stamp OperationResult.
    """

    def __init__(
        self,
        *,
        tier: Tier,
        model: str,
        max_tokens: int,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
    ) -> None:
        try:
            from openai import AsyncOpenAI  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "openai SDK not installed (used for DeepSeek's "
                "OpenAI-compatible API); pip install openai"
            ) from exc
        # Multi-key rotation (2026-05-13 throughput fix): read comma-separated
        # DEEPSEEK_API_KEYS first; fall back to single DEEPSEEK_API_KEY for
        # backward compat. Each key gets its OWN AsyncOpenAI client + httpx
        # connection pool; generate() round-robins across them. With 2 keys,
        # DeepSeek per-account rate limits get 2x effective ceiling AND TLS
        # blips on one key don't cascade across all calls.
        if api_key is not None:
            keys = [api_key]
        else:
            multi = os.environ.get("DEEPSEEK_API_KEYS")
            if multi:
                keys = [k.strip() for k in multi.split(",") if k.strip()]
            else:
                single = os.environ.get("DEEPSEEK_API_KEY")
                keys = [single] if single else []
        if not keys:
            raise RuntimeError(
                "DEEPSEEK_API_KEY[S] missing — set DEEPSEEK_API_KEYS (comma-"
                "separated) or DEEPSEEK_API_KEY in env, or pass api_key kwarg"
            )
        # Timeout + retry tuning (2026-05-13 D1' incident calibration):
        #
        # openai SDK defaults are timeout=600s × max_retries=2 ≈ 30 min
        # worst-case per call. With 500 concurrent calls per tick under
        # asyncio.gather, one hung connection blocks the entire tick for
        # half an hour — exactly what hit D1' the first time around.
        #
        # Calibration after 2026-05-13 200-agent probe:
        # - Simple "say hi" calls return in 2.7s
        # - Complex prompts (life_history JSON ~1000 tokens) easily hit
        #   30s+; earlier 30s cap was too aggressive and caused many
        #   APITimeoutError falsely.
        # - timeout=45s covers most real workloads, max_retries=1 handles
        #   TLS warmup blips (which clustered in agents 0-9 in the probe).
        # - Worst-case per call: 45 × 2 + ~5s backoff ≈ 95s; OperationPool's
        #   handler wall-clock cap bumped to 120s to give headroom.
        #
        # Concurrency: openai SDK's default httpx max_connections=100 was
        # the secondary D1' bottleneck — 500 in-flight calls per tick ×
        # 100-slot connection pool = 5x serialization even before the hang.
        # Bumped to 600 (matches 500 protag + buffer); separate keepalive
        # cap so we don't burn FDs between ticks.
        self._clients: list[AsyncOpenAI] = []
        try:
            import httpx  # type: ignore[import-not-found]
            for k in keys:
                http_client = httpx.AsyncClient(
                    limits=httpx.Limits(
                        max_connections=600,
                        max_keepalive_connections=100,
                    ),
                    timeout=httpx.Timeout(
                        connect=10.0, read=45.0, write=10.0, pool=30.0,
                    ),
                )
                self._clients.append(AsyncOpenAI(
                    api_key=k,
                    base_url=base_url,
                    timeout=45.0,
                    max_retries=1,
                    http_client=http_client,
                ))
        except ImportError:
            # httpx is a transitive dep of openai, but fall back gracefully
            for k in keys:
                self._clients.append(AsyncOpenAI(
                    api_key=k,
                    base_url=base_url,
                    timeout=45.0,
                    max_retries=1,
                ))
        # Round-robin index (single event-loop, no lock needed for int += 1)
        self._key_idx = 0
        self._n_keys = len(self._clients)
        self._tier = tier
        self._model = model
        self._max_tokens = max_tokens
        # B6 contract: caller's OperationPool reads this to stamp
        # OperationResult.prompt_tokens / completion_tokens.
        self._last_usage: dict[str, int] | None = None

    async def generate(
        self, prompt: str, *, model: str = "", **_: Any,
    ) -> str:
        # Ignore caller's `model` kwarg — handlers pass profile.base_model
        # (a Claude/Gemini name) which DeepSeek doesn't recognize. Always
        # use self._model (the DeepSeek-tier model picked at construction).
        used_model = self._model
        # Multi-key round-robin: pick next client. Pre-increment so two
        # concurrent calls (in same event loop tick) get distinct keys when
        # n_keys >= 2.
        client = self._clients[self._key_idx % self._n_keys]
        self._key_idx += 1
        # 2026-05-11: Force-disable chain-of-thought reasoning.
        # DeepSeek's v4-pro reasoner adds 5-10x latency from generating
        # `reasoning_content` before final `content`. We pass BOTH
        # `thinking={"type": "disabled"}` (the working flag in our tests —
        # cuts latency from 7.7s → 1.7s, reasoning_len 906 → 0) AND
        # `enable_thinking=False` (suspenders + belt — covers different
        # DeepSeek model variants that may accept one but not the other).
        try:
            response = await client.chat.completions.create(
                model=used_model,
                max_tokens=self._max_tokens,
                messages=[{"role": "user", "content": prompt}],
                extra_body={
                    "thinking": {"type": "disabled"},
                    "enable_thinking": False,
                },
            )
        except Exception:
            self._last_usage = None
            raise

        # Record usage for cost tracking (B6 contract).
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


class _AnthropicTierClient:
    """Anthropic-backed client with per-tier model + max_tokens.

    Wraps the synchronous Anthropic SDK in an `async def generate`
    matching `LLMClient` protocol. No retry / no rate limiting (matches
    suite_stub_llm._AnthropicClient).
    """

    def __init__(
        self,
        *,
        tier: Tier,
        model: str,
        max_tokens: int,
        api_key: str | None = None,
    ) -> None:
        try:
            from anthropic import Anthropic  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "anthropic SDK not installed; pip install anthropic"
            ) from exc
        self._client = Anthropic(api_key=api_key) if api_key else Anthropic()
        self._tier = tier
        self._model = model
        self._max_tokens = max_tokens

    async def generate(
        self, prompt: str, *, model: str = "", **_: Any,
    ) -> str:
        used_model = model or self._model
        response = self._client.messages.create(
            model=used_model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text_parts: list[str] = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
        return "".join(text_parts)


def build_tier_clients(
    *,
    provider: Provider = "stub",
    models: Mapping[Tier, str] | None = None,
    max_tokens: Mapping[Tier, int] | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Return a `{tier_name: LLMClient}` mapping for OperationPool.

    Args:
        provider: "anthropic" for real calls; "stub" for deterministic
            no-cost test clients.
        models: optional override per tier; missing tiers fall back to
            DEFAULT_MODELS.
        max_tokens: optional override per tier.
        api_key: explicit API key (else picked from ANTHROPIC_API_KEY).

    Returns:
        dict[str, LLMClient] with keys "sonnet", "haiku", "nano".
    """
    model_map: dict[Tier, str] = {**DEFAULT_MODELS, **(models or {})}
    tokens_map: dict[Tier, int] = {**DEFAULT_MAX_TOKENS, **(max_tokens or {})}

    if provider == "stub":
        return {
            "sonnet": _StubTierClient("sonnet"),
            "haiku": _StubTierClient("haiku"),
            "nano": _StubTierClient("nano"),
        }
    if provider == "anthropic":
        # Pull api_key from env once; reuse across tiers.
        eff_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if eff_key is None:
            logger.warning(
                "tier_llm_factory: provider=anthropic but no api_key found "
                "in args or ANTHROPIC_API_KEY env; SDK may fail at first call"
            )
        return {
            "sonnet": _AnthropicTierClient(
                tier="sonnet",
                model=model_map["sonnet"],
                max_tokens=tokens_map["sonnet"],
                api_key=eff_key,
            ),
            "haiku": _AnthropicTierClient(
                tier="haiku",
                model=model_map["haiku"],
                max_tokens=tokens_map["haiku"],
                api_key=eff_key,
            ),
            "nano": _AnthropicTierClient(
                tier="nano",
                model=model_map["nano"],
                max_tokens=tokens_map["nano"],
                api_key=eff_key,
            ),
        }
    if provider == "gemini":
        # Use Gemini-specific model defaults unless user overrode
        gemini_model_map = {**GEMINI_MODELS, **(models or {})}
        if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
            logger.warning(
                "tier_llm_factory: provider=gemini but no GEMINI_API_KEY / "
                "GOOGLE_API_KEY in env; SDK may fail at first call"
            )
        return {
            "sonnet": _GeminiTierClient(
                tier="sonnet",
                model=gemini_model_map["sonnet"],
                max_tokens=tokens_map["sonnet"],
            ),
            "haiku": _GeminiTierClient(
                tier="haiku",
                model=gemini_model_map["haiku"],
                max_tokens=tokens_map["haiku"],
            ),
            "nano": _GeminiTierClient(
                tier="nano",
                model=gemini_model_map["nano"],
                max_tokens=tokens_map["nano"],
            ),
        }
    if provider == "deepseek":
        # Use DeepSeek-specific model defaults unless user overrode.
        deepseek_model_map = {**DEEPSEEK_MODELS, **(models or {})}
        eff_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if eff_key is None:
            logger.warning(
                "tier_llm_factory: provider=deepseek but no DEEPSEEK_API_KEY "
                "in env; SDK will fail at first call"
            )
        return {
            "sonnet": _DeepSeekTierClient(
                tier="sonnet",
                model=deepseek_model_map["sonnet"],
                max_tokens=tokens_map["sonnet"],
                api_key=eff_key,
            ),
            "haiku": _DeepSeekTierClient(
                tier="haiku",
                model=deepseek_model_map["haiku"],
                max_tokens=tokens_map["haiku"],
                api_key=eff_key,
            ),
            "nano": _DeepSeekTierClient(
                tier="nano",
                model=deepseek_model_map["nano"],
                max_tokens=tokens_map["nano"],
                api_key=eff_key,
            ),
        }
    raise ValueError(f"unknown provider {provider!r}")


__all__ = [
    "Tier",
    "Provider",
    "DEFAULT_MODELS",
    "GEMINI_MODELS",
    "DEEPSEEK_MODELS",
    "DEFAULT_MAX_TOKENS",
    "build_tier_clients",
]
