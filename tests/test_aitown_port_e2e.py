"""End-to-end smoke for the ai-town port stack.

Verifies the full chain wires together without LLM or orchestrator failure:
- sample_population with generate_identity (stub LLM) fills identity_text
- DialogueService schedule + advance + end + bridge writes 3-way fan-out
- OperationPool processes scheduled ops with stub handlers
- TickMetricsRecorder pulls reflection_count / dialogue_count / op stats
- Inspector helpers don't blow up on populated state

This is a STRUCTURAL test, not a behavior validation — it ensures the
pieces fit together. Behavioral asserts (reflection ≥ 1/agent/day, dialogue
≥ 1/protag-pair) require real plan-driven runs and are kept thin here.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from synthetic_socio_wind_tunnel.agent.operations.handlers import (
    handle_do_something,
    handle_generate_message,
    handle_remember_conversation,
)
from synthetic_socio_wind_tunnel.agent.operations.models import (
    OperationResult,
    PendingOp,
)
from synthetic_socio_wind_tunnel.agent.operations.pool import OperationPool
from synthetic_socio_wind_tunnel.agent.population import (
    LANE_COVE_PROFILE,
    sample_population,
)
from synthetic_socio_wind_tunnel.conversation.dialogue_service import (
    DialogueService,
)
from synthetic_socio_wind_tunnel.conversation.service import ConversationService
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.memory.embedding import NullEmbedding
from synthetic_socio_wind_tunnel.memory.embeddings_cache import EmbeddingsCache
from synthetic_socio_wind_tunnel.memory.importance import ImportanceScorer
from synthetic_socio_wind_tunnel.memory.reflection import ReflectionService
from synthetic_socio_wind_tunnel.memory.service import MemoryService
from synthetic_socio_wind_tunnel.metrics import (
    TickMetricsRecorder,
    build_run_metrics,
)
from synthetic_socio_wind_tunnel.social_graph import SocialGraphService

# Tier factory
from tools.tier_llm_factory import build_tier_clients


_T0 = datetime(2026, 5, 9, 8)


class _StubLLM:
    """Returns a fixed JSON for identity / canned response otherwise."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def generate(self, prompt: str, *, model: str = "", **_) -> str:
        self.calls.append(prompt)
        # Identity prompt — covers both legacy English ("Output JSON ONLY")
        # and new Chinese ("只输出 JSON") archetype-grounded format.
        is_identity_prompt = (
            ("Output JSON ONLY" in prompt and "identity" in prompt)
            or ("只输出 JSON" in prompt and "identity" in prompt)
            or ("archetype" in prompt.lower() and "plan" in prompt)
        )
        if is_identity_prompt:
            return json.dumps({
                "identity": "A 30-something who likes the local cafe.",
                "plan": "Wander around the area today.",
            })
        if "decided to leave" in prompt:
            return "Got to run, see you later!"
        if "you just started a conversation" in prompt:
            return "Hey, nice running into you!"
        if "currently in a conversation" in prompt:
            return "Yeah for sure."
        if "summarize the conversation" in prompt:
            return "Had a friendly chat about the area."
        if 'On scale 0-9' in prompt or 'rate poignancy' in prompt:
            return "5"
        if '"action"' in prompt:
            return json.dumps({"action": "wait"})
        return "ok"


# ---------------------------------------------------------------------------


class TestE2ESmoke:

    def test_population_sample_with_identity_fills_protagonists(self):
        profile = LANE_COVE_PROFILE.model_copy(update={"size": 6})
        llm = _StubLLM()
        profiles = sample_population(
            profile, seed=42, num_protagonists=3,
            generate_identity=True, llm_client=llm,
        )
        protag = [p for p in profiles if p.is_protagonist]
        assert len(protag) == 3
        for p in protag:
            # Protag identity comes from LLM stub (canned "A 30...")
            assert p.identity_text and p.identity_text.startswith("A 30")
            assert p.plan_text == "Wander around the area today."
        # Scripted agents may now have archetype-template-filled identity
        # (Stage 1 lane cove archetypes), but they should NOT have the
        # LLM stub response.
        scripted = [p for p in profiles if not p.is_protagonist]
        for p in scripted:
            if p.identity_text is not None:
                assert not p.identity_text.startswith("A 30"), (
                    "scripted should never have the LLM stub response"
                )

    def test_dialogue_full_lifecycle_with_bridge(self):
        """Full lifecycle: invite → accept → participate → messages →
        end → bridge to memory + propagation + social_graph."""
        dsvc = DialogueService(seed=1)
        msvc = MemoryService()
        csvc = ConversationService(seed=1)
        gsvc = SocialGraphService()

        d = dsvc.schedule_invite(
            "emma", "linda", "cafe", tick=10, simulated_time=_T0,
        )
        dsvc.accept_invite(d.dialogue_id, "linda")
        dsvc.advance_to_participating(d.dialogue_id, tick=11)
        for i in range(3):
            sp = "emma" if i % 2 == 0 else "linda"
            dsvc.append_message(
                d.dialogue_id, sp, f"msg {i}",
                tick=12 + i,
                simulated_time=_T0 + timedelta(minutes=i * 2),
            )
        dsvc.end(
            d.dialogue_id, "leave", tick=20,
            simulated_time=_T0 + timedelta(minutes=10),
        )

        result = dsvc.bridge_to_memory_and_propagation(
            d.dialogue_id,
            memory_service=msvc, conversation_service=csvc, social_graph=gsvc,
            simulated_time=_T0 + timedelta(minutes=11),
            summary="Friendly chat about the cafe.",
        )
        assert result["skipped"] is False
        # 3-way fan-out check
        assert len(msvc.all_for("emma")) == 1
        assert len(msvc.all_for("linda")) == 1
        assert csvc.info_count() == 1
        assert gsvc.get_tie("emma", "linda") is not None

    def test_operation_pool_with_real_handlers_and_stub_llm(self):
        """Verify the wired stack: tier factory → pool → handlers."""
        clients = build_tier_clients(provider="stub")
        pool = OperationPool(
            handlers={
                "do_something": handle_do_something,
                "generate_message": handle_generate_message,
                "remember_conversation": handle_remember_conversation,
            },
            llm_clients=clients,
        )
        # Schedule a do_something; expect stub returns {"action":"wait"}
        op = PendingOp(
            op_id="op1", agent_id="emma", kind="do_something",
            created_tick=0, timeout_tick=24,
            args={
                "agent_name": "Emma",
                "current_location_id": "park",
                "current_time": "10:00",
            },
        )
        pool.schedule(op)
        results = asyncio.run(pool.process_pending(current_tick=1))
        assert len(results) == 1
        r = results[0]
        assert r.success is True
        assert r.payload.get("action") == "wait"

    def test_reflection_via_memory_service(self):
        """ReflectionService writes reflection events through MemoryService."""
        scorer = ImportanceScorer(llm_client=_StubLLM())
        cache = EmbeddingsCache(NullEmbedding())
        ref = ReflectionService(
            llm_client=_ReflectionStubLLM(),
            importance_threshold=0.0,  # always trigger
        )
        msvc = MemoryService(
            importance_scorer=scorer,
            reflection_service=ref,
            embeddings_cache=cache,
            protagonist_ids=("emma",),
            retrieval_mode="aitown",
        )
        # Inject some recent action memories so should_reflect can fire
        from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
        for i in range(5):
            msvc.record("emma", MemoryEvent(
                event_id=f"a{i}", agent_id="emma", tick=i,
                simulated_time=_T0 + timedelta(minutes=i * 5),
                kind="action", content=f"did action {i}",
                importance=0.5,
            ))
        events = asyncio.run(msvc.maybe_reflect(
            "emma", "Emma",
            current_tick=10, simulated_time=_T0 + timedelta(hours=1),
            day_index=0, force_for_day_end=True,
        ))
        # Reflection events written
        all_evs = msvc.all_for("emma")
        reflection_evs = [e for e in all_evs if e.kind == "reflection"]
        assert len(reflection_evs) == len(events)
        assert len(reflection_evs) >= 1


class _ReflectionStubLLM:
    """Returns a hardcoded reflection JSON suitable for ReflectionService."""

    async def generate(self, prompt, *, model="", **_):
        return json.dumps([
            {"insight": "Emma values quiet days.",
             "source_event_ids": ["a0", "a1"]},
            {"insight": "Routines anchor emotional state.",
             "source_event_ids": ["a2", "a3"]},
            {"insight": "Familiar places feel restorative.",
             "source_event_ids": ["a4"]},
        ])


# ---------------------------------------------------------------------------
# Metrics integration smoke
# ---------------------------------------------------------------------------


class TestMetricsE2E:

    def test_metrics_pulls_aitown_fields(self):
        """build_run_metrics returns populated reflection/dialogue/op fields
        when corresponding services are wired into TickMetricsRecorder."""
        ledger = Ledger()
        ledger.current_time = _T0
        msvc = MemoryService(protagonist_ids=("emma",))
        from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
        msvc.record("emma", MemoryEvent(
            event_id="r1", agent_id="emma", tick=10,
            simulated_time=_T0, kind="reflection",
            content="An insight.",
        ))

        dsvc = DialogueService(seed=1)
        d = dsvc.schedule_invite(
            "emma", "linda", "cafe", tick=10, simulated_time=_T0,
        )
        dsvc.accept_invite(d.dialogue_id, "linda")
        dsvc.advance_to_participating(d.dialogue_id, tick=11)
        dsvc.append_message(
            d.dialogue_id, "emma", "hi",
            tick=12, simulated_time=_T0 + timedelta(minutes=5),
        )
        dsvc.end(
            d.dialogue_id, "leave",
            tick=15, simulated_time=_T0 + timedelta(minutes=10),
        )

        recorder = TickMetricsRecorder(
            ledger=ledger,
            memory_service=msvc,
            dialogue_service=dsvc,
        )

        from unittest.mock import MagicMock
        mdr = MagicMock()
        mdr.seed = 42
        metrics = build_run_metrics(recorder, multi_day_result=mdr)

        assert metrics.reflection_count == 1
        assert metrics.dialogue_count == 1
        assert metrics.dialogue_avg_length == 1.0
