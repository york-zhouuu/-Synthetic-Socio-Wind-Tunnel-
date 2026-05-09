"""Tests for ai-town port RunMetrics fields (Phase E task 21).

Verifies build_run_metrics:
- Fills reflection_count / dialogue_count / dialogue_avg_length /
  op_timeout_count / cost_breakdown when services injected
- Leaves them None when services not injected (backwards compat)
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from synthetic_socio_wind_tunnel.agent.operations.models import (
    OperationResult,
    PendingOp,
)
from synthetic_socio_wind_tunnel.conversation.dialogue_service import (
    DialogueService,
)
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
from synthetic_socio_wind_tunnel.memory.service import MemoryService
from synthetic_socio_wind_tunnel.metrics import (
    TickMetricsRecorder,
    build_run_metrics,
)


_T0 = datetime(2026, 5, 9, 8)


def _multi_day_result(seed: int = 42):
    """Mock MultiDayResult with just a `.seed` attribute."""
    mdr = MagicMock()
    mdr.seed = seed
    return mdr


# ---------------------------------------------------------------------------
# Backwards compat: no ai-town services → all 5 new fields None
# ---------------------------------------------------------------------------


class TestBackwardsCompat:

    def test_no_services_all_fields_none(self):
        ledger = Ledger()
        ledger.current_time = _T0
        recorder = TickMetricsRecorder(ledger=ledger)
        metrics = build_run_metrics(
            recorder, multi_day_result=_multi_day_result(),
        )
        assert metrics.reflection_count is None
        assert metrics.dialogue_count is None
        assert metrics.dialogue_avg_length is None
        assert metrics.op_timeout_count is None
        assert metrics.cost_breakdown is None


# ---------------------------------------------------------------------------
# Reflection count
# ---------------------------------------------------------------------------


class TestReflectionCount:

    def test_reflection_count_from_memory_service(self):
        ledger = Ledger()
        ledger.current_time = _T0
        msvc = MemoryService(protagonist_ids=("emma", "linda"))
        # Inject 2 reflection memories for emma, 1 for linda
        for i in range(2):
            msvc.record("emma", MemoryEvent(
                event_id=f"r{i}", agent_id="emma", tick=10 + i,
                simulated_time=_T0, kind="reflection",
                content=f"insight {i}",
            ))
        msvc.record("linda", MemoryEvent(
            event_id="r0", agent_id="linda", tick=12,
            simulated_time=_T0, kind="reflection", content="other insight",
        ))
        # And a non-reflection memory (shouldn't count)
        msvc.record("emma", MemoryEvent(
            event_id="a0", agent_id="emma", tick=15,
            simulated_time=_T0, kind="action", content="walked",
        ))
        recorder = TickMetricsRecorder(ledger=ledger, memory_service=msvc)
        metrics = build_run_metrics(
            recorder, multi_day_result=_multi_day_result(),
        )
        assert metrics.reflection_count == 3  # 2 emma + 1 linda

    def test_reflection_count_zero_when_no_reflections(self):
        ledger = Ledger()
        ledger.current_time = _T0
        msvc = MemoryService(protagonist_ids=("emma",))
        msvc.record("emma", MemoryEvent(
            event_id="a0", agent_id="emma", tick=10,
            simulated_time=_T0, kind="action", content="walked",
        ))
        recorder = TickMetricsRecorder(ledger=ledger, memory_service=msvc)
        metrics = build_run_metrics(
            recorder, multi_day_result=_multi_day_result(),
        )
        assert metrics.reflection_count == 0


# ---------------------------------------------------------------------------
# Dialogue stats
# ---------------------------------------------------------------------------


class TestDialogueStats:

    def test_dialogue_count_and_avg_length(self):
        ledger = Ledger()
        ledger.current_time = _T0
        dsvc = DialogueService(seed=1)
        # Make 2 dialogues with different message counts
        from datetime import timedelta
        d1 = dsvc.schedule_invite(
            "a", "b", "park", tick=10, simulated_time=_T0,
        )
        dsvc.accept_invite(d1.dialogue_id, "b")
        dsvc.advance_to_participating(d1.dialogue_id, tick=11)
        for i in range(4):
            sp = "a" if i % 2 == 0 else "b"
            dsvc.append_message(
                d1.dialogue_id, sp, f"m{i}",
                tick=12 + i,
                simulated_time=_T0 + timedelta(minutes=i),
            )
        dsvc.end(d1.dialogue_id, "leave",
                 tick=20, simulated_time=_T0 + timedelta(minutes=10))

        d2 = dsvc.schedule_invite(
            "a", "c", "cafe", tick=30, simulated_time=_T0 + timedelta(hours=2),
        )
        dsvc.accept_invite(d2.dialogue_id, "c")
        dsvc.advance_to_participating(d2.dialogue_id, tick=31)
        for i in range(2):
            sp = "a" if i % 2 == 0 else "c"
            dsvc.append_message(
                d2.dialogue_id, sp, f"m{i}",
                tick=32 + i,
                simulated_time=_T0 + timedelta(hours=2, minutes=i),
            )
        dsvc.end(d2.dialogue_id, "leave",
                 tick=40, simulated_time=_T0 + timedelta(hours=2, minutes=10))

        recorder = TickMetricsRecorder(ledger=ledger, dialogue_service=dsvc)
        metrics = build_run_metrics(
            recorder, multi_day_result=_multi_day_result(),
        )
        assert metrics.dialogue_count == 2
        # avg of 4 + 2 = 3
        assert metrics.dialogue_avg_length == 3.0


# ---------------------------------------------------------------------------
# Operation pool stats
# ---------------------------------------------------------------------------


class TestOpPoolStats:

    def test_op_timeout_and_cost_breakdown(self):
        ledger = Ledger()
        ledger.current_time = _T0

        # Build a real OperationPool, populate completed_log + timeout_log
        from synthetic_socio_wind_tunnel.agent.operations.pool import (
            OperationPool,
        )

        async def stub(op, *, llm_client, **_):
            return OperationResult(
                op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
                success=True, payload={},
            )

        class _StubLLM:
            async def generate(self, prompt, **_):
                return "x"

        pool = OperationPool(
            handlers={"do_something": stub, "remember_conversation": stub},
            llm_clients={"sonnet": _StubLLM(), "haiku": _StubLLM()},
        )
        # Manually inject completed results with token counts (simulate
        # real run output)
        pool._completed_log.extend([
            OperationResult(
                op_id="op1", agent_id="emma", kind="do_something",
                success=True, prompt_tokens=1000, completion_tokens=200,
            ),
            OperationResult(
                op_id="op2", agent_id="linda", kind="remember_conversation",
                success=True, prompt_tokens=500, completion_tokens=100,
            ),
        ])
        pool._timeout_log.append(PendingOp(
            op_id="op_to", agent_id="bob", kind="do_something",
            created_tick=0, timeout_tick=10, args={},
        ))

        recorder = TickMetricsRecorder(ledger=ledger, operation_pool=pool)
        metrics = build_run_metrics(
            recorder, multi_day_result=_multi_day_result(),
        )
        assert metrics.op_timeout_count == 1
        assert metrics.cost_breakdown is not None
        # do_something defaults to sonnet; remember_conversation → haiku
        assert metrics.cost_breakdown["sonnet"] > 0
        assert metrics.cost_breakdown["haiku"] > 0
        # nano untouched
        assert metrics.cost_breakdown["nano"] == 0.0
        assert metrics.cost_breakdown["total"] == pytest.approx(
            metrics.cost_breakdown["sonnet"]
            + metrics.cost_breakdown["haiku"]
            + metrics.cost_breakdown["nano"]
        )

    def test_no_completed_logs_zero_cost(self):
        from synthetic_socio_wind_tunnel.agent.operations.pool import (
            OperationPool,
        )

        async def stub(op, *, llm_client, **_):
            return OperationResult(
                op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
                success=True,
            )

        class _StubLLM:
            async def generate(self, prompt, **_):
                return "x"

        pool = OperationPool(
            handlers={"do_something": stub},
            llm_clients={"sonnet": _StubLLM()},
        )
        ledger = Ledger()
        ledger.current_time = _T0
        recorder = TickMetricsRecorder(ledger=ledger, operation_pool=pool)
        metrics = build_run_metrics(
            recorder, multi_day_result=_multi_day_result(),
        )
        assert metrics.op_timeout_count == 0
        assert metrics.cost_breakdown == {
            "sonnet": 0.0, "haiku": 0.0, "nano": 0.0, "total": 0.0,
        }
