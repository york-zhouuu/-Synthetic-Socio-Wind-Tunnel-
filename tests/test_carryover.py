"""Tests for CarryoverContext + MemoryService cross-day retrieval."""

from __future__ import annotations

from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.memory import (
    CarryoverContext,
    MemoryEvent,
    MemoryService,
)


def _event(agent_id: str, day_index: int, *, kind="action", content="x",
           importance=0.5, tick: int = 0) -> MemoryEvent:
    return MemoryEvent(
        event_id=f"{agent_id}_{day_index}_{tick}",
        agent_id=agent_id,
        tick=tick,
        simulated_time=datetime(2026, 4, 22 + day_index, 10, 0, 0),
        kind=kind,
        content=content,
        importance=importance,
        day_index=day_index,
    )


class TestGetDailySummary:
    def test_missing_returns_none(self):
        m = MemoryService()
        assert m.get_daily_summary("emma", day_index=0) is None

    def test_returns_summary_for_day(self):
        m = MemoryService()
        m.record("emma", _event("emma", 3, kind="daily_summary",
                                content="day 3 was quiet"))
        s = m.get_daily_summary("emma", day_index=3)
        assert s is not None
        assert s.summary_text == "day 3 was quiet"
        assert s.agent_id == "emma"


class TestRecentDailySummaries:
    def test_3_day_window(self):
        m = MemoryService()
        for d in range(6):
            m.record("emma", _event("emma", d, kind="daily_summary",
                                    content=f"day {d}"))
        out = m.get_recent_daily_summaries("emma", last_n_days=3, ref_day_index=5)
        # window (ref - 3, ref) = day 2, 3, 4
        texts = [s.summary_text for s in out]
        assert texts == ["day 2", "day 3", "day 4"]

    def test_empty_when_no_history(self):
        m = MemoryService()
        out = m.get_recent_daily_summaries("emma", last_n_days=3, ref_day_index=0)
        assert out == ()

    def test_auto_ref_uses_max_day(self):
        m = MemoryService()
        for d in (0, 1, 2):
            m.record("emma", _event("emma", d, kind="daily_summary",
                                    content=f"day {d}"))
        # 不传 ref_day_index → 用 max(day_index) = 2 作参考
        out = m.get_recent_daily_summaries("emma", last_n_days=3)
        # window (2-3, 2) = day -1, 0, 1 → 取 day 0, 1
        texts = [s.summary_text for s in out]
        assert texts == ["day 0", "day 1"]


class TestGetCarryoverContext:
    def test_day_0_empty(self):
        m = MemoryService()
        ctx = m.get_carryover_context("emma", current_day_index=0)
        assert isinstance(ctx, CarryoverContext)
        assert ctx.yesterday_summary is None
        assert ctx.recent_reflections == ()

    def test_day_5_full(self):
        m = MemoryService()
        for d in range(5):
            m.record("emma", _event("emma", d, kind="daily_summary",
                                    content=f"day {d}"))
        # 加 3 条 task_received with different importance
        m.record("emma", _event("emma", 2, kind="task_received",
                                content="t1", importance=0.9))
        m.record("emma", _event("emma", 2, kind="task_received",
                                content="t2", importance=0.3))
        m.record("emma", _event("emma", 3, kind="task_received",
                                content="t3", importance=0.7))

        ctx = m.get_carryover_context("emma", current_day_index=5)
        # yesterday = day 4
        assert ctx.yesterday_summary is not None
        assert ctx.yesterday_summary.summary_text == "day 4"
        # recent = day 1, 2, 3（last 3 days of (5-4, 5-1)=day 1-3）
        texts = [s.summary_text for s in ctx.recent_reflections]
        assert texts == ["day 1", "day 2", "day 3"]
        # pending anchors sorted by importance desc, limit 5
        anchors = ctx.pending_task_anchors
        assert len(anchors) == 3
        assert [a.content for a in anchors] == ["t1", "t3", "t2"]  # 0.9, 0.7, 0.3

    def test_pending_task_anchors_max_5(self):
        m = MemoryService()
        for i in range(8):
            m.record("emma", _event("emma", 1, kind="task_received",
                                    content=f"t{i}", importance=0.5 + i * 0.01,
                                    tick=i))
        ctx = m.get_carryover_context("emma", current_day_index=2)
        assert len(ctx.pending_task_anchors) == 5


class TestProcessTickPropagatesDayIndex:
    def test_action_event_inherits_day_index(self):
        from synthetic_socio_wind_tunnel.agent import (
            AgentProfile, AgentRuntime,
        )
        from synthetic_socio_wind_tunnel.agent.intent import MoveIntent
        from synthetic_socio_wind_tunnel.engine.simulation import SimulationResult
        from synthetic_socio_wind_tunnel.orchestrator.models import (
            CommitRecord, TickResult,
        )

        m = MemoryService()
        profile = AgentProfile(
            agent_id="emma", name="Emma", age=30, occupation="x",
            household="single", home_location="a",
        )
        agent = AgentRuntime(profile=profile, current_location="a")

        intent = MoveIntent(to_location="b")
        commit = CommitRecord(
            agent_id="emma",
            intent=intent,
            result=SimulationResult.ok(),
            day_index=4,
        )
        tr = TickResult(
            tick_index=10,
            simulated_time=datetime(2026, 4, 26, 10, 0, 0),
            commits=(commit,),
            encounter_candidates=(),
            day_index=4,
        )
        m.process_tick(tr, {"emma": agent})

        action_events = [e for e in m.all_for("emma") if e.kind == "action"]
        assert len(action_events) == 1
        assert action_events[0].day_index == 4
