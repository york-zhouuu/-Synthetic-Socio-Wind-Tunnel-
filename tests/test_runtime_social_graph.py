"""Tests for AgentRuntime.familiar_with (social-graph-capability)."""

from __future__ import annotations

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
from synthetic_socio_wind_tunnel.social_graph import SocialGraphService


def _profile(agent_id: str) -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id, name=agent_id.title(), age=30, occupation="x",
        household="single", home_location="home",
        personality=PersonalityTraits(),
    )


class TestFamiliarWith:

    def test_no_social_graph_returns_false(self):
        """Without social_graph injection, familiar_with always False."""
        rt = AgentRuntime(profile=_profile("emma"), current_location="home")
        assert rt.familiar_with("linda") is False
        assert rt.familiar_with("anyone") is False

    def test_no_tie_returns_false(self):
        graph = SocialGraphService(K=10)
        rt = AgentRuntime(
            profile=_profile("emma"), current_location="home", social_graph=graph,
        )
        assert rt.familiar_with("linda") is False  # never met

    def test_strong_tie_above_threshold(self):
        graph = SocialGraphService(K=10)
        # emma <-> linda: 5 encounters → strength 0.333 > 0.1
        for tick in range(5):
            graph.record_encounter("emma", "linda", tick=tick)
        rt = AgentRuntime(
            profile=_profile("emma"), current_location="home", social_graph=graph,
        )
        assert rt.familiar_with("linda") is True

    def test_weak_tie_below_default_threshold(self):
        graph = SocialGraphService(K=10)
        # 1 encounter → strength 0.091 < 0.1 default threshold
        graph.record_encounter("emma", "john", tick=0)
        rt = AgentRuntime(
            profile=_profile("emma"), current_location="home", social_graph=graph,
        )
        assert rt.familiar_with("john") is False

    def test_custom_threshold_changes_result(self):
        graph = SocialGraphService(K=10)
        # 2 encounters → strength 0.167
        for tick in range(2):
            graph.record_encounter("emma", "linda", tick=tick)
        rt = AgentRuntime(
            profile=_profile("emma"), current_location="home", social_graph=graph,
        )
        assert rt.familiar_with("linda", threshold=0.1) is True
        assert rt.familiar_with("linda", threshold=0.2) is False

    def test_no_llm_call(self):
        """familiar_with MUST NOT trigger any LLM."""
        graph = SocialGraphService(K=10)
        rt = AgentRuntime(
            profile=_profile("emma"), current_location="home", social_graph=graph,
        )
        import time
        t0 = time.perf_counter()
        for i in range(10000):
            rt.familiar_with(f"agent_{i % 10}")
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.5, f"10k calls took {elapsed:.2f}s — too slow"
