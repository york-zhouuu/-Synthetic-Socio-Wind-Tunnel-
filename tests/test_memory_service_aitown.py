"""Tests for MemoryService ai-town port integrations (Phase B)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from synthetic_socio_wind_tunnel.memory.embedding import NullEmbedding
from synthetic_socio_wind_tunnel.memory.embeddings_cache import EmbeddingsCache
from synthetic_socio_wind_tunnel.memory.importance import ImportanceScorer
from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
from synthetic_socio_wind_tunnel.memory.reflection import ReflectionService
from synthetic_socio_wind_tunnel.memory.service import MemoryService


class _StubLLM:
    def __init__(self, response: str = "[]") -> None:
        self.response = response

    async def generate(self, prompt: str, *, model: str = "", **kw) -> str:
        return self.response


def _seed_memories(svc: MemoryService, agent_id: str, n: int = 60,
                   importance: float = 1.0) -> None:
    """Push n high-importance events to clear the reflection threshold."""
    base_time = datetime(2026, 5, 9, 10)
    for i in range(n):
        svc.record(agent_id, MemoryEvent(
            event_id=f"seed_{agent_id}_{i}",
            agent_id=agent_id, tick=i,
            simulated_time=base_time + timedelta(minutes=i),
            kind="encounter", content=f"event {i}",
            importance=importance,
        ))


class TestMaybeReflectGated:

    def test_no_reflection_service_returns_empty(self):
        svc = MemoryService()
        out = asyncio.run(svc.maybe_reflect(
            "emma", "Emma",
            current_tick=10, simulated_time=datetime(2026, 5, 9),
            day_index=0,
        ))
        assert out == []

    def test_non_protagonist_skipped(self):
        reflection = ReflectionService(llm_client=_StubLLM())
        svc = MemoryService(
            reflection_service=reflection,
            protagonist_ids=("emma",),  # only emma
        )
        _seed_memories(svc, "linda")  # linda is scripted
        out = asyncio.run(svc.maybe_reflect(
            "linda", "Linda",
            current_tick=10, simulated_time=datetime(2026, 5, 9, 11),
            day_index=0,
        ))
        assert out == []

    def test_protagonist_below_threshold_no_reflect(self):
        reflection = ReflectionService(llm_client=_StubLLM())
        svc = MemoryService(
            reflection_service=reflection,
            protagonist_ids=("emma",),
        )
        # Only 5 events, sum=5 < threshold=50
        _seed_memories(svc, "emma", n=5, importance=1.0)
        out = asyncio.run(svc.maybe_reflect(
            "emma", "Emma",
            current_tick=10, simulated_time=datetime(2026, 5, 9, 11),
            day_index=0,
        ))
        assert out == []


class TestMaybeReflectThresholdHit:

    def test_protagonist_above_threshold_reflects(self):
        json_response = (
            '[{"insight": "I value routine", "statementIds": [0,1]}]'
        )
        reflection = ReflectionService(llm_client=_StubLLM(json_response))
        svc = MemoryService(
            reflection_service=reflection,
            protagonist_ids=("emma",),
        )
        _seed_memories(svc, "emma", n=60, importance=1.0)
        out = asyncio.run(svc.maybe_reflect(
            "emma", "Emma",
            current_tick=100, simulated_time=datetime(2026, 5, 9, 12),
            day_index=0,
        ))
        assert len(out) == 1
        assert out[0].kind == "reflection"
        # Verify it landed in the store
        all_events = svc.all_for("emma")
        assert any(e.kind == "reflection" for e in all_events)

    def test_force_for_day_end_triggers(self):
        json_response = '[{"insight": "ok", "statementIds": [0]}]'
        reflection = ReflectionService(llm_client=_StubLLM(json_response))
        svc = MemoryService(
            reflection_service=reflection,
            protagonist_ids=("emma",),
        )
        # Seed below threshold but force=True → still reflects
        _seed_memories(svc, "emma", n=5, importance=0.5)
        out = asyncio.run(svc.maybe_reflect(
            "emma", "Emma",
            current_tick=10, simulated_time=datetime(2026, 5, 9, 11),
            day_index=0,
            force_for_day_end=True,
        ))
        assert len(out) == 1


class TestMaybeReflectIdempotent:

    def test_same_tick_no_double_reflect(self):
        json_response = '[{"insight": "ok", "statementIds": [0]}]'
        reflection = ReflectionService(llm_client=_StubLLM(json_response))
        svc = MemoryService(
            reflection_service=reflection,
            protagonist_ids=("emma",),
        )
        _seed_memories(svc, "emma", n=60)
        ts = datetime(2026, 5, 9, 12)
        out1 = asyncio.run(svc.maybe_reflect(
            "emma", "Emma",
            current_tick=100, simulated_time=ts, day_index=0,
        ))
        # Second call same simulated_time → no new events
        out2 = asyncio.run(svc.maybe_reflect(
            "emma", "Emma",
            current_tick=100, simulated_time=ts, day_index=0,
        ))
        assert len(out1) == 1
        assert out2 == []


class TestRetrievalMode:

    def test_aitown_mode_uses_normalize_then_sum(self):
        svc = MemoryService(retrieval_mode="aitown")
        # Just verify the retriever is in aitown mode
        assert svc._retriever._mode == "aitown"

    def test_legacy_default_unchanged(self):
        svc = MemoryService()
        assert svc._retriever._mode == "legacy"
