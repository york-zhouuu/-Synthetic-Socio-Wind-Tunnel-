"""Tests for TickMetricsRecorder + RunMetrics ↔ ConversationService."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.conversation import ConversationService, Information
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.metrics.recorder import TickMetricsRecorder
from synthetic_socio_wind_tunnel.orchestrator.models import TickResult


def _ledger(agent_ids: list[str]) -> Ledger:
    led = Ledger()
    led.current_time = datetime(2026, 5, 5)
    for aid in agent_ids:
        led.set_entity(EntityState(
            entity_id=aid, position=Coord(x=0, y=0), location_id="home",
        ))
    return led


def _tick(tick: int, day: int) -> TickResult:
    return TickResult(
        tick_index=tick, day_index=day,
        simulated_time=datetime(2026, 5, 5),
        commits=(), encounter_candidates=(),
    )


def _info(info_id: str, day: int = 0, salience: float = 0.8) -> Information:
    return Information(
        info_id=info_id, content=info_id, category="push",
        salience=salience, origin_tick=0, origin_agent_id="emma",
        origin_day_index=day,
    )


class TestRecorderConversationFields:

    def test_no_conversation_keeps_fields_none(self):
        rec = TickMetricsRecorder(ledger=_ledger(["emma"]), conversation=None)
        rec.on_tick_end(_tick(0, 0))
        snap = rec.snapshot()
        assert snap[0].info_origins_today is None
        assert snap[0].info_shares_today is None
        assert snap[0].info_reaching_2plus_today is None
        assert snap[0].avg_hops_today is None

    def test_conversation_injection_fills_fields(self):
        conv = ConversationService(seed=42)
        # Pre-populate: 2 origins on day 0
        conv.record_origin(_info("i1", day=0), "emma", tick=10)
        conv.record_origin(_info("i2", day=0), "emma", tick=20)
        # i1 reaches hops=2 on day 0 (linda hops=1, john hops=2)
        conv._learn("linda", "i1", tick=30, hops=1)  # type: ignore[attr-defined]
        conv._learn("john", "i1", tick=40, hops=2)   # type: ignore[attr-defined]

        rec = TickMetricsRecorder(ledger=_ledger(["emma"]), conversation=conv)
        rec.on_tick_end(_tick(0, 0))
        snap = rec.snapshot()
        d = snap[0]
        assert d.info_origins_today == 2
        assert d.info_reaching_2plus_today == 1  # only i1
        assert d.info_shares_today >= 1


class TestRunMetricsFactory:

    def test_info_propagation_hops_filled_when_present(self):
        from synthetic_socio_wind_tunnel.metrics.factory import build_run_metrics

        conv = ConversationService(seed=42)
        # 3 infos: 1 reaches hops=2, others stay at origin
        conv.record_origin(_info("i1"), "emma", tick=10)
        conv._learn("linda", "i1", tick=20, hops=1)  # type: ignore[attr-defined]
        conv._learn("john", "i1", tick=30, hops=2)   # type: ignore[attr-defined]
        conv.record_origin(_info("i2"), "emma", tick=10)
        conv.record_origin(_info("i3"), "emma", tick=10)

        rec = TickMetricsRecorder(ledger=_ledger(["emma"]), conversation=conv)
        rec.on_tick_end(_tick(0, 0))

        mdr = MagicMock()
        mdr.seed = 42
        rm = build_run_metrics(rec, multi_day_result=mdr)

        assert rm.info_propagation_hops is not None
        assert rm.info_propagation_hops["info_count_total"] == 3
        assert rm.info_propagation_hops["info_reaching_2plus_hops"] == 1
        assert rm.info_propagation_hops["max_hop_observed"] == 2

    def test_info_propagation_hops_none_when_no_conv(self):
        from synthetic_socio_wind_tunnel.metrics.factory import build_run_metrics

        rec = TickMetricsRecorder(ledger=_ledger(["emma"]), conversation=None)
        rec.on_tick_end(_tick(0, 0))
        mdr = MagicMock()
        mdr.seed = 42
        rm = build_run_metrics(rec, multi_day_result=mdr)
        assert rm.info_propagation_hops is None
