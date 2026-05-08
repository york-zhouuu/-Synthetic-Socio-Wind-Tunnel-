"""Tests for metrics ↔ ConversationService target_audience integration."""

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
    led.current_time = datetime(2026, 5, 8)
    for aid in agent_ids:
        led.set_entity(EntityState(
            entity_id=aid, position=Coord(x=0, y=0), location_id="home",
        ))
    return led


def _tick(tick: int, day: int) -> TickResult:
    return TickResult(
        tick_index=tick, day_index=day,
        simulated_time=datetime(2026, 5, 8),
        commits=(), encounter_candidates=(),
    )


def _info(info_id: str, day: int = 0,
          target_tags: tuple[str, ...] = ()) -> Information:
    return Information(
        info_id=info_id, content=info_id, category="push",
        salience=0.8, origin_tick=0, origin_agent_id="emma",
        origin_day_index=day, target_audience_tags=target_tags,
    )


class TestRunMetricsTargetPrecision:

    def test_filled_when_audience_provider_present(self):
        from synthetic_socio_wind_tunnel.metrics.factory import build_run_metrics

        def audience_for(aid: str) -> str:
            return {"a": "parents", "b": "parents", "c": "elderly"}.get(aid, "default")
        conv = ConversationService(seed=42, audience_tag_provider=audience_for)

        # i1: target=parents; reaches a (in), b (in), c (out) — within=2, outside=1
        conv.record_origin(_info("i1", target_tags=("parents",)), "emma", tick=10)
        conv._learn("a", "i1", tick=20, hops=1)  # type: ignore[attr-defined]
        conv._learn("b", "i1", tick=21, hops=1)  # type: ignore[attr-defined]
        conv._learn("c", "i1", tick=22, hops=1)  # type: ignore[attr-defined]

        rec = TickMetricsRecorder(ledger=_ledger(["a"]), conversation=conv)
        rec.on_tick_end(_tick(0, 0))

        mdr = MagicMock()
        mdr.seed = 42
        rm = build_run_metrics(rec, multi_day_result=mdr)

        assert rm.info_propagation_hops is not None
        # within = 2 (a,b); outside = 2 (emma origin=default, c=elderly)
        assert rm.info_propagation_hops["info_within_target_reach"] == 2
        assert rm.info_propagation_hops["info_outside_target_reach"] == 2
        assert rm.info_propagation_hops["target_precision"] == pytest.approx(0.5, abs=1e-3)

    def test_zero_when_no_audience_provider(self):
        from synthetic_socio_wind_tunnel.metrics.factory import build_run_metrics

        conv = ConversationService(seed=42)  # no audience_tag_provider
        conv.record_origin(_info("i1", target_tags=("parents",)), "emma", tick=10)

        rec = TickMetricsRecorder(ledger=_ledger(["a"]), conversation=conv)
        rec.on_tick_end(_tick(0, 0))
        mdr = MagicMock()
        mdr.seed = 42
        rm = build_run_metrics(rec, multi_day_result=mdr)

        assert rm.info_propagation_hops is not None
        assert rm.info_propagation_hops["info_within_target_reach"] == 0
        assert rm.info_propagation_hops["info_outside_target_reach"] == 0
        assert rm.info_propagation_hops["target_precision"] == 0.0


class TestDayMetricsTargetReachToday:

    def test_filled_when_provider_present(self):
        def audience_for(aid: str) -> str:
            return {"a": "parents", "b": "elderly"}.get(aid, "default")
        conv = ConversationService(seed=42, audience_tag_provider=audience_for)
        conv.record_origin(_info("i1", target_tags=("parents",)), "emma", tick=10)
        # Day 0 = ticks [0, 288); a learns on day 0, b learns on day 0
        conv._learn("a", "i1", tick=20, hops=1)  # parents → in target  # type: ignore[attr-defined]
        conv._learn("b", "i1", tick=22, hops=1)  # elderly → out  # type: ignore[attr-defined]

        rec = TickMetricsRecorder(ledger=_ledger(["a"]), conversation=conv)
        rec.on_tick_end(_tick(0, 0))
        snap = rec.snapshot()
        assert snap[0].info_target_reach_today == 1  # only a is within target

    def test_none_when_no_conversation(self):
        rec = TickMetricsRecorder(ledger=_ledger(["a"]), conversation=None)
        rec.on_tick_end(_tick(0, 0))
        snap = rec.snapshot()
        assert snap[0].info_target_reach_today is None
