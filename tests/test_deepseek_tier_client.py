"""Tests for DeepSeek tier client (added 2026-05-11).

Mock the openai SDK; do NOT hit real API in CI.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Set a dummy key so client construction doesn't refuse.
os.environ.setdefault("DEEPSEEK_API_KEY", "dummy-test-key")


from tools.tier_llm_factory import (  # type: ignore
    DEEPSEEK_MODELS,
    _DeepSeekTierClient,
    build_tier_clients,
)


def _make_response(text: str, prompt_tokens: int, completion_tokens: int):
    """Mimic openai.ChatCompletion response."""
    msg = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(
        choices=[choice],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


class TestDeepSeekModelMap:

    def test_default_models_routed_per_tier(self):
        assert DEEPSEEK_MODELS["sonnet"] == "deepseek-v4-pro"
        assert DEEPSEEK_MODELS["haiku"] == "deepseek-v4-flash"
        assert DEEPSEEK_MODELS["nano"] == "deepseek-v4-flash"


class TestDeepSeekTierClient:

    def _patch_client(self, c, mock_response):
        # run-resilience refactor: client lives at _contexts[0].sdk_client
        mock_create = AsyncMock(return_value=mock_response)
        mock_sdk = MagicMock()
        mock_sdk.chat.completions.create = mock_create
        c._contexts[0].sdk_client = mock_sdk

    def test_records_token_usage(self):
        c = _DeepSeekTierClient(
            tier="haiku", model="deepseek-v4-flash", max_tokens=512,
        )
        self._patch_client(c, _make_response("hello", 100, 50))

        result = asyncio.run(c.generate("test prompt"))

        assert result == "hello"
        assert c._last_usage == {
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }

    def test_no_usage_falls_back_to_none(self):
        c = _DeepSeekTierClient(
            tier="nano", model="deepseek-v4-flash", max_tokens=32,
        )
        bad_resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=None,
        )
        self._patch_client(c, bad_resp)

        result = asyncio.run(c.generate("test"))
        assert result == "ok"
        assert c._last_usage is None

    def test_empty_choices_returns_empty_string(self):
        c = _DeepSeekTierClient(
            tier="sonnet", model="deepseek-v4-pro", max_tokens=1024,
        )
        empty_resp = SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=0),
        )
        self._patch_client(c, empty_resp)

        result = asyncio.run(c.generate("test"))
        assert result == ""

    def test_caller_model_kwarg_ignored(self):
        """generate(model=...) caller param SHALL NOT override self._model.

        Handlers pass profile.base_model (e.g. 'claude-sonnet-...') which
        DeepSeek doesn't recognize. Tier client always uses its own model.
        """
        c = _DeepSeekTierClient(
            tier="sonnet", model="deepseek-v4-pro", max_tokens=1024,
        )
        captured: dict = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            return _make_response("ok", 5, 5)

        mock_sdk = MagicMock()
        mock_sdk.chat.completions.create = fake_create
        c._contexts[0].sdk_client = mock_sdk

        asyncio.run(c.generate("p", model="claude-sonnet-4-6"))
        assert captured["model"] == "deepseek-v4-pro"


class TestBuildTierClientsDeepSeek:

    def test_deepseek_provider_returns_3_tier_clients(self):
        clients = build_tier_clients(
            provider="deepseek", api_key="dummy-key",
        )
        assert set(clients.keys()) == {"sonnet", "haiku", "nano"}
        for c in clients.values():
            assert isinstance(c, _DeepSeekTierClient)

    def test_deepseek_models_per_tier(self):
        clients = build_tier_clients(
            provider="deepseek", api_key="dummy-key",
        )
        assert clients["sonnet"]._model == "deepseek-v4-pro"
        assert clients["haiku"]._model == "deepseek-v4-flash"
        assert clients["nano"]._model == "deepseek-v4-flash"

    def test_deepseek_max_tokens_per_tier(self):
        clients = build_tier_clients(
            provider="deepseek", api_key="dummy-key",
        )
        assert clients["sonnet"]._max_tokens == 1024
        assert clients["haiku"]._max_tokens == 512
        assert clients["nano"]._max_tokens == 32

    def test_deepseek_override_models(self):
        clients = build_tier_clients(
            provider="deepseek", api_key="dummy-key",
            models={"sonnet": "deepseek-custom-x"},
        )
        assert clients["sonnet"]._model == "deepseek-custom-x"
        # Other tiers fall back to defaults
        assert clients["haiku"]._model == "deepseek-v4-flash"


class TestRepLockProvider:

    def test_deepseek_provider_in_rep_lock(self):
        from synthetic_socio_wind_tunnel.metrics.reproducibility import (
            compute_reproducibility_lock,
        )
        lock = compute_reproducibility_lock(
            seed_pool=[42],
            use_real_llm=True,
            variant_names=["baseline"],
            phase_config={"baseline_days": 1, "intervention_days": 1, "post_days": 1},
            provider="deepseek",
        )
        assert lock["provider"] == "deepseek"
        assert "deepseek" in lock["model_version"]
