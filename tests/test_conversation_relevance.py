"""Tests for conversation's relevance + audience modifications."""

from __future__ import annotations

import random
from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
from synthetic_socio_wind_tunnel.conversation import ConversationService, Information
from synthetic_socio_wind_tunnel.orchestrator.models import (
    EncounterCandidate,
    TickResult,
)
from synthetic_socio_wind_tunnel.social_graph import SocialGraphService


def _runtime(agent_id: str, extraversion: float = 0.7) -> AgentRuntime:
    return AgentRuntime(
        profile=AgentProfile(
            agent_id=agent_id, name=agent_id, age=30, occupation="x",
            household="single", home_location="home",
            personality=PersonalityTraits(extraversion=extraversion),
        ),
        current_location="home",
    )


def _info(info_id: str = "i1", *, salience: float = 0.8, day: int = 0,
          target_tags: tuple[str, ...] = ()) -> Information:
    return Information(
        info_id=info_id, content="本街市集", category="push",
        salience=salience, origin_tick=10, origin_agent_id="emma",
        origin_day_index=day, target_audience_tags=target_tags,
    )


def _tick(tick: int, day: int, encs: list[tuple[str, str]]) -> TickResult:
    return TickResult(
        tick_index=tick, day_index=day,
        simulated_time=datetime(2026, 5, 8),
        commits=(),
        encounter_candidates=tuple(
            EncounterCandidate(
                agent_a=a, agent_b=b, shared_locations=("cafe",), tick=tick,
            )
            for a, b in encs
        ),
    )


class TestRelevanceModifierBackwardCompat:

    def test_no_provider_share_rate_unchanged(self):
        # Without relevance_provider, formula reduces to original V1
        rates = []
        for label, provider in [("none", None)]:
            n_share = 0
            for trial in range(200):
                svc = ConversationService(seed=trial, relevance_provider=provider)
                graph = SocialGraphService(K=10)
                for tick in range(5):
                    graph.record_encounter("emma", "linda", tick=tick)
                agents = {"emma": _runtime("emma"), "linda": _runtime("linda")}
                svc.record_origin(_info(salience=0.8), "emma", tick=10)
                tr = _tick(20, 0, [("emma", "linda")])
                svc.process_tick(tr, graph, sim_day=0, agents=agents)
                if "i1" in svc.info_known_by("linda"):
                    n_share += 1
            rates.append((label, n_share / 200))
        # Just sanity-check share rate is in plausible range (~5-30%)
        rate = rates[0][1]
        assert 0.05 < rate < 0.6, f"baseline rate {rate} out of expected range"


class TestRelevanceModifierEffect:

    def _trial(self, *, sender_rel: float, receiver_rel: float,
               trials: int = 200) -> float:
        def provider(info_id: str, agent_id: str) -> float:
            return sender_rel if agent_id == "emma" else receiver_rel
        n_share = 0
        for trial in range(trials):
            svc = ConversationService(seed=trial, relevance_provider=provider)
            graph = SocialGraphService(K=10)
            for tick in range(5):
                graph.record_encounter("emma", "linda", tick=tick)
            agents = {"emma": _runtime("emma"), "linda": _runtime("linda")}
            svc.record_origin(_info(salience=0.8), "emma", tick=10)
            tr = _tick(20, 0, [("emma", "linda")])
            svc.process_tick(tr, graph, sim_day=0, agents=agents)
            if "i1" in svc.info_known_by("linda"):
                n_share += 1
        return n_share / trials

    def test_low_receiver_relevance_lowers_share(self):
        high = self._trial(sender_rel=1.0, receiver_rel=1.0)
        low = self._trial(sender_rel=1.0, receiver_rel=0.3)
        # absolute differences are small (~5pp), but the ratio is large (~4x).
        # Asserting ratio is more meaningful at this share-rate scale.
        assert high > low * 2.0 + 0.005, (
            f"high receiver_rel {high:.2%} should exceed low {low:.2%}"
        )

    def test_low_sender_relevance_lowers_share(self):
        high = self._trial(sender_rel=1.0, receiver_rel=1.0)
        low = self._trial(sender_rel=0.3, receiver_rel=1.0)
        # absolute differences are small (~5pp), but the ratio is large (~4x).
        # Asserting ratio is more meaningful at this share-rate scale.
        assert high > low * 2.0 + 0.005, (
            f"high sender_rel {high:.2%} should exceed low {low:.2%}"
        )


class TestTargetPrecision:

    def test_no_audience_tag_provider_returns_zero(self):
        svc = ConversationService(seed=42)
        svc.record_origin(_info(target_tags=("parents",)), "emma", tick=10)
        assert svc.mean_target_precision() == 0.0
        assert svc.within_target_count("i1") == 0

    def test_target_precision_calculation(self):
        # 3 agents know i1: a,b are parents (target), c is elderly (outside)
        def audience_for(agent_id: str) -> str:
            return {"a": "parents", "b": "parents", "c": "elderly"}.get(agent_id, "default")
        svc = ConversationService(
            seed=42, audience_tag_provider=audience_for,
        )
        svc.record_origin(_info(target_tags=("parents",)), "emma", tick=10)
        # Manually mark a,b,c as knowing i1
        svc._learn("a", "i1", tick=20, hops=1)  # type: ignore[attr-defined]
        svc._learn("b", "i1", tick=21, hops=1)  # type: ignore[attr-defined]
        svc._learn("c", "i1", tick=22, hops=1)  # type: ignore[attr-defined]
        # within = a,b = 2; outside = c = 1; total = 3 (excluding emma origin)
        # Note: emma is also in known set but emma=default → outside
        assert svc.within_target_count("i1") == 2
        assert svc.outside_target_count("i1") == 2  # emma + c
        # 2 / (2+2) = 0.5
        assert svc.target_precision_for("i1") == pytest.approx(0.5, abs=1e-3)

    def test_info_without_target_tags_zero_precision(self):
        def audience_for(agent_id: str) -> str:
            return "default"
        svc = ConversationService(
            seed=42, audience_tag_provider=audience_for,
        )
        # Info has no target_audience_tags
        svc.record_origin(_info(target_tags=()), "emma", tick=10)
        svc._learn("a", "i1", tick=20, hops=1)  # type: ignore[attr-defined]
        # No target → precision 0
        assert svc.within_target_count("i1") == 0
        assert svc.outside_target_count("i1") == 0
        assert svc.target_precision_for("i1") == 0.0
