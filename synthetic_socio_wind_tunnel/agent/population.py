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
    CareHours,
    CommunityTenure,
    DisabilityCare,
    DisabilityStatus,
    DwellingStructure,
    EducationLevel,
    EnglishProficiency,
    FamilyComposition,
    Gender,
    Household,
    HousingTenure,
    IncomeTier,
    IndigenousStatus,
    LifePattern,
    VehiclesAtDwelling,
    VolunteerStatus,
    WorkMode,
    YearOfArrival,
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
    # gender_distribution: ABS Census 2021 typically gives binary;
    # non_binary defaults to 0 unless community-specific data overrides.
    gender_distribution: Mapping[Gender, float] = Field(
        default_factory=lambda: {"male": 0.487, "female": 0.513, "non_binary": 0.0}
    )

    # === agent-profile-enrich (2026-04-27): 13 new distributions ===
    # Default empty dict means: don't sample this dimension; AgentProfile
    # field stays None. Override per-PopulationProfile (e.g. LANE_COVE_PROFILE
    # ships ABS-derived values).
    community_tenure_distribution: Mapping[CommunityTenure, float] = Field(default_factory=dict)
    unpaid_child_care_distribution: Mapping[CareHours, float] = Field(default_factory=dict)
    unpaid_domestic_distribution: Mapping[CareHours, float] = Field(default_factory=dict)
    unpaid_disability_care_distribution: Mapping[DisabilityCare, float] = Field(default_factory=dict)
    volunteer_distribution: Mapping[VolunteerStatus, float] = Field(default_factory=dict)
    english_proficiency_distribution: Mapping[EnglishProficiency, float] = Field(default_factory=dict)
    family_composition_distribution: Mapping[FamilyComposition, float] = Field(default_factory=dict)
    dwelling_structure_distribution: Mapping[DwellingStructure, float] = Field(default_factory=dict)
    vehicles_distribution: Mapping[VehiclesAtDwelling, float] = Field(default_factory=dict)
    year_of_arrival_distribution: Mapping[YearOfArrival, float] = Field(default_factory=dict)
    indigenous_distribution: Mapping[IndigenousStatus, float] = Field(default_factory=dict)
    disability_distribution: Mapping[DisabilityStatus, float] = Field(default_factory=dict)
    education_distribution: Mapping[EducationLevel, float] = Field(default_factory=dict)

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
        "gender_distribution",
    )
    @classmethod
    def _dist_sum_to_one(cls, v, info):
        _validate_distribution(info.field_name, v)
        return v

    @field_validator(
        "community_tenure_distribution",
        "unpaid_child_care_distribution",
        "unpaid_domestic_distribution",
        "unpaid_disability_care_distribution",
        "volunteer_distribution",
        "english_proficiency_distribution",
        "family_composition_distribution",
        "dwelling_structure_distribution",
        "vehicles_distribution",
        "year_of_arrival_distribution",
        "indigenous_distribution",
        "disability_distribution",
        "education_distribution",
    )
    @classmethod
    def _optional_dist_sum_to_one(cls, v, info):
        """Empty dict = don't sample; non-empty = must sum to 1.0."""
        if v:
            _validate_distribution(info.field_name, v)
        return v


def _weighted_pick(rng: random.Random, distribution: Mapping[str, float]) -> str:
    keys = list(distribution.keys())
    weights = [distribution[k] for k in keys]
    return rng.choices(keys, weights=weights, k=1)[0]


def _optional_pick(
    rng: random.Random, distribution: Mapping[str, float],
) -> str | None:
    """Like _weighted_pick but returns None when distribution is empty."""
    if not distribution:
        return None
    return _weighted_pick(rng, distribution)


# family_composition (G27/G29) → household (3-bucket Literal) mapping.
# Used by sample_population to populate `household` deterministically from
# `family_composition` while keeping the public Household type unchanged.
_FAMILY_COMP_TO_HOUSEHOLD: Mapping[str, str] = {
    "lone_person": "single",
    "couple_no_kids": "couple",
    "couple_kids_15plus": "couple",
    "couple_kids_under_15": "family_with_kids",
    "one_parent_family": "family_with_kids",
    "group_household": "single",
    "other": "single",
}


def _household_from_family_composition(fc: str | None) -> str | None:
    if fc is None:
        return None
    return _FAMILY_COMP_TO_HOUSEHOLD.get(fc, "single")


def _sample_life_pattern(
    rng: random.Random,
    *,
    home_location: str | None,
    destinations: tuple[str, ...] | None,
) -> LifePattern:
    """
    Sample one agent's sticky 14-day routine anchor.

    Preferred destinations are picked from the `destinations` pool (when
    provided). When the pool is empty / None, fields stay None so plan
    generation falls back to per-day random destinations (no sticky anchor).

    Time offsets use gaussian priors centered at minute 30 of their hour
    window (i.e. 7:30 morning, 17:30 evening), std 12 minutes — matching the
    bell-shape of real commute departure distributions before ABS Travel
    Survey data ships.
    """
    if not destinations:
        morning = int(rng.gauss(30, 12)) % 60
        evening = int(rng.gauss(30, 15)) % 60
        return LifePattern(
            morning_commute_minute=max(0, min(59, morning)),
            evening_return_minute=max(0, min(59, evening)),
        )

    # Pick distinct preferred destinations; if pool is small, allow reuse
    pool = list(destinations)
    if home_location and home_location in pool:
        pool = [d for d in pool if d != home_location]

    def _pick():
        return rng.choice(pool) if pool else None

    return LifePattern(
        preferred_cafe=_pick(),
        preferred_leisure_park=_pick(),
        preferred_errand_destination=_pick(),
        morning_commute_minute=max(0, min(59, int(rng.gauss(30, 12)) % 60)),
        evening_return_minute=max(0, min(59, int(rng.gauss(30, 15)) % 60)),
        weekend_outing_destination=_pick(),
    )


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
        # Always draw household here to keep RNG sequence stable across the
        # agent-profile-enrich change (preserves byte-equal output for the
        # original 6 calibration dims). Override below if family_composition
        # is sampled.
        household = _weighted_pick(rng, profile.household_distribution)
        language = _weighted_pick(rng, profile.language_distribution)
        gender = _weighted_pick(rng, profile.gender_distribution)

        # 13 enrichment fields (agent-profile-enrich change). Each Optional;
        # returns None when distribution is empty.
        community_tenure = _optional_pick(rng, profile.community_tenure_distribution)
        unpaid_child_care = _optional_pick(rng, profile.unpaid_child_care_distribution)
        unpaid_domestic = _optional_pick(rng, profile.unpaid_domestic_distribution)
        unpaid_disability_care = _optional_pick(rng, profile.unpaid_disability_care_distribution)
        volunteer = _optional_pick(rng, profile.volunteer_distribution)
        english_proficiency = _optional_pick(rng, profile.english_proficiency_distribution)
        family_composition = _optional_pick(rng, profile.family_composition_distribution)
        dwelling_structure = _optional_pick(rng, profile.dwelling_structure_distribution)
        vehicles = _optional_pick(rng, profile.vehicles_distribution)
        year_of_arrival = _optional_pick(rng, profile.year_of_arrival_distribution)
        indigenous = _optional_pick(rng, profile.indigenous_distribution)
        disability = _optional_pick(rng, profile.disability_distribution)
        education = _optional_pick(rng, profile.education_distribution)

        # Override household from family_composition mapping when present
        # (richer signal than the legacy 3-bucket distribution).
        if family_composition is not None:
            household = _household_from_family_composition(family_composition) or household

        # Migration tenure: country-of-birth != Australia → 1st-gen migrant.
        # 2nd-gen migrants (born here to migrant parents) aren't separable from
        # ABS Country-of-Birth alone; we model them as Australia-born here.
        if ethnicity != "Australia" and ethnicity != "other":
            migration_tenure = _clamp(rng.gauss(8.0, 5.0), 0.0, 40.0)
        else:
            migration_tenure = None

        digital = _sample_digital(rng, profile.digital_params)
        personality = _sample_personality(rng, profile.personality_params)

        if home_locations:
            home = rng.choice(home_locations)
        else:
            home = f"home_{index:04d}"

        # agent-realistic-routine: per-agent sticky LifePattern. Sampled
        # last to keep RNG sequence stable for prior fields (preserves
        # byte-equality on calibration dims that came before).
        life_pattern = _sample_life_pattern(
            rng, home_location=home, destinations=home_locations,
        )

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
            gender=gender,  # type: ignore[arg-type]
            digital=digital,
            is_protagonist=False,
            base_model=profile.haiku_model,
            # enrichment fields
            community_tenure_5yr=community_tenure,  # type: ignore[arg-type]
            unpaid_child_care_hours=unpaid_child_care,  # type: ignore[arg-type]
            unpaid_domestic_hours=unpaid_domestic,  # type: ignore[arg-type]
            unpaid_disability_care_hours=unpaid_disability_care,  # type: ignore[arg-type]
            volunteer_status=volunteer,  # type: ignore[arg-type]
            english_proficiency=english_proficiency,  # type: ignore[arg-type]
            family_composition=family_composition,  # type: ignore[arg-type]
            dwelling_structure=dwelling_structure,  # type: ignore[arg-type]
            vehicles_at_dwelling=vehicles,  # type: ignore[arg-type]
            year_of_arrival_bucket=year_of_arrival,  # type: ignore[arg-type]
            indigenous_status=indigenous,  # type: ignore[arg-type]
            disability_status=disability,  # type: ignore[arg-type]
            education_level=education,  # type: ignore[arg-type]
            life_pattern=life_pattern,
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

# Calibrated against ABS Census 2021 SA2 121011686 Lane Cove (15,888 people)
# via `tools/convert_abs_census.py` (see `agent-calibration` change).
# Bucket schema matches `data/calibration/abs_census_lanecove_2021.json` so
# `tools/run_calibration.py` can compute chi² without bucket re-mapping.
#
# Note: 2021 census was conducted during Sydney COVID Delta lockdown — work_mode
# `remote` (55%) is anomalously high vs steady-state Lane Cove (~18%). We use
# ABS values directly here so calibration matches the static snapshot;
# downstream researchers should disclose this in publishable artifacts.
LANE_COVE_PROFILE = PopulationProfile(
    name="lanecove_2021_abs_calibrated",
    size=1000,
    # Country-of-birth proxy; values from ABS G09 SA2 121011686
    ethnicity_distribution={
        "Australia": 0.5828,
        "China": 0.0525,
        "England": 0.0484,
        "India": 0.0271,
        "New_Zealand": 0.0188,
        "Hong_Kong_SAR_Ch": 0.0157,
        "South_Africa": 0.0147,
        "Philippines": 0.0120,
        "USA": 0.0103,
        "Vietnam": 0.0046,
        "other": 0.2131,
    },
    housing_distribution={
        "owner_occupier": 0.439,
        "renter": 0.544,
        "public_housing": 0.017,
    },
    income_distribution={
        "low": 0.327,
        "mid": 0.282,
        "high": 0.391,
    },
    # ABS G62 doesn't separate shift work; we estimate 5% from healthcare /
    # hospitality / retail employment in Lane Cove (Industry of Employment
    # G54), then re-normalize the other three buckets proportionally to ABS.
    # Calibration will show small loss on work_mode chi² vs ABS due to this
    # synthetic split; acceptable at best-effort tier.
    work_mode_distribution={
        "commute": 0.324,
        "remote": 0.527,
        "shift": 0.050,
        "nonworking": 0.099,
    },
    # 11-bucket age aligned with ABS G01
    age_bracket_distribution={
        "0-4": 0.068,
        "5-14": 0.130,
        "15-19": 0.049,
        "20-24": 0.044,
        "25-34": 0.147,
        "35-44": 0.188,
        "45-54": 0.128,
        "55-64": 0.096,
        "65-74": 0.078,
        "75-84": 0.049,
        "85+": 0.023,
    },
    age_bracket_bounds={
        "0-4": (0, 4), "5-14": (5, 14), "15-19": (15, 19),
        "20-24": (20, 24), "25-34": (25, 34), "35-44": (35, 44),
        "45-54": (45, 54), "55-64": (55, 64), "65-74": (65, 74),
        "75-84": (75, 84), "85+": (85, 100),
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
    # === agent-profile-enrich (2026-04-27): 13 thesis-direct dims ===
    # All values from ABS Census 2021 SA2 121011686 Lane Cove via
    # tools/convert_abs_census.py --full
    community_tenure_distribution={
        "established_5plus": 0.5511,
        "recent_1_5yr": 0.3591,
        "new_<1yr": 0.0898,
    },
    unpaid_child_care_distribution={
        "none": 0.6826,
        "1_14": 0.0000,
        "15_29": 0.3174,
        "30plus": 0.0000,
    },
    unpaid_domestic_distribution={
        "none": 0.1998,
        "1_14": 0.5731,
        "15_29": 0.1435,
        "30plus": 0.0836,
    },
    unpaid_disability_care_distribution={
        "none": 0.8890,
        "yes": 0.1110,
    },
    volunteer_distribution={
        "volunteer": 0.1770,
        "non_volunteer": 0.8230,
    },
    english_proficiency_distribution={
        "english_only": 0.6981,
        "very_well": 0.1348,
        "well": 0.1348,
        "not_well": 0.0162,
        "not_at_all": 0.0161,  # sum-fix
    },
    family_composition_distribution={
        "lone_person": 0.0000,
        "couple_no_kids": 0.2666,
        "couple_kids_under_15": 0.4923,
        "couple_kids_15plus": 0.1373,
        "one_parent_family": 0.0945,
        "group_household": 0.0000,
        "other": 0.0093,  # sum-fix
    },
    dwelling_structure_distribution={
        "separate_house": 0.4626,
        "semi_detached": 0.0724,
        "flat_apartment": 0.4630,
        "other_dwelling": 0.0020,
    },
    vehicles_distribution={
        "0": 0.0918,
        "1": 0.5049,
        "2": 0.3169,
        "3plus": 0.0864,
    },
    year_of_arrival_distribution={
        "pre_2000": 0.1632,
        "2000_2010": 0.0873,
        "2011_2015": 0.0644,
        "2016_2021": 0.0710,
        "australian_born": 0.6141,
    },
    indigenous_distribution={
        "indigenous": 0.0075,
        "non_indigenous": 0.9925,
    },
    disability_distribution={
        "needs_assistance": 0.0328,
        "no_assistance": 0.9672,
    },
    education_distribution={
        "postgrad": 0.2133,
        "bachelor": 0.3569,
        "diploma": 0.0707,
        "year_12": 0.2032,
        "year_11_or_below": 0.1185,
        "no_qualification": 0.0374,
    },
)


