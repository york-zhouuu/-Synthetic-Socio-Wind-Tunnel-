"""Tests for ImportanceScorer (agent-stack-aitown-port Phase A)."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.memory.importance import ImportanceScorer
from synthetic_socio_wind_tunnel.memory.models import MemoryEvent


def _event(content: str = "had coffee with linda") -> MemoryEvent:
    return MemoryEvent(
        event_id="ev1", agent_id="emma", tick=10,
        simulated_time=datetime(2026, 5, 8, 8, 0),
        kind="encounter", content=content,
        urgency=0.3, importance=0.5,
    )


class _StubLLM:
    """Test double LLMClient returning a configured response."""

    def __init__(self, response: str = "5", *, raise_exc: bool = False) -> None:
        self.response = response
        self.raise_exc = raise_exc
        self.calls: list[str] = []

    async def generate(self, prompt: str, *, model: str = "", **kw) -> str:
        self.calls.append(prompt)
        if self.raise_exc:
            raise RuntimeError("LLM down")
        return self.response


class TestParseSimpleDigit:

    @pytest.mark.parametrize("response,expected", [
        ("0", 0.0),
        ("5", pytest.approx(5 / 9, abs=1e-3)),
        ("9", 1.0),
    ])
    def test_pure_digit(self, response, expected):
        scorer = ImportanceScorer(llm_client=_StubLLM(response=response))
        result = asyncio.run(scorer.score(_event()))
        assert result == expected

    def test_with_whitespace(self):
        scorer = ImportanceScorer(llm_client=_StubLLM(response="  7  \n"))
        result = asyncio.run(scorer.score(_event()))
        assert result == pytest.approx(7 / 9, abs=1e-3)

    def test_with_prefix(self):
        scorer = ImportanceScorer(llm_client=_StubLLM(response="Importance: 8"))
        result = asyncio.run(scorer.score(_event()))
        assert result == pytest.approx(8 / 9, abs=1e-3)


class TestFailureFallback:

    def test_llm_raises_returns_default(self):
        scorer = ImportanceScorer(llm_client=_StubLLM(raise_exc=True))
        result = asyncio.run(scorer.score(_event()))
        assert result == 0.5  # default

    def test_no_digit_returns_default(self):
        scorer = ImportanceScorer(llm_client=_StubLLM(response="not a number"))
        result = asyncio.run(scorer.score(_event()))
        assert result == 0.5

    def test_empty_response_returns_default(self):
        scorer = ImportanceScorer(llm_client=_StubLLM(response=""))
        result = asyncio.run(scorer.score(_event()))
        assert result == 0.5

    def test_empty_content_skips_llm(self):
        stub = _StubLLM(response="9")
        scorer = ImportanceScorer(llm_client=stub)
        empty_event = _event(content="")
        result = asyncio.run(scorer.score(empty_event))
        assert result == 0.5
        assert len(stub.calls) == 0  # didn't call LLM

    def test_custom_default(self):
        scorer = ImportanceScorer(
            llm_client=_StubLLM(raise_exc=True),
            default_on_failure=0.3,
        )
        result = asyncio.run(scorer.score(_event()))
        assert result == 0.3


class TestBatch:

    def test_batch_scores_all(self):
        stub = _StubLLM(response="5")
        scorer = ImportanceScorer(llm_client=stub)
        events = [_event(content=f"mem {i}") for i in range(7)]
        results = asyncio.run(scorer.score_batch(events, batch_size=3))
        assert len(results) == 7
        assert all(r == pytest.approx(5 / 9, abs=1e-3) for r in results)
        assert len(stub.calls) == 7  # one LLM call per event

    def test_batch_empty(self):
        scorer = ImportanceScorer(llm_client=_StubLLM(response="5"))
        results = asyncio.run(scorer.score_batch([], batch_size=3))
        assert results == []


class TestPromptShape:

    def test_prompt_includes_content(self):
        stub = _StubLLM(response="3")
        scorer = ImportanceScorer(llm_client=stub)
        asyncio.run(scorer.score(_event(content="walked past library")))
        assert "walked past library" in stub.calls[0]
        assert "0 to 9" in stub.calls[0]
