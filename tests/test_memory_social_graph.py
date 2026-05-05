"""Tests for MemoryService ↔ SocialGraphService integration."""

from __future__ import annotations

from datetime import datetime

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
from synthetic_socio_wind_tunnel.memory.service import MemoryService
from synthetic_socio_wind_tunnel.orchestrator.models import EncounterCandidate, TickResult
from synthetic_socio_wind_tunnel.social_graph import SocialGraphService


def _profile(agent_id: str) -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id, name=agent_id.title(), age=30, occupation="x",
        household="single", home_location="home",
        personality=PersonalityTraits(),
    )


def _tick_result(*, tick: int, day: int, encounters: list[tuple[str, str, str]]) -> TickResult:
    return TickResult(
        tick_index=tick,
        day_index=day,
        simulated_time=datetime(2026, 5, 5, 8, 0),
        commits=(),
        encounter_candidates=tuple(
            EncounterCandidate(agent_a=a, agent_b=b, shared_locations=(loc,), tick=tick)
            for a, b, loc in encounters
        ),
    )


class TestEncounterAccumulation:

    def test_encounter_synced_to_graph_when_injected(self):
        graph = SocialGraphService(K=10)
        memory = MemoryService(social_graph=graph)
        agents = {
            "emma": AgentRuntime(profile=_profile("emma"), current_location="home"),
            "linda": AgentRuntime(profile=_profile("linda"), current_location="home"),
        }
        tr = _tick_result(tick=10, day=0,
                          encounters=[("emma", "linda", "cafe_main")])
        memory.process_tick(tr, agents, planner=None)

        tie = graph.get_tie("emma", "linda")
        assert tie is not None
        assert tie.encounter_count == 1
        assert tie.first_seen_tick == 10
        assert tie.first_seen_day == 0

    def test_no_graph_injection_no_record(self):
        """Old behavior preserved when social_graph=None."""
        memory = MemoryService(social_graph=None)
        agents = {
            "emma": AgentRuntime(profile=_profile("emma"), current_location="home"),
            "linda": AgentRuntime(profile=_profile("linda"), current_location="home"),
        }
        tr = _tick_result(tick=10, day=0,
                          encounters=[("emma", "linda", "cafe_main")])
        # should not raise, encounter MemoryEvents still written
        memory.process_tick(tr, agents, planner=None)
        assert any(
            e.kind == "encounter" for e in memory.all_for("emma")
        )

    def test_repeat_encounters_accumulate(self):
        graph = SocialGraphService(K=10)
        memory = MemoryService(social_graph=graph)
        agents = {
            "emma": AgentRuntime(profile=_profile("emma"), current_location="home"),
            "linda": AgentRuntime(profile=_profile("linda"), current_location="home"),
        }
        for tick in (10, 20, 30):
            tr = _tick_result(tick=tick, day=tick // 288,
                              encounters=[("emma", "linda", "park_a")])
            memory.process_tick(tr, agents, planner=None)
        tie = graph.get_tie("emma", "linda")
        assert tie.encounter_count == 3
        assert tie.first_seen_tick == 10
        assert tie.last_seen_tick == 30

    def test_same_tick_encounter_idempotent_in_graph(self):
        graph = SocialGraphService(K=10)
        memory = MemoryService(social_graph=graph)
        agents = {
            "emma": AgentRuntime(profile=_profile("emma"), current_location="home"),
            "linda": AgentRuntime(profile=_profile("linda"), current_location="home"),
        }
        # call process_tick twice with same tick (orchestrator quirk simulation)
        tr = _tick_result(tick=10, day=0,
                          encounters=[("emma", "linda", "cafe_main")])
        memory.process_tick(tr, agents, planner=None)
        memory.process_tick(tr, agents, planner=None)
        tie = graph.get_tie("emma", "linda")
        # graph's same-tick idempotency keeps encounter_count at 1
        assert tie.encounter_count == 1


class TestNearbyAgentsFamiliarSource:

    def test_familiar_via_graph_when_injected(self):
        graph = SocialGraphService(K=10)
        # Pre-populate emma <-> linda with 5 encounters (strength 0.333 > 0.1)
        for tick in range(5):
            graph.record_encounter("emma", "linda", tick=tick)
        memory = MemoryService(social_graph=graph)
        agents = {
            "emma": AgentRuntime(profile=_profile("emma"), current_location="home"),
            "linda": AgentRuntime(profile=_profile("linda"), current_location="home"),
            "john": AgentRuntime(profile=_profile("john"), current_location="home"),
        }
        # Test: build nearby_agents for emma in a tick where she sees linda + john
        tr = _tick_result(tick=100, day=0,
                          encounters=[("emma", "linda", "cafe"),
                                      ("emma", "john", "cafe")])
        nearby = memory._nearby_agents_for("emma", tr, agents["emma"])
        familiar_states = sorted(n.is_familiar for n in nearby)
        # linda: True (strength 0.333 > 0.1); john: False (no prior tie)
        assert familiar_states == [False, True]

    def test_familiar_via_memory_fallback(self):
        """social_graph=None falls back to memory-based familiar judgement."""
        memory = MemoryService(social_graph=None)
        agents = {
            "emma": AgentRuntime(profile=_profile("emma"), current_location="home"),
            "linda": AgentRuntime(profile=_profile("linda"), current_location="home"),
        }
        # Seed emma's memory with a prior encounter with linda
        prior = _tick_result(tick=50, day=0, encounters=[("emma", "linda", "park")])
        memory.process_tick(prior, agents, planner=None)
        # Now build nearby_agents for emma seeing linda again
        tr = _tick_result(tick=100, day=0,
                          encounters=[("emma", "linda", "cafe")])
        nearby = memory._nearby_agents_for("emma", tr, agents["emma"])
        # Memory has linda as actor_id → familiar=True (legacy behavior)
        assert len(nearby) == 1
        assert nearby[0].is_familiar is True
