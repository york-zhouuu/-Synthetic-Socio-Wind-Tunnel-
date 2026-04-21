"""
Population 采样 - 按社区画像生成 AgentProfile 列表

PopulationProfile 声明结构性维度的边缘分布与人群尺寸，
sample_population 按种子采样出 N 个 AgentProfile。

对 thesis 的价值：1000 agent 的联合分布不应由手工 fixture 决定，
而应从一个可验证的画像采样；fitness-audit 能检查分布覆盖。

重要：本模块不引入人口统计学"价值判断"，仅采样可观察事实字段。
LLM（Planner）负责基于这些字段的主观解读。

注意：
- LANE_COVE_PROFILE 的分布数值是 **未经验证的占位**（作者按 Lane Cove 2066
  一般印象粗设），不等同于真实 ABS census。后续 change SHALL 用 ABS 2021
  census + Lane Cove council 数据做一次性替换，并在 git history 中保留此
  对齐点。fitness-audit 的 `phase1-baseline.profile-preset-ground-truthed`
  条目追踪这一缺口。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from synthetic_socio_wind_tunnel.agent.personality import PersonalityTraits
from synthetic_socio_wind_tunnel.agent.profile import (
    AgentProfile,
    Household,
    HousingTenure,
    IncomeTier,
    WorkMode,
)
from synthetic_socio_wind_tunnel.attention.models import DigitalProfile, FeedBias


_WEIGHT_EPS = 1e-6


@dataclass(frozen=True)
class PersonalityParams:
    """
    PersonalityTraits 采样参数（typed-personality change）。

    每维度一对 (mean, std)。std=0 时全常数；默认 (0.5, 0.2) 在 1000 样本
    下给 ~0.2 的标准差，保证 thesis 层面的异质性。
    """

    openness: tuple[float, float] = (0.5, 0.2)
    conscientiousness: tuple[float, float] = (0.5, 0.2)
    extraversion: tuple[float, float] = (0.5, 0.2)
    agreeableness: tuple[float, float] = (0.5, 0.2)
    neuroticism: tuple[float, float] = (0.5, 0.2)
    curiosity: tuple[float, float] = (0.5, 0.2)
    routine_adherence: tuple[float, float] = (0.5, 0.2)
    risk_tolerance: tuple[float, float] = (0.5, 0.2)


@dataclass(frozen=True)
class DigitalParams:
    """DigitalProfile 生成参数。"""

    screen_hours_mean: float = 3.5
    screen_hours_std: float = 1.8
    # feed_bias 分布（权重和 1.0 ± 1e-6）
    feed_bias_distribution: Mapping[FeedBias, float] = field(
        default_factory=lambda: {"global": 0.55, "local": 0.15, "mixed": 0.30}
    )
    headphones_hours_mean: float = 1.5
    headphones_hours_std: float = 1.0
    responsiveness_mean: float = 0.5
    responsiveness_std: float = 0.25
    primary_apps_pool: tuple[str, ...] = (
        "wechat", "instagram", "tiktok", "facebook", "xhs", "linkedin", "nextdoor",
    )
    primary_apps_count: int = 3


def _validate_distribution(name: str, dist: Mapping[str, float]) -> None:
    if not dist:
        raise ValueError(f"{name}: distribution must be non-empty")
    total = sum(dist.values())
    if abs(total - 1.0) > _WEIGHT_EPS:
        raise ValueError(
            f"{name}: distribution weights must sum to 1.0 (got {total:.6f})"
        )


class PopulationProfile(BaseModel):
    """
    一个社区的人群画像。

    边缘分布：每个维度独立采样（后续 change 可加入相关性矩阵）。
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    size: int = Field(ge=1)

    ethnicity_distribution: Mapping[str, float]
    housing_distribution: Mapping[HousingTenure, float]
    income_distribution: Mapping[IncomeTier, float]
    work_mode_distribution: Mapping[WorkMode, float]
    age_bracket_distribution: Mapping[str, float]
    language_distribution: Mapping[str, float]
    household_distribution: Mapping[str, float] = Field(
        default_factory=lambda: {"single": 0.35, "couple": 0.30, "family_with_kids": 0.35}
    )

    # 年龄区间到 (min, max) 岁数映射
    age_bracket_bounds: Mapping[str, tuple[int, int]] = Field(
        default_factory=lambda: {
            "youth": (16, 29),
            "adult": (30, 54),
            "elderly": (55, 85),
        }
    )

    digital_params: DigitalParams = Field(default_factory=DigitalParams)
    personality_params: PersonalityParams = Field(default_factory=PersonalityParams)

    # protagonists: 默认 base_model
    sonnet_model: str = "claude-sonnet-4-6"
    haiku_model: str = "claude-haiku-4-5-20251001"

    @field_validator(
        "ethnicity_distribution",
        "housing_distribution",
        "income_distribution",
        "work_mode_distribution",
        "age_bracket_distribution",
        "language_distribution",
        "household_distribution",
    )
    @classmethod
    def _dist_sum_to_one(cls, v, info):
        _validate_distribution(info.field_name, v)
        return v


def _weighted_pick(rng: random.Random, distribution: Mapping[str, float]) -> str:
    keys = list(distribution.keys())
    weights = [distribution[k] for k in keys]
    return rng.choices(keys, weights=weights, k=1)[0]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _sample_personality(
    rng: random.Random, params: PersonalityParams
) -> PersonalityTraits:
    """独立高斯采样 8 个维度，clamp 到 [0, 1]（typed-personality change）。"""
    def sample(pair: tuple[float, float]) -> float:
        mean, std = pair
        return _clamp(rng.gauss(mean, std), 0.0, 1.0)

    return PersonalityTraits(
        openness=sample(params.openness),
        conscientiousness=sample(params.conscientiousness),
        extraversion=sample(params.extraversion),
        agreeableness=sample(params.agreeableness),
        neuroticism=sample(params.neuroticism),
        curiosity=sample(params.curiosity),
        routine_adherence=sample(params.routine_adherence),
        risk_tolerance=sample(params.risk_tolerance),
    )


def _sample_digital(rng: random.Random, params: DigitalParams) -> DigitalProfile:
    bias = _weighted_pick(rng, params.feed_bias_distribution)
    screen = _clamp(rng.gauss(params.screen_hours_mean, params.screen_hours_std), 0.0, 16.0)
    headphones = _clamp(
        rng.gauss(params.headphones_hours_mean, params.headphones_hours_std),
        0.0,
        12.0,
    )
    responsiveness = _clamp(
        rng.gauss(params.responsiveness_mean, params.responsiveness_std),
        0.0,
        1.0,
    )
    pool = list(params.primary_apps_pool)
    count = min(params.primary_apps_count, len(pool))
    apps = tuple(rng.sample(pool, count))
    return DigitalProfile(
        daily_screen_hours=screen,
        feed_bias=bias,  # type: ignore[arg-type]
        headphones_hours=headphones,
        notification_responsiveness=responsiveness,
        primary_apps=apps,
    )


def sample_population(
    profile: PopulationProfile,
    *,
    seed: int,
    num_protagonists: int = 0,
    home_locations: tuple[str, ...] | None = None,
) -> list[AgentProfile]:
    """
    按画像采样出一个 AgentProfile 列表。

    Args:
        profile: 人群画像（边缘分布）
        seed: 随机种子（决定性：同 seed 产出逐字段一致）
        num_protagonists: 标记为 is_protagonist=True 的数量，SHALL 使用 Sonnet 档
        home_locations: 家位置 id 的可选池；若为空，每个 agent 的 home_location
            用占位字符串 "home_{index}"，由上层 orchestrator 分配

    Returns:
        长度为 profile.size 的 AgentProfile 列表
    """
    if num_protagonists > profile.size:
        raise ValueError(
            f"num_protagonists ({num_protagonists}) exceeds population size ({profile.size})"
        )

    rng = random.Random(seed)

    profiles: list[AgentProfile] = []
    for index in range(profile.size):
        age_bracket = _weighted_pick(rng, profile.age_bracket_distribution)
        lo, hi = profile.age_bracket_bounds[age_bracket]
        age = rng.randint(lo, hi)

        ethnicity = _weighted_pick(rng, profile.ethnicity_distribution)
        housing = _weighted_pick(rng, profile.housing_distribution)
        income = _weighted_pick(rng, profile.income_distribution)
        work_mode = _weighted_pick(rng, profile.work_mode_distribution)
        household = _weighted_pick(rng, profile.household_distribution)
        language = _weighted_pick(rng, profile.language_distribution)

        # Migration tenure: if ethnicity has "-migrant-" marker, sample a plausible value
        if "migrant-1gen" in ethnicity:
            migration_tenure = _clamp(rng.gauss(8.0, 5.0), 0.0, 40.0)
        elif "migrant-2gen" in ethnicity:
            migration_tenure = None  # 2nd-gen: born here, tenure not meaningful
        else:
            migration_tenure = None

        digital = _sample_digital(rng, profile.digital_params)
        personality = _sample_personality(rng, profile.personality_params)

        if home_locations:
            home = rng.choice(home_locations)
        else:
            home = f"home_{index:04d}"

        agent_id = f"a_{seed}_{index:04d}"

        profiles.append(AgentProfile(
            agent_id=agent_id,
            name=f"agent_{index}",
            age=age,
            occupation=_occupation_for(work_mode, rng),
            household=household,  # type: ignore[arg-type]
            home_location=home,
            languages=[language],
            personality=personality,
            ethnicity_group=ethnicity,
            migration_tenure_years=migration_tenure,
            housing_tenure=housing,
            income_tier=income,
            work_mode=work_mode,
            digital=digital,
            is_protagonist=False,
            base_model=profile.haiku_model,
        ))

    # Assign protagonists: pick deterministically from rng
    if num_protagonists > 0:
        protagonist_indices = set(rng.sample(range(profile.size), num_protagonists))
        for i in protagonist_indices:
            existing = profiles[i]
            profiles[i] = existing.model_copy(update={
                "is_protagonist": True,
                "base_model": profile.sonnet_model,
            })

    return profiles


def _occupation_for(work_mode: WorkMode, rng: random.Random) -> str:
    """粗略的 work_mode → occupation 映射（placeholder）。"""
    pools = {
        "commute": ("office_worker", "retail_clerk", "teacher", "nurse"),
        "remote": ("software_dev", "designer", "writer", "analyst"),
        "shift": ("barista", "security_guard", "hospitality", "warehouse"),
        "nonworking": ("retired", "student", "caregiver", "unemployed"),
    }
    return rng.choice(pools[work_mode])


# ============================================================================
# Presets
# ============================================================================

# TODO(realign-to-social-thesis): 这些分布是 placeholder。真实数值应在后续
# change 中由 ABS 2021 census + Lane Cove council 的人口统计驱动。

LANE_COVE_PROFILE = PopulationProfile(
    name="lanecove_v0_placeholder",
    size=1000,
    ethnicity_distribution={
        "AU-born": 0.55,
        "AU-migrant-1gen-europe": 0.10,
        "AU-migrant-1gen-asia": 0.20,
        "AU-migrant-2gen-asia": 0.10,
        "AU-migrant-2gen-europe": 0.05,
    },
    housing_distribution={
        "owner_occupier": 0.60,
        "renter": 0.35,
        "public_housing": 0.05,
    },
    income_distribution={
        "low": 0.15,
        "mid": 0.60,
        "high": 0.25,
    },
    work_mode_distribution={
        "commute": 0.50,
        "remote": 0.20,
        "shift": 0.10,
        "nonworking": 0.20,
    },
    age_bracket_distribution={
        "youth": 0.20,
        "adult": 0.55,
        "elderly": 0.25,
    },
    language_distribution={
        "English": 0.70,
        "Mandarin": 0.12,
        "Cantonese": 0.05,
        "Italian": 0.03,
        "Korean": 0.03,
        "Greek": 0.02,
        "other": 0.05,
    },
)


