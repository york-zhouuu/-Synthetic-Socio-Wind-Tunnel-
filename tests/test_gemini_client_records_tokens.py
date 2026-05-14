"""Tests for B6: Gemini tier client records token usage.

Original `_GeminiTierClient.generate` ignored `response.usage_metadata`,
so cost_breakdown.total was always 0 even for paid Gemini runs.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


pytest.importorskip("google.genai", reason="google-genai SDK not installed")

# Tests construct _GeminiTierClient without a real API key. Set a dummy
# env var so genai.Client() doesn't refuse to construct.
import os as _os
_os.environ.setdefault("GEMINI_API_KEY", "dummy-test-key-not-real")

from tier_llm_factory import _GeminiTierClient  # type: ignore


def _make_response(text: str, prompt_tokens: int, completion_tokens: int):
    """Mimic genai.GenerateContentResponse with usage_metadata."""
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt_tokens,
            candidates_token_count=completion_tokens,
        ),
    )


class TestGeminiUsageMetadata:

    def _patch_client(self, client, mock_response):
        """Replace the underlying genai client with a mock that returns mock_response."""
        mock_aio = MagicMock()
        mock_aio.models.generate_content = AsyncMock(return_value=mock_response)
        client._client = MagicMock()
        client._client.aio = mock_aio

    def test_records_tokens_from_usage_metadata(self):
        client = _GeminiTierClient(
            tier="haiku", model="gemini-3-flash-preview", max_tokens=512,
        )
        self._patch_client(client, _make_response("response text", 100, 50))

        result = asyncio.run(client.generate("test prompt"))

        assert result == "response text"
        assert client._last_usage == {
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }

    def test_no_usage_metadata_falls_back_to_none(self):
        client = _GeminiTierClient(
            tier="haiku", model="gemini-3-flash-preview", max_tokens=512,
        )
        # response with no usage_metadata at all
        bad_response = SimpleNamespace(text="ok")
        self._patch_client(client, bad_response)

        result = asyncio.run(client.generate("test"))

        assert result == "ok"
        assert client._last_usage is None

    def test_zero_token_counts_recorded_as_zero(self):
        """Edge: zero is a legitimate value; SHALL NOT be coerced to None."""
        client = _GeminiTierClient(
            tier="nano", model="gemini-3-flash-preview", max_tokens=32,
        )
        self._patch_client(client, _make_response("", 0, 0))

        asyncio.run(client.generate("p"))

        assert client._last_usage == {
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

    def test_consecutive_calls_overwrite_last_usage(self):
        """_last_usage SHALL reflect the most recent call only."""
        client = _GeminiTierClient(
            tier="sonnet", model="gemini-3-flash-preview", max_tokens=1024,
        )
        self._patch_client(client, _make_response("first", 10, 5))
        asyncio.run(client.generate("p1"))
        assert client._last_usage["prompt_tokens"] == 10

        # Second call with different counts
        self._patch_client(client, _make_response("second", 200, 100))
        asyncio.run(client.generate("p2"))
        assert client._last_usage == {"prompt_tokens": 200, "completion_tokens": 100}
