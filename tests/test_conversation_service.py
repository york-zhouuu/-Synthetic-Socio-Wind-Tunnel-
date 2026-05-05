"""Tests for ConversationService — record / propagate / queries."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
from synthetic_socio_wind_tunnel.conversation import (
    ConversationService,
    Information,
)
from synthetic_socio_wind_tunnel.orchestrator.models import (
    EncounterCandidate,
    TickResult,
)
from synthetic_socio_wind_tunnel.social_graph import SocialGraphService


def _profile(agent_id: str, extraversion: float = 0.5) -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id, name=agent_id.title(), age=30, occupation="x",
        household="single", home_location="home",
        personality=PersonalityTraits(extraversion=extraversion),
    )


def _runtime(agent_id: str, extraversion: float = 0.5) -> AgentRuntime:
    return AgentRuntime(
        profile=_profile(agent_id, extraversion=extraversion),
        current_location="home",
    )


def _info(info_id: str = "i1", salience: float = 0.8, day: int = 0) -> Information:
    return Information(
        info_id=info_id, content="本街市集", category="push",
        salience=salience, origin_tick=10, origin_agent_id="emma",
        origin_day_index=day,
    )


def _tick_result(tick: int, day: int, encs: list[tuple[str, str]]) -> TickResult:
    return TickResult(
        tick_index=tick,
        day_index=day,
        simulated_time=datetime(2026, 5, 5),
        commits=(),
        encounter_candidates=tuple(
            EncounterCandidate(
                agent_a=a, agent_b=b, shared_locations=("cafe",), tick=tick,
            )
            for a, b in encs
        ),
    )


class TestRecordOrigin:

    def test_origin_agent_immediately_knows(self):
        svc = ConversationService(seed=42)
        svc.record_origin(_info(), "emma", tick=10)
        assert "i1" in svc.info_known_by("emma")
        prop = svc.get_propagation("i1")
        assert prop.hops_at["emma"] == 0
        assert prop.reach == 1

    def test_double_record_origin_idempotent(self):
        svc = ConversationService(seed=42)
        svc.record_origin(_info(), "emma", tick=10)
        svc.record_origin(_info(), "emma", tick=10)
        assert svc.info_count() == 1

    def test_unknown_info_returns_none(self):
        svc = ConversationService(seed=42)
        assert svc.get_propagation("nope") is None


class TestProbabilisticShare:

    def _setup(self, *, salience=0.8, day=0, sim_day=0,
               extra_a=0.5, extra_b=0.5, tie_count=0):
        """Return (svc, graph, agents, info) ready for process_tick."""
        svc = ConversationService(seed=42)
        graph = SocialGraphService(K=10)
        # Pre-seed encounters for tie strength if requested
        for tick in range(tie_count):
            graph.record_encounter("emma", "linda", tick=tick)
        agents = {
            "emma": _runtime("emma", extraversion=extra_a),
            "linda": _runtime("linda", extraversion=extra_b),
        }
        info = _info(salience=salience, day=day)
        svc.record_origin(info, "emma", tick=10)
        return svc, graph, agents, info

    def _trial_share_rate(self, salience=0.8, day=0, sim_day=0,
                           extra_a=0.7, extra_b=0.7, tie_count=5,
                           trials=200) -> float:
        """Estimate share rate over many seeded trials."""
        n_share = 0
        for trial in range(trials):
            svc = ConversationService(seed=trial)
            graph = SocialGraphService(K=10)
            for tick in range(tie_count):
                graph.record_encounter("emma", "linda", tick=tick)
            agents = {
                "emma": _runtime("emma", extraversion=extra_a),
                "linda": _runtime("linda", extraversion=extra_b),
            }
            info = _info(salience=salience, day=day)
            svc.record_origin(info, "emma", tick=10)
            tr = _tick_result(20, sim_day, [("emma", "linda")])
            svc.process_tick(tr, graph, sim_day=sim_day, agents=agents)
            if "i1" in svc.info_known_by("linda"):
                n_share += 1
        return n_share / trials

    def test_high_salience_higher_rate(self):
        rate_high = self._trial_share_rate(salience=0.8)
        rate_low = self._trial_share_rate(salience=0.3)
        assert rate_high > rate_low + 0.03, (
            f"high salience {rate_high:.2%} should exceed low {rate_low:.2%}"
        )

    def test_recency_decay(self):
        rate_today = self._trial_share_rate(day=0, sim_day=0)
        rate_old = self._trial_share_rate(day=0, sim_day=9)  # 9 days ago
        assert rate_today > rate_old + 0.05, (
            f"today {rate_today:.2%} should exceed 9-days-old {rate_old:.2%}"
        )

    def test_strong_tie_higher_rate(self):
        weak = self._trial_share_rate(tie_count=1)   # strength ~ 0.091
        strong = self._trial_share_rate(tie_count=20)  # strength ~ 0.667
        assert strong > weak + 0.05, (
            f"strong tie {strong:.2%} should exceed weak {weak:.2%}"
        )

    def test_extraversion_lifts_rate(self):
        low = self._trial_share_rate(extra_a=0.2, extra_b=0.2)
        high = self._trial_share_rate(extra_a=0.9, extra_b=0.9)
        assert high > low + 0.05, (
            f"high extra {high:.2%} should exceed low {low:.2%}"
        )

    def test_already_known_skipped(self):
        svc, graph, agents, _ = self._setup()
        # let linda already know
        from synthetic_socio_wind_tunnel.conversation.models import Information
        svc._learn("linda", "i1", tick=15, hops=1)  # type: ignore[attr-defined]
        tr = _tick_result(20, 0, [("emma", "linda")])
        events = svc.process_tick(tr, graph, sim_day=0, agents=agents)
        # No share events since both already know
        assert all(e.info_id != "i1" or e.to_agent != "linda" for e in events)

    def test_reverse_path_does_not_update_hops(self):
        """A→B→A shouldn't change A's hops (still 0 = origin)."""
        svc, graph, agents, _ = self._setup(tie_count=20, salience=0.95)
        # Manually push share emma→linda then linda→emma encounter
        svc._learn("linda", "i1", tick=15, hops=1)  # type: ignore[attr-defined]
        # bump prop counter (cosmetic; not strictly needed)
        svc._share_count["i1"] += 1  # type: ignore[attr-defined]
        # next tick: linda→emma encounter; emma already known → no update
        tr = _tick_result(20, 0, [("emma", "linda")])
        svc.process_tick(tr, graph, sim_day=0, agents=agents)
        prop = svc.get_propagation("i1")
        assert prop.hops_at["emma"] == 0, "origin's hops must remain 0"

    def test_seed_reproducibility(self):
        rates = []
        for _ in range(2):
            svc = ConversationService(seed=42)
            graph = SocialGraphService(K=10)
            for tick in range(5):
                graph.record_encounter("emma", "linda", tick=tick)
            agents = {
                "emma": _runtime("emma", extraversion=0.7),
                "linda": _runtime("linda", extraversion=0.7),
            }
            svc.record_origin(_info(salience=0.8), "emma", tick=10)
            tr = _tick_result(20, 0, [("emma", "linda")])
            events = svc.process_tick(tr, graph, sim_day=0, agents=agents)
            rates.append(tuple((e.info_id, e.to_agent) for e in events))
        assert rates[0] == rates[1], "same seed should give same events"


class TestQueries:

    def test_count_reaching_2plus(self):
        svc = ConversationService(seed=42)
        # i1: emma origin, linda hops=1, john hops=2 → reaches 2+
        svc.record_origin(_info("i1"), "emma", tick=10)
        svc._learn("linda", "i1", tick=20, hops=1)  # type: ignore[attr-defined]
        svc._learn("john", "i1", tick=30, hops=2)  # type: ignore[attr-defined]
        # i2: emma origin only (no shares)
        svc.record_origin(_info("i2"), "emma", tick=10)

        assert svc.count_reaching(min_hops=2) == 1  # only i1
        assert svc.max_hops() == 2
        assert svc.info_count() == 2

    def test_avg_reach(self):
        svc = ConversationService(seed=42)
        svc.record_origin(_info("i1"), "emma", tick=10)
        svc._learn("linda", "i1", tick=20, hops=1)  # type: ignore[attr-defined]
        # i1 reach=2; only one info → avg=2
        assert svc.avg_reach() == 2.0

    def test_top_propagated(self):
        svc = ConversationService(seed=42)
        svc.record_origin(_info("i1"), "emma", tick=10)
        svc._learn("linda", "i1", tick=20, hops=1)  # type: ignore[attr-defined]
        svc._learn("john", "i1", tick=30, hops=2)  # type: ignore[attr-defined]
        svc.record_origin(_info("i2"), "emma", tick=10)
        top = svc.top_propagated(n=2)
        assert top[0].info_id == "i1"  # higher reach


class TestDailyCounters:

    def test_origins_on_day(self):
        svc = ConversationService(seed=42)
        svc.record_origin(_info("i1", day=0), "emma", tick=10)
        svc.record_origin(_info("i2", day=1), "emma", tick=300)
        assert svc.origins_on_day(0) == 1
        assert svc.origins_on_day(1) == 1
        assert svc.origins_on_day(99) == 0

    def test_reaching_2plus_on_day(self):
        svc = ConversationService(seed=42)
        svc.record_origin(_info("i1"), "emma", tick=10)
        # day 0 = ticks [0, 288); day 1 = [288, 576)
        svc._learn("linda", "i1", tick=20, hops=1)   # day 0  # type: ignore[attr-defined]
        svc._learn("john", "i1", tick=300, hops=2)   # day 1  # type: ignore[attr-defined]
        # i1 first reaches hops≥2 on day 1 (john at tick 300)
        assert svc.reaching_2plus_on_day(0) == 0
        assert svc.reaching_2plus_on_day(1) == 1

    def test_avg_hops_on_day(self):
        svc = ConversationService(seed=42)
        svc.record_origin(_info("i1"), "emma", tick=10)  # day 0, hops=0
        svc._learn("linda", "i1", tick=20, hops=1)        # day 0  # type: ignore[attr-defined]
        # day 0 hops: emma=0, linda=1 → avg 0.5
        assert svc.avg_hops_on_day(0) == 0.5
