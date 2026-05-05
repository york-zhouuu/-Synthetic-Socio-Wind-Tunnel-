"""End-to-end goldilocks band + heterogeneity tests
（realism-attention-rebalance）。

不跑完整 sim（成本高），用 sample_population 抽 100 个 Lane Cove agent，
对每个 agent 跑相同 hyperlocal_push 候选 × 多个 rng seed，统计触发率分布
是否符合 spec 的两个约束：

1. 平均 replan 触发率 ∈ [5%, 15%]（goldilocks band）
2. 100 agent 触发率分布出现至少 3 个聚类（heterogeneity）
"""

from __future__ import annotations

import random
from datetime import datetime
from statistics import median

import pytest

from synthetic_socio_wind_tunnel.agent import (
    LANE_COVE_PROFILE, AgentRuntime, sample_population,
)
from synthetic_socio_wind_tunnel.memory.models import MemoryEvent


_DESTS = tuple(f"loc_{i}" for i in range(20))


def _hyperlocal_push() -> MemoryEvent:
    """典型 hyperlocal push：urgency=0.6（policy_hack/variant_a 默认值）。"""
    return MemoryEvent(
        event_id="ev1", agent_id="-", tick=10,
        simulated_time=datetime(2026, 4, 29, 8, 0),
        kind="notification",
        content="本街正在举办市集，你愿意来看看吗？",
        urgency=0.6,
        importance=0.5,
    )


def _agent_trigger_rate(
    rt: AgentRuntime, candidate: MemoryEvent, *,
    trials: int = 100, base_seed: int = 0,
) -> float:
    """单 agent 跑 N 次 should_replan，返回触发率。"""
    n_true = 0
    for i in range(trials):
        rng = random.Random(base_seed + i)
        if rt.should_replan([], candidate, rng=rng):
            n_true += 1
    return n_true / trials


@pytest.fixture(scope="module")
def lanecove_population_rates() -> list[float]:
    """采样 100 个 Lane Cove agent，每人跑 100 次 should_replan，返回触发率列表。"""
    template = LANE_COVE_PROFILE.model_copy(update={"size": 100})
    profiles = sample_population(template, seed=42, home_locations=_DESTS)
    candidate = _hyperlocal_push()
    rates: list[float] = []
    for i, p in enumerate(profiles):
        rt = AgentRuntime(profile=p, current_location=p.home_location)
        rates.append(_agent_trigger_rate(rt, candidate, trials=100, base_seed=i * 100))
    return rates


# ---------------------------------------------------------------------------
# Goldilocks band：平均触发率 ∈ [5%, 15%]
# ---------------------------------------------------------------------------


class TestGoldilocksBand:

    def test_average_rate_in_band(self, lanecove_population_rates):
        avg = sum(lanecove_population_rates) / len(lanecove_population_rates)
        assert 0.05 <= avg <= 0.15, (
            f"Lane Cove 100 agent 平均触发率 {avg:.2%} 落出 goldilocks band [5%, 15%]"
        )

    def test_median_rate_in_band(self, lanecove_population_rates):
        med = median(lanecove_population_rates)
        # 中位数允许稍宽 [3%, 18%]，因为分布右偏（少数高 cur 高 openness 拉高均值）
        assert 0.03 <= med <= 0.18, (
            f"Lane Cove 100 agent 触发率中位数 {med:.2%} 异常"
        )


# ---------------------------------------------------------------------------
# Heterogeneity：分布至少 3 个 mode
# ---------------------------------------------------------------------------


class TestHeterogeneity:

    def test_distribution_not_unimodal(self, lanecove_population_rates):
        """同一条 push 给 100 个 personality 不同 agent 应产生分布性反应。"""
        # 简化的多峰检测：把 [0, 1] 划成 5 个 bin，至少 3 个 bin 有 ≥5 agents
        bins = [0, 0, 0, 0, 0]  # [0, 0.1), [0.1, 0.2), [0.2, 0.4), [0.4, 0.6), [0.6, 1.0]
        thresholds = [0.10, 0.20, 0.40, 0.60, 1.01]
        for r in lanecove_population_rates:
            for i, t in enumerate(thresholds):
                if r < t:
                    bins[i] += 1
                    break
        active_bins = sum(1 for b in bins if b >= 5)
        assert active_bins >= 3, (
            f"分布过窄：5 个 bin 中只有 {active_bins} 个 ≥5 agents（应 ≥ 3）。"
            f"bin counts: {bins}"
        )

    def test_low_responders_exist(self, lanecove_population_rates):
        """高 routine_adherence 农 agent 应有显著比例触发率 < 5%。"""
        low_count = sum(1 for r in lanecove_population_rates if r < 0.05)
        assert low_count >= 10, (
            f"低响应者太少：{low_count}/100（应 ≥ 10）"
        )

    def test_high_responders_exist(self, lanecove_population_rates):
        """高 curiosity / openness 的 agent 应有显著比例触发率 > 20%。"""
        high_count = sum(1 for r in lanecove_population_rates if r > 0.20)
        assert high_count >= 5, (
            f"高响应者太少：{high_count}/100（应 ≥ 5）"
        )


# ---------------------------------------------------------------------------
# Personality 簇：低 / 中 / 高 routine_adherence 的触发率排序
# ---------------------------------------------------------------------------


class TestPersonalityClustering:

    def test_low_adherence_higher_than_high_adherence(self):
        """低 adherence 簇的平均触发率 SHALL 显著高于高 adherence 簇。"""
        template = LANE_COVE_PROFILE.model_copy(update={"size": 100})
        profiles = sample_population(template, seed=42, home_locations=_DESTS)
        candidate = _hyperlocal_push()

        low_rates = []
        high_rates = []
        for i, p in enumerate(profiles):
            rt = AgentRuntime(profile=p, current_location=p.home_location)
            r = _agent_trigger_rate(rt, candidate, trials=100, base_seed=i * 100)
            if p.personality.routine_adherence < 0.4:
                low_rates.append(r)
            elif p.personality.routine_adherence > 0.7:
                high_rates.append(r)

        if not (low_rates and high_rates):
            pytest.skip("Lane Cove sample 中没有同时覆盖两端的 agent")

        low_avg = sum(low_rates) / len(low_rates)
        high_avg = sum(high_rates) / len(high_rates)
        assert low_avg > high_avg + 0.05, (
            f"低 adherence 簇均值 {low_avg:.2%} 应明显高于高 adherence 簇 "
            f"{high_avg:.2%}"
        )
