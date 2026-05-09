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

import logging
import os
from typing import Any, Literal, Mapping

logger = logging.getLogger(__name__)


Tier = Literal["sonnet", "haiku", "nano"]
Provider = Literal["anthropic", "gemini", "stub"]


# Default model per tier. Override via env or build_tier_clients(models=...).
DEFAULT_MODELS: dict[Tier, str] = {
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
    # "nano" tier maps to haiku (no nano model exists); the OperationPool
    # uses it for score_importance which is cheap (single int).
    "nano": "claude-haiku-4-5-20251001",
}

# Gemini equivalents — flash is fastest/cheapest. All 3 tiers route to
# the same flash model for v1; tier routing differentiates max_tokens
# only. Future model-budget change can split tiers across pro/flash.
GEMINI_MODELS: dict[Tier, str] = {
    "sonnet": "gemini-3-flash-preview",
    "haiku": "gemini-3-flash-preview",
    "nano": "gemini-3-flash-preview",
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
        # Use the ASYNC client — actual non-blocking call.
        response = await self._client.aio.models.generate_content(
            model=used_model,
            contents=prompt,
            config=config,
        )
        return response.text or ""


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
    raise ValueError(f"unknown provider {provider!r}")


__all__ = [
    "Tier",
    "Provider",
    "DEFAULT_MODELS",
    "DEFAULT_MAX_TOKENS",
    "build_tier_clients",
]
