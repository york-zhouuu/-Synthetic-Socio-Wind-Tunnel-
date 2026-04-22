"""Tests for policy_hack.base — Variant / PhaseController / Adapter."""

from __future__ import annotations

from datetime import date, datetime
from random import Random

import pytest

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.orchestrator import MultiDayRunner, Orchestrator
from synthetic_socio_wind_tunnel.policy_hack import (
    PhaseController,
    Variant,
    VariantContext,
    VariantRunnerAdapter,
)


# ---------- fixtures ----------

def _atlas() -> Atlas:
    region = (
        RegionBuilder("r", "r")
        .add_outdoor("a", "A", area_type="street")
        .polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        .end_outdoor()
        .build()
    )
    return Atlas(region)


def _agent(agent_id: str) -> AgentRuntime:
    profile = AgentProfile(
        agent_id=agent_id, name=agent_id, age=30, occupation="x",
        household="single", home_location="a",
    )
    return AgentRuntime(profile=profile, current_location="a")


def _orch_and_runner(agents: list[AgentRuntime]) -> tuple[Orchestrator, MultiDayRunner]:
    atlas = _atlas()
    ledger = Ledger()
    ledger.current_time = datetime(2026, 4, 22, 0, 0, 0)
    for a in agents:
        ledger.set_entity(EntityState(
            entity_id=a.profile.agent_id,
            location_id=a.current_location,
            position=Coord(x=0.0, y=0.0),
        ))
    orch = Orchestrator(atlas, ledger, agents)
    runner = MultiDayRunner(orchestrator=orch, seed=0)
    return orch, runner


# ============================================================================
# Variant ABC semantics
# ============================================================================

class TestVariantAbstract:
    def test_variant_abstract_cannot_instantiate(self):
        with pytest.raises(TypeError):
            Variant(
                name="x", hypothesis="H_info", theoretical_lineage="",
                success_criterion="", failure_criterion="",
                chain_position="algorithmic-input",
            )  # type: ignore[abstract]

    def test_concrete_subclass_without_apply_day_start_fails(self):
        # 定义子类但漏 apply_day_start
        class Bad(Variant):
            name: str = "bad"
            hypothesis: str = "H_info"  # type: ignore[assignment]
            theoretical_lineage: str = ""
            success_criterion: str = ""
            failure_criterion: str = ""
            chain_position: str = "algorithmic-input"  # type: ignore[assignment]

        with pytest.raises(TypeError):
            Bad()

    def test_metadata_dict_keys(self):
        from synthetic_socio_wind_tunnel.policy_hack import HyperlocalPushVariant
        v = HyperlocalPushVariant(target_location="cafe")
        m = v.metadata_dict()
        assert set(m.keys()) >= {
            "name", "hypothesis", "theoretical_lineage",
            "success_criterion", "failure_criterion", "chain_position",
            "is_mirror", "paired_variant",
        }


# ============================================================================
# PhaseController
# ============================================================================

class TestPhaseController:
    def test_default_14_day_boundaries(self):
        pc = PhaseController()  # 4/6/4
        assert pc.phase(0) == "baseline"
        assert pc.phase(3) == "baseline"
        assert pc.phase(4) == "intervention"
        assert pc.phase(9) == "intervention"
        assert pc.phase(10) == "post"
        assert pc.phase(13) == "post"

    def test_is_active_only_intervention(self):
        pc = PhaseController()
        active_days = [d for d in range(14) if pc.is_active(d)]
        assert active_days == [4, 5, 6, 7, 8, 9]

    def test_first_day_flags(self):
        pc = PhaseController()
        assert pc.is_first_intervention_day(4) is True
        assert pc.is_first_intervention_day(5) is False
        assert pc.is_first_post_day(10) is True
        assert pc.is_first_post_day(11) is False

    def test_custom_1_1_1(self):
        pc = PhaseController(baseline_days=1, intervention_days=1, post_days=1)
        assert pc.phase(0) == "baseline"
        assert pc.phase(1) == "intervention"
        assert pc.phase(2) == "post"

    def test_total_days(self):
        pc = PhaseController(baseline_days=2, intervention_days=5, post_days=3)
        assert pc.total_days == 10


# ============================================================================
# VariantRunnerAdapter
# ============================================================================

class TestVariantRunnerAdapter:
    def _mk_recording_variant(self):
        """一个会记录 hook 调用的 Variant。"""
        from synthetic_socio_wind_tunnel.policy_hack import Variant as V

        class RecorderVariant(V):
            name: str = "recorder"
            hypothesis: str = "H_info"  # type: ignore[assignment]
            theoretical_lineage: str = "test"
            success_criterion: str = "test"
            failure_criterion: str = "test"
            chain_position: str = "algorithmic-input"  # type: ignore[assignment]

            def apply_intervention_start(self, ctx):
                self._calls.append(("intervention_start", ctx.day_index))

            def apply_day_start(self, ctx):
                self._calls.append(("day_start", ctx.day_index))

            def apply_intervention_end(self, ctx):
                self._calls.append(("intervention_end", ctx.day_index))

        RecorderVariant.model_config = dict(RecorderVariant.model_config)
        # 给实例一个 mutable calls log
        v = RecorderVariant()
        object.__setattr__(v, "_calls", [])  # bypass frozen
        return v

    def test_baseline_no_variant_calls(self):
        v = self._mk_recording_variant()
        pc = PhaseController(baseline_days=2, intervention_days=0, post_days=0)
        agents = [_agent("a1")]
        _orch, runner = _orch_and_runner(agents)
        adapter = VariantRunnerAdapter(v, pc, seed=0)
        adapter.attach_to(runner)

        # Manually call on_day_start for baseline
        adapter.on_day_start(date(2026, 4, 22), 0)
        adapter.on_day_start(date(2026, 4, 23), 1)

        assert v._calls == []  # no hooks fired in baseline

    def test_intervention_triggers_day_start(self):
        v = self._mk_recording_variant()
        pc = PhaseController(baseline_days=1, intervention_days=2, post_days=1)
        agents = [_agent("a1")]
        _orch, runner = _orch_and_runner(agents)
        adapter = VariantRunnerAdapter(v, pc, seed=0)
        adapter.attach_to(runner)

        adapter.on_day_start(date(2026, 4, 22), 0)  # baseline
        adapter.on_day_start(date(2026, 4, 23), 1)  # intervention start
        adapter.on_day_start(date(2026, 4, 24), 2)  # intervention mid
        adapter.on_day_start(date(2026, 4, 25), 3)  # post start

        events = [e for e in v._calls]
        assert ("intervention_start", 1) in events
        assert ("day_start", 1) in events
        assert ("day_start", 2) in events
        assert ("intervention_end", 3) in events
        # baseline day 0 should not trigger anything
        assert all(e[1] != 0 for e in events)

    def test_attach_twice_raises(self):
        v = self._mk_recording_variant()
        pc = PhaseController()
        agents = [_agent("a1")]
        _orch, runner = _orch_and_runner(agents)
        adapter = VariantRunnerAdapter(v, pc, seed=0)
        adapter.attach_to(runner)
        with pytest.raises(RuntimeError):
            adapter.attach_to(runner)

    def test_on_day_start_before_attach_raises(self):
        v = self._mk_recording_variant()
        pc = PhaseController()
        adapter = VariantRunnerAdapter(v, pc, seed=0)
        with pytest.raises(RuntimeError):
            adapter.on_day_start(date(2026, 4, 22), 0)

    def test_setup_run_calls_apply_population(self):
        from synthetic_socio_wind_tunnel.policy_hack import CatalystSeedingVariant
        v = CatalystSeedingVariant(catalyst_ratio=0.5)
        pc = PhaseController()
        adapter = VariantRunnerAdapter(v, pc, seed=0)

        profiles = [
            AgentProfile(agent_id=f"a{i}", name=f"a{i}", age=30,
                         occupation="x", household="single", home_location="a")
            for i in range(4)
        ]
        new_profiles = adapter.setup_run(profiles, Random(0))
        # 50% = 2 agents 被 catalyst 化
        catalyst_count = sum(
            1 for p in new_profiles
            if p.personality.extraversion == v.catalyst_personality.extraversion
        )
        assert catalyst_count == 2
