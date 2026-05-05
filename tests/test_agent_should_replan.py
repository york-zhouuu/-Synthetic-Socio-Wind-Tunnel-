"""Tests for AgentRuntime.should_replan rule-based logic (no LLM).

Post realism-attention-rebalance：should_replan 不再是硬阈值，
而是 6 维 personality + context modifier + 概率门。本文件断言
概率分布的方向性（高 curiosity > 高 routine_adherence 等），
而不是单次确定性结果。
"""

from __future__ import annotations

import random
from datetime import datetime

from synthetic_socio_wind_tunnel.agent import AgentProfile, AgentRuntime
from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
from synthetic_socio_wind_tunnel.memory.models import MemoryEvent


def _profile(
    curiosity: float = 0.5,
    routine_adherence: float = 0.5,
    openness: float = 0.5,
    conscientiousness: float = 0.5,
    risk_tolerance: float = 0.5,
    extraversion: float = 0.5,
) -> AgentProfile:
    return AgentProfile(
        agent_id="emma", name="Emma", age=30, occupation="x",
        household="single", home_location="home",
        personality=PersonalityTraits(
            curiosity=curiosity, routine_adherence=routine_adherence,
            openness=openness, conscientiousness=conscientiousness,
            risk_tolerance=risk_tolerance, extraversion=extraversion,
        ),
    )


def _notification(urgency: float = 0.5, kind: str = "notification") -> MemoryEvent:
    return MemoryEvent(
        event_id="n1", agent_id="emma", tick=0,
        simulated_time=datetime(2026, 4, 21, 7, 0),
        kind=kind,  # type: ignore
        content="push!", urgency=urgency, importance=0.7,
    )


def _trigger_rate(runtime: AgentRuntime, candidate: MemoryEvent, *,
                  trials: int = 1000, base_seed: int = 0) -> float:
    """跑 N 次 should_replan，返回触发率。"""
    n_true = 0
    for i in range(trials):
        rng = random.Random(base_seed + i)
        if runtime.should_replan([], candidate, rng=rng):
            n_true += 1
    return n_true / trials


class TestPersonalityDirection:
    """6 维 personality 各自对触发率的方向性影响。"""

    # 用 urgency=0.6（hyperlocal_push 的典型值），各 personality
    # 的方向性差异更可见。中性 personality + 0.6 ~ 12% 触发率（goldilocks band）。

    def test_high_curiosity_lifts_rate(self):
        low = AgentRuntime(profile=_profile(curiosity=0.1))
        high = AgentRuntime(profile=_profile(curiosity=0.9))
        cand = _notification(urgency=0.6)
        rate_low = _trigger_rate(low, cand)
        rate_high = _trigger_rate(high, cand)
        assert rate_high > rate_low + 0.10, (
            f"curiosity 应抬升触发率：low={rate_low:.2%} high={rate_high:.2%}"
        )

    def test_high_adherence_lowers_rate(self):
        low = AgentRuntime(profile=_profile(routine_adherence=0.1))
        high = AgentRuntime(profile=_profile(routine_adherence=0.9))
        cand = _notification(urgency=0.6)
        rate_low = _trigger_rate(low, cand)
        rate_high = _trigger_rate(high, cand)
        assert rate_high < rate_low - 0.10, (
            f"routine_adherence 应压低触发率："
            f"low={rate_low:.2%} high={rate_high:.2%}"
        )

    def test_high_openness_lifts_rate(self):
        low = AgentRuntime(profile=_profile(openness=0.1))
        high = AgentRuntime(profile=_profile(openness=0.9))
        cand = _notification(urgency=0.6)
        rate_low = _trigger_rate(low, cand)
        rate_high = _trigger_rate(high, cand)
        assert rate_high > rate_low + 0.03, (
            f"openness 应抬升触发率：low={rate_low:.2%} high={rate_high:.2%}"
        )

    def test_extreme_urgency_lifts_rate(self):
        """极高 urgency 显著高于普通 urgency（即使是中性 personality）。"""
        rt = AgentRuntime(profile=_profile())
        rate_normal = _trigger_rate(rt, _notification(urgency=0.5))
        rate_extreme = _trigger_rate(rt, _notification(urgency=0.95))
        assert rate_extreme > rate_normal + 0.20, (
            f"urgency=0.95 应显著高于 0.5："
            f"normal={rate_normal:.2%} extreme={rate_extreme:.2%}"
        )

    def test_low_urgency_mostly_ignored(self):
        """很低 urgency 大概率不触发。"""
        rt = AgentRuntime(profile=_profile())
        cand = _notification(urgency=0.05)
        rate = _trigger_rate(rt, cand)
        assert rate < 0.10, f"urgency=0.05 应几乎被忽略：rate={rate:.2%}"


class TestProbabilisticGate:
    """概率门：典型 urgency 同 personality 不应"全 0 或全 1"。"""

    def test_typical_urgency_not_all_or_nothing(self):
        # 典型 hp push urgency=0.6，中性 personality → goldilocks 区间
        rt = AgentRuntime(profile=_profile())
        cand = _notification(urgency=0.6)
        rate = _trigger_rate(rt, cand, trials=1000)
        assert 0.05 < rate < 0.30, (
            f"中性 personality + urgency=0.6 应落入 [5%, 30%]（goldilocks）："
            f"rate={rate:.2%}"
        )


class TestContextModifier:
    """已投入活动的 agent 阈值升高。"""

    def test_engaged_agent_resists_more(self):
        from synthetic_socio_wind_tunnel.agent.planner import PlanStep
        rt = AgentRuntime(profile=_profile())
        # 用 urgency=0.6 让 baseline 触发率落在 goldilocks 中段（约 12%），
        # 这样 -0.15 阈值 modifier 的下降量可以观察到（变成约 0%）
        cand = _notification(urgency=0.6)
        step = PlanStep(time="08:00", action="stay", duration_minutes=30)

        rate_no_step = _trigger_rate(rt, cand)
        rate_just_started = sum(
            1 for i in range(1000)
            if rt.should_replan(
                [], cand, current_step=step, current_step_elapsed_min=2.0,
                rng=random.Random(i),
            )
        ) / 1000
        rate_engaged = sum(
            1 for i in range(1000)
            if rt.should_replan(
                [], cand, current_step=step, current_step_elapsed_min=15.0,
                rng=random.Random(i),
            )
        ) / 1000

        assert rate_engaged < rate_just_started - 0.03, (
            f"engaged={rate_engaged:.2%} 应低于 just_started={rate_just_started:.2%}"
        )
        assert abs(rate_just_started - rate_no_step) < 0.05


class TestFatigueDecay:
    """同一 agent 当日 replan 次数累加 → 阈值升高。"""

    def test_more_replans_lowers_rate(self):
        rt = AgentRuntime(profile=_profile())
        cand = _notification(urgency=0.6)
        rate_fresh = sum(
            1 for i in range(1000)
            if rt.should_replan(
                [], cand, replan_count_today=0, rng=random.Random(i),
            )
        ) / 1000
        rate_tired = sum(
            1 for i in range(1000)
            if rt.should_replan(
                [], cand, replan_count_today=4, rng=random.Random(i),
            )
        ) / 1000
        assert rate_tired < rate_fresh - 0.05, (
            f"replan_count=4 应显著低于 0：fresh={rate_fresh:.2%} "
            f"tired={rate_tired:.2%}"
        )


class TestTaskReceived:

    def test_task_received_uses_same_logic(self):
        rt = AgentRuntime(profile=_profile(curiosity=0.9, routine_adherence=0.1))
        cand = _notification(urgency=0.6, kind="task_received")
        rate = _trigger_rate(rt, cand)
        # 高 cur+低 adh 在 urg=0.6 下应明显高于 goldilocks 中心（~12%）
        assert rate > 0.20, f"task_received 高 curiosity 应高触发率：rate={rate:.2%}"


class TestOtherKindsDefaultFalse:
    """非 notification kind 永远不触发，无视 personality / urgency。"""

    def test_encounter_not_replan(self):
        rt = AgentRuntime(profile=_profile(curiosity=0.9))
        cand = MemoryEvent(
            event_id="e1", agent_id="emma", tick=0,
            simulated_time=datetime.now(),
            kind="encounter", content="met linda",
            actor_id="linda", urgency=0.8,
        )
        assert rt.should_replan([], cand, rng=random.Random(0)) is False

    def test_action_not_replan(self):
        rt = AgentRuntime(profile=_profile())
        cand = MemoryEvent(
            event_id="a1", agent_id="emma", tick=0,
            simulated_time=datetime.now(),
            kind="action", content="moved",
        )
        assert rt.should_replan([], cand, rng=random.Random(0)) is False


class TestDecisionLog:

    def test_log_off_by_default(self):
        rt = AgentRuntime(profile=_profile())
        cand = _notification(urgency=0.6)
        for _ in range(5):
            rt.should_replan([], cand, rng=random.Random(0))
        assert rt.replan_decision_log == []

    def test_log_records_each_call(self):
        rt = AgentRuntime(profile=_profile())
        rt.enable_replan_log = True
        cand = _notification(urgency=0.6)
        for i in range(5):
            rt.should_replan([], cand, rng=random.Random(i))
        assert len(rt.replan_decision_log) == 5
        for record in rt.replan_decision_log:
            assert record.candidate_kind == "notification"
            assert record.candidate_urgency == 0.6
            assert "routine_adherence" in record.base_components
            assert "extraversion" in record.base_components
            assert isinstance(record.decision, bool)


class TestNoLLMCall:

    def test_no_llm_in_should_replan(self):
        """should_replan 绝不能调 LLM。"""
        rt = AgentRuntime(profile=_profile())
        cand = _notification(urgency=0.9)
        import time
        start = time.perf_counter()
        for i in range(10000):
            rt.should_replan([], cand, rng=random.Random(i))
        elapsed = time.perf_counter() - start
        assert elapsed < 1.5, (
            f"should_replan 10k calls took {elapsed:.2f}s (expected < 1.5s)"
        )


class TestBackwardCompat:

    def test_legacy_call_signature_works(self):
        """老 caller 用 should_replan(memory_view, candidate) 不传 kw 也不能崩。"""
        rt = AgentRuntime(profile=_profile())
        cand = _notification(urgency=0.6)
        # 不传 rng / current_step / replan_count_today，全部 default
        result = rt.should_replan([], cand)
        assert result in (True, False)  # 不抛异常即可
