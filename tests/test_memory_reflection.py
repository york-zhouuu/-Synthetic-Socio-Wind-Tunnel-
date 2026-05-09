"""Tests for ReflectionService (agent-stack-aitown-port Phase B).

Verifies 1:1 ai-town fidelity:
- importance threshold trigger (sum > 500 in 0-9; we use 50 in [0,1])
- prompt structure matches ai-town verbatim
- JSON parse tolerance (markdown fences, prose wrappers)
- related_memory_ids back-resolved from statementIds
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from synthetic_socio_wind_tunnel.memory.embedding import NullEmbedding
from synthetic_socio_wind_tunnel.memory.embeddings_cache import EmbeddingsCache
from synthetic_socio_wind_tunnel.memory.importance import ImportanceScorer
from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
from synthetic_socio_wind_tunnel.memory.reflection import (
    DEFAULT_IMPORTANCE_THRESHOLD,
    ReflectionService,
    _build_reflection_prompt,
)


class _StubLLM:
    def __init__(self, response: str = "[]") -> None:
        self.response = response
        self.calls: list[str] = []

    async def generate(self, prompt: str, *, model: str = "", **kw) -> str:
        self.calls.append(prompt)
        return self.response


def _ev(content: str, importance: float = 0.5, *, ts_offset_min: int = 0) -> MemoryEvent:
    return MemoryEvent(
        event_id=f"ev_{content[:5]}",
        agent_id="emma", tick=0,
        simulated_time=datetime(2026, 5, 9, 10, 0) + timedelta(minutes=ts_offset_min),
        kind="encounter", content=content,
        importance=importance,
    )


def _eid_factory(agent_id: str, n: int) -> str:
    return f"ref_{agent_id}_{n}"


# ---------------------------------------------------------------------------
# 1. Should-reflect gate
# ---------------------------------------------------------------------------


class TestShouldReflect:

    def test_empty_returns_false(self):
        svc = ReflectionService(llm_client=_StubLLM())
        assert svc.should_reflect([], last_reflection_time=None) is False

    def test_below_threshold_returns_false(self):
        svc = ReflectionService(llm_client=_StubLLM())
        # 10 × 0.5 = 5.0; threshold default 50 → not triggered
        events = [_ev(f"m{i}", importance=0.5) for i in range(10)]
        assert svc.should_reflect(events, last_reflection_time=None) is False

    def test_above_threshold_returns_true(self):
        svc = ReflectionService(llm_client=_StubLLM())
        # 60 × 1.0 = 60.0 > 50 default → triggered
        events = [_ev(f"m{i}", importance=1.0) for i in range(60)]
        assert svc.should_reflect(events, last_reflection_time=None) is True

    def test_only_post_last_reflection_count(self):
        svc = ReflectionService(llm_client=_StubLLM())
        # 100 importance=0.5 events at minutes 0..99 (sum=50 ≯ 50, exactly threshold)
        events = [_ev(f"m{i}", importance=0.5, ts_offset_min=i) for i in range(100)]
        cutoff = events[80].simulated_time  # only events after #80
        # 19 events × 0.5 = 9.5; sum > 50? no
        assert svc.should_reflect(events, last_reflection_time=cutoff) is False

    def test_force_day_end_overrides(self):
        svc = ReflectionService(llm_client=_StubLLM())
        # No events but force=True → reflect
        assert svc.should_reflect([], last_reflection_time=None,
                                   force_for_day_end=True) is True

    def test_custom_threshold(self):
        svc = ReflectionService(
            llm_client=_StubLLM(), importance_threshold=10.0,
        )
        events = [_ev(f"m{i}", importance=0.5) for i in range(30)]  # sum 15
        assert svc.should_reflect(events, last_reflection_time=None) is True


# ---------------------------------------------------------------------------
# 2. Prompt structure (1:1 ai-town)
# ---------------------------------------------------------------------------


class TestPromptStructure:

    def test_contains_ai_town_markers(self):
        events = [_ev("walked past library"), _ev("had coffee with linda")]
        prompt = _build_reflection_prompt(agent_name="Emma", memories=events)
        # ai-town's verbatim opening (memory.ts:350)
        assert prompt.startswith("[no prose]\n[Output only JSON]\n")
        # name + "statements about you"
        assert "You are Emma, statements about you:" in prompt
        # 2 statements
        assert "Statement 0: walked past library" in prompt
        assert "Statement 1: had coffee with linda" in prompt
        # 3 high-level insights ask
        assert "3 high-level insights" in prompt
        # JSON example
        assert "statementIds" in prompt


# ---------------------------------------------------------------------------
# 3. Reflect — happy path
# ---------------------------------------------------------------------------


class TestReflectHappyPath:

    def test_returns_3_reflection_events(self):
        json_response = (
            '['
            '{"insight": "I value routine", "statementIds": [0, 1]},'
            '{"insight": "I trust linda", "statementIds": [1]},'
            '{"insight": "Library is calm", "statementIds": [0]}'
            ']'
        )
        svc = ReflectionService(llm_client=_StubLLM(json_response))
        events = [_ev("walked past library"), _ev("had coffee with linda")]
        out = asyncio.run(svc.reflect(
            "emma", "Emma", events,
            current_tick=10, simulated_time=datetime(2026, 5, 9, 10),
            day_index=2, event_id_factory=_eid_factory,
        ))
        assert len(out) == 3
        assert out[0].kind == "reflection"
        assert out[0].content == "I value routine"
        assert out[0].related_memory_ids == ("ev_walke", "ev_had c")
        assert out[0].importance == 0.8  # default reflection importance
        assert out[0].tags == ("reflection",)

    def test_bad_statement_ids_clamped(self):
        # statementIds includes out-of-range index
        json_response = (
            '[{"insight": "test", "statementIds": [0, 999, -1]}]'
        )
        svc = ReflectionService(llm_client=_StubLLM(json_response))
        events = [_ev("a"), _ev("b")]
        out = asyncio.run(svc.reflect(
            "emma", "E", events,
            current_tick=1, simulated_time=datetime(2026, 5, 9),
            day_index=0, event_id_factory=_eid_factory,
        ))
        # Only id 0 is valid (1 doesn't exist; 999 / -1 dropped)
        assert out[0].related_memory_ids == ("ev_a",)


# ---------------------------------------------------------------------------
# 4. Parse tolerance (markdown fences, leading prose)
# ---------------------------------------------------------------------------


class TestParseTolerance:

    def test_markdown_code_fence(self):
        wrapped = (
            '```json\n'
            '[{"insight": "test", "statementIds": [0]}]\n'
            '```'
        )
        svc = ReflectionService(llm_client=_StubLLM(wrapped))
        out = asyncio.run(svc.reflect(
            "e", "E", [_ev("m")],
            current_tick=1, simulated_time=datetime(2026, 5, 9),
            day_index=0, event_id_factory=_eid_factory,
        ))
        assert len(out) == 1

    def test_leading_prose_with_array_inside(self):
        wrapped = (
            'Here are my insights:\n'
            '[{"insight": "ok", "statementIds": [0]}]'
        )
        svc = ReflectionService(llm_client=_StubLLM(wrapped))
        out = asyncio.run(svc.reflect(
            "e", "E", [_ev("m")],
            current_tick=1, simulated_time=datetime(2026, 5, 9),
            day_index=0, event_id_factory=_eid_factory,
        ))
        assert len(out) == 1

    def test_invalid_json_returns_empty(self):
        svc = ReflectionService(llm_client=_StubLLM("garbage no json here"))
        out = asyncio.run(svc.reflect(
            "e", "E", [_ev("m")],
            current_tick=1, simulated_time=datetime(2026, 5, 9),
            day_index=0, event_id_factory=_eid_factory,
        ))
        assert out == []

    def test_non_array_json_returns_empty(self):
        svc = ReflectionService(llm_client=_StubLLM('{"ok": "no"}'))
        out = asyncio.run(svc.reflect(
            "e", "E", [_ev("m")],
            current_tick=1, simulated_time=datetime(2026, 5, 9),
            day_index=0, event_id_factory=_eid_factory,
        ))
        assert out == []


# ---------------------------------------------------------------------------
# 5. LLM failure → empty list (no exception)
# ---------------------------------------------------------------------------


class TestFailureFallback:

    def test_llm_raises_returns_empty(self):
        class Raising:
            async def generate(self, prompt, *, model="", **kw):
                raise RuntimeError("LLM down")

        svc = ReflectionService(llm_client=Raising())
        out = asyncio.run(svc.reflect(
            "e", "E", [_ev("m")],
            current_tick=1, simulated_time=datetime(2026, 5, 9),
            day_index=0, event_id_factory=_eid_factory,
        ))
        assert out == []


# ---------------------------------------------------------------------------
# 6. Integration with importance + embeddings
# ---------------------------------------------------------------------------


class TestWithImportanceScorerAndEmbeddings:

    def test_importance_scorer_used(self):
        json_response = '[{"insight": "ok", "statementIds": [0]}]'
        # Importance scorer returns "9" → 1.0
        scorer = ImportanceScorer(llm_client=_StubLLM("9"))
        svc = ReflectionService(
            llm_client=_StubLLM(json_response),
            importance_scorer=scorer,
        )
        out = asyncio.run(svc.reflect(
            "e", "E", [_ev("m")],
            current_tick=1, simulated_time=datetime(2026, 5, 9),
            day_index=0, event_id_factory=_eid_factory,
        ))
        assert out[0].importance == pytest.approx(1.0)

    def test_embedding_attached(self):
        json_response = '[{"insight": "ok", "statementIds": [0]}]'
        cache = EmbeddingsCache(provider=NullEmbedding())
        svc = ReflectionService(
            llm_client=_StubLLM(json_response),
            embeddings_cache=cache,
        )
        out = asyncio.run(svc.reflect(
            "e", "E", [_ev("m")],
            current_tick=1, simulated_time=datetime(2026, 5, 9),
            day_index=0, event_id_factory=_eid_factory,
        ))
        assert out[0].embedding is not None
        assert len(out[0].embedding) > 0
