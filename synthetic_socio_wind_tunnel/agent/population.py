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

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.location_pools import LocationPools
    from synthetic_socio_wind_tunnel.agent.planner import LLMClient
    from synthetic_socio_wind_tunnel.atlas import Atlas


logger = logging.getLogger(__name__)

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


_HOUSEHOLD_TARGET_SIZE: dict[str, int] = {
    # family_composition → typical # of agents in same household
    "lone_person": 1,
    "couple_no_kids": 2,
    "couple_kids_under_15": 4,
    "couple_kids_15plus": 4,
    "one_parent_family": 3,
    "group_household": 3,
    "other": 1,
}


def _assign_household(
    new_profiles: list, chunk: list[int], fc: str, seed: int,
    household_counter: int,
) -> None:
    """Mutate new_profiles to assign a shared household_id + roles in-place."""
    hh_id = f"hh_{seed}_{household_counter:05d}"
    shared_home = new_profiles[chunk[0]].home_location
    chunk_with_age = sorted(chunk, key=lambda i: new_profiles[i].age)
    for rank, idx in enumerate(chunk_with_age):
        p = new_profiles[idx]
        if p.age < 18:
            role = "child"
        elif rank == 0 and fc in ("couple_no_kids",):
            role = "partner"
        else:
            role = "parent" if ("kids" in fc or "parent" in fc) else "partner"
        new_profiles[idx] = p.model_copy(update={
            "household_id": hh_id,
            "household_role": role,
            "home_location": shared_home,
        })


def _cluster_into_households(
    profiles: list["AgentProfile"],
    *,
    seed: int,
    rng: random.Random,
    home_pool: tuple[str, ...] = (),
) -> list["AgentProfile"]:
    """A2: post-process sampled agents to cluster into households.

    Groups agents by family_composition; assigns shared household_id +
    home_location for each cluster. Returns a NEW list of profiles
    (frozen models, so we use model_copy).

    Algorithm:
    1. Sort agents into per-family_composition buckets.
    2. For each bucket, chunk into groups of TARGET_SIZE (4 for family-with-kids,
       2 for couples, 1 for lone). Each chunk = 1 household.
    3. Within a chunk, all agents get household_id = "hh_{seed}_{index}",
       household_role assigned by age (kids vs parent), and shared
       home_location = first agent's home_location.
    """
    by_fc: dict[str, list[int]] = {}
    for i, p in enumerate(profiles):
        fc = p.family_composition or "other"
        by_fc.setdefault(fc, []).append(i)

    new_profiles = list(profiles)
    household_counter = 0

    for fc, indices in by_fc.items():
        target = _HOUSEHOLD_TARGET_SIZE.get(fc, 1)
        if target <= 1:
            # Solo households — each agent gets own household_id
            for idx in indices:
                p = new_profiles[idx]
                hh_id = f"hh_{seed}_{household_counter:05d}"
                household_counter += 1
                new_profiles[idx] = p.model_copy(update={
                    "household_id": hh_id,
                    "household_role": "lone",
                })
            continue

        # Multi-member households — chunk by target size
        # Shuffle to avoid spatial locality bias (don't always pair adjacent indices)
        shuffled = list(indices)
        rng.shuffle(shuffled)
        for chunk_start in range(0, len(shuffled), target):
            chunk = shuffled[chunk_start:chunk_start + target]
            if len(chunk) < 2:
                # Trailing solo (odd count) — give it own household
                idx = chunk[0]
                p = new_profiles[idx]
                hh_id = f"hh_{seed}_{household_counter:05d}"
                household_counter += 1
                new_profiles[idx] = p.model_copy(update={
                    "household_id": hh_id,
                    "household_role": "lone",
                })
                continue

            # fix-realism-systemic-gaps: split chunks whose member age span
            # exceeds 70 years (e.g. infant + 92-year-old should not share a
            # household). The chunk is greedily partitioned into sub-groups
            # whose internal age span ≤ 70, sorted by age.
            chunk_sorted_by_age = sorted(
                chunk, key=lambda i: new_profiles[i].age,
            )
            sub_chunks: list[list[int]] = []
            current_sub: list[int] = []
            current_min_age = None
            for idx in chunk_sorted_by_age:
                age_here = new_profiles[idx].age
                if not current_sub:
                    current_sub = [idx]
                    current_min_age = age_here
                elif age_here - current_min_age <= 70:
                    current_sub.append(idx)
                else:
                    sub_chunks.append(current_sub)
                    current_sub = [idx]
                    current_min_age = age_here
            if current_sub:
                sub_chunks.append(current_sub)

            for sub_chunk in sub_chunks:
                # Single-member fallback (broken away from age-incompatible group)
                if len(sub_chunk) < 2:
                    idx = sub_chunk[0]
                    p = new_profiles[idx]
                    hh_id = f"hh_{seed}_{household_counter:05d}"
                    household_counter += 1
                    new_profiles[idx] = p.model_copy(update={
                        "household_id": hh_id,
                        "household_role": "lone",
                    })
                    continue

                self_chunk = sub_chunk
                _assign_household(
                    new_profiles, self_chunk, fc, seed,
                    household_counter,
                )
                household_counter += 1
    new_profiles = _resolve_home_age_gaps(
        new_profiles, seed=seed, home_pool=home_pool,
    )
    return new_profiles


def _resolve_home_age_gaps(
    profiles: list,
    *,
    seed: int,
    home_pool: tuple[str, ...] = (),
    max_gap: int = 70,
) -> list:
    """Reassign agents whose presence in a home creates > max_gap age span.

    After household clustering, two agents from different households can
    still coincidentally share the same home_location. When their age
    difference exceeds max_gap, the outlier (farthest from cohabitants'
    median age) is bumped to a different residential building drawn from
    home_pool — preferring an unoccupied building, falling back to the
    least-crowded one.
    """
    from collections import defaultdict
    out = list(profiles)
    by_home: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(out):
        by_home[p.home_location].append(i)

    bump_rng = random.Random(seed + 31337)
    for home_id, idxs in list(by_home.items()):
        if len(idxs) < 2:
            continue
        for _ in range(len(idxs)):
            ages = [out[i].age for i in idxs]
            if max(ages) - min(ages) <= max_gap:
                break
            median_age = sorted(ages)[len(ages) // 2]
            worst_i = max(idxs, key=lambda i: abs(out[i].age - median_age))
            new_home = _find_bump_home(home_pool, by_home, bump_rng)
            if new_home is None:
                # No home_pool given (legacy path); keep the agent in place
                break
            out[worst_i] = out[worst_i].model_copy(update={
                "home_location": new_home,
                "household_id": f"hh_{seed}_bumped_{worst_i:05d}",
                "household_role": "lone",
            })
            by_home[home_id].remove(worst_i)
            by_home[new_home].append(worst_i)
            idxs = by_home[home_id]
    return out


def _find_bump_home(
    home_pool: tuple[str, ...],
    by_home: dict[str, list[int]],
    rng: random.Random,
) -> str | None:
    """Return a residential building id with the fewest current residents.

    Prefers unoccupied entries from home_pool; falls back to least crowded.
    """
    if not home_pool:
        return None
    unoccupied = [h for h in home_pool if not by_home.get(h)]
    if unoccupied:
        return rng.choice(sorted(unoccupied))
    # All occupied: pick the least crowded
    candidates = sorted(home_pool, key=lambda h: len(by_home.get(h, [])))
    return candidates[0] if candidates else None


_WORKING_MODES = ("commute", "remote", "shift")


def sample_population(
    profile: PopulationProfile,
    *,
    seed: int,
    num_protagonists: int = 0,
    pools: "LocationPools | None" = None,
    atlas: "Atlas | None" = None,
    max_commute_m: float = 1500.0,
    home_locations: tuple[str, ...] | None = None,
    generate_identity: bool = False,
    llm_client: "LLMClient | None" = None,
    identity_model: str = "",
) -> list[AgentProfile]:
    """
    按画像采样出一个 AgentProfile 列表。

    Args:
        profile: 人群画像（边缘分布）
        seed: 随机种子（决定性：同 seed 产出逐字段一致）
        num_protagonists: 标记为 is_protagonist=True 的数量，SHALL 使用 Sonnet 档
        pools: typed LocationPools (preferred path). home_location SHALL be drawn
            from pools.home_pool (residential buildings); workplace SHALL be
            drawn from pools.work_pool when work_mode ∈ {commute, remote,
            shift}, None otherwise.
        home_locations: DEPRECATED; legacy single-pool of location ids used
            for home_location. Pass `pools=LocationPools(...)` instead. Emits
            DeprecationWarning when used.
        generate_identity: ai-town port — when True, calls `llm_client` for each
            protagonist to fill `identity_text` (~3-sentence persona) and
            `plan_text` (~1-sentence today's goal). Failures fall back to
            deterministic stubs; never raises. Sync wrapper around an async
            asyncio.gather batch.
        llm_client: required when `generate_identity=True`.
        identity_model: optional model override passed to llm_client.generate.

    Returns:
        长度为 profile.size 的 AgentProfile 列表
    """
    if num_protagonists > profile.size:
        raise ValueError(
            f"num_protagonists ({num_protagonists}) exceeds population size ({profile.size})"
        )

    if pools is None and home_locations is not None:
        import warnings as _warn
        _warn.warn(
            "sample_population(home_locations=...) is deprecated; "
            "pass pools=LocationPools(...) to enable typed home/work/poi pools.",
            DeprecationWarning, stacklevel=2,
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
        # fix-realism-systemic-gaps: clamp work_mode distribution by age bracket
        # so children aren't "commute" and 94-year-olds aren't "shift" workers.
        work_mode = _weighted_pick(
            rng, _work_mode_distribution_for_age(
                age, dict(profile.work_mode_distribution),
            ),
        )
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

        if pools is not None:
            home = rng.choice(pools.home_pool)
        elif home_locations:
            home = rng.choice(home_locations)
        else:
            home = f"home_{index:04d}"

        # Pre-pick occupation here so workplace assignment can match
        # occupation type. (Original _occupation_for was called inside
        # AgentProfile(...) below.)
        occupation = _occupation_for(age, work_mode, rng)

        # Workplace assignment (fix-population-uses-typed-locations + fix-realism-
        # systemic-gaps): only for working work_modes; pools-path only.
        # Match workplace to occupation type and respect commute radius.
        workplace: str | None = None
        if pools is not None and work_mode in _WORKING_MODES and pools.work_pool:
            workplace = _pick_workplace_near(
                home, pools.work_pool, occupation, atlas,
                max_commute_m, rng,
            )

        # agent-realistic-routine: per-agent sticky LifePattern. Sampled
        # last to keep RNG sequence stable for prior fields (preserves
        # byte-equality on calibration dims that came before). Pools-path
        # uses poi_pool as life-pattern destination anchors.
        if pools is not None:
            life_pattern_destinations: tuple[str, ...] | None = pools.poi_pool
        else:
            life_pattern_destinations = home_locations
        life_pattern = _sample_life_pattern(
            rng, home_location=home, destinations=life_pattern_destinations,
        )

        # add-walking-speed-budget: derive per-agent travel speed from
        # vehicles_at_dwelling (ABS 2021 distribution). 0 cars → pure walking;
        # higher car ownership → mixed walk+drive, higher per-tick budget.
        #
        # B2 calibration sources (2026-05-13):
        #   - 80 m/min  walking pace: Australian Pedestrian Facilities Guideline
        #                             (Austroads 2017, "5 km/h design value
        #                             for pedestrian network planning")
        #   - 250 m/min urban driving: NSW Bureau of Transport Statistics,
        #                              "Sydney AM/PM peak average ~15 km/h
        #                              including stops" (BTS 2023 HTS data)
        #   - 150 m/min (1-car mixed): interpolation; weighted 60% walking
        #                              + 40% driving for typical 1-car household
        #   - 280 m/min (3+ car): driving + minimal walking; modeled as 17 km/h
        #
        # Per-tick budgets (5-min tick):
        #   80 m/min walking → 400m / 5min
        #   150 m/min mix    → 750m / 5min
        #   250 m/min drive  → 1.25km / 5min
        #   280 m/min heavy  → 1.4km / 5min
        if vehicles in (None, "0"):
            agent_speed = 80.0
            agent_prefer_driving = False
        elif vehicles == "1":
            agent_speed = 150.0
            agent_prefer_driving = True
        elif vehicles == "2":
            agent_speed = 250.0
            agent_prefer_driving = True
        else:  # "3plus"
            agent_speed = 280.0
            agent_prefer_driving = True

        agent_id = f"a_{seed}_{index:04d}"

        profiles.append(AgentProfile(
            agent_id=agent_id,
            name=f"agent_{index}",
            age=age,
            occupation=occupation,
            household=household,  # type: ignore[arg-type]
            home_location=home,
            workplace=workplace,
            walking_speed_m_per_min=agent_speed,
            prefer_driving=agent_prefer_driving,
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

    # A2 / realism-household-coupling: cluster agents into households so
    # multi-member family_composition values (couple, family) actually share
    # home_location + household_id. This unblocks household_kin social_priors
    # rule (which previously fired 0 ties because home_locations were unique
    # per agent).
    cluster_home_pool: tuple[str, ...] = (
        pools.home_pool if pools is not None else (home_locations or ())
    )
    profiles = _cluster_into_households(
        profiles, seed=seed, rng=rng, home_pool=cluster_home_pool,
    )

    # Assign protagonists: pick deterministically from rng. Only adult
    # agents (age >= 18) are eligible — kids running LLM stack is both
    # nonsensical and unsafe (could fabricate child personas).
    if num_protagonists > 0:
        adult_indices = [i for i, p in enumerate(profiles) if p.age >= 18]
        if len(adult_indices) < num_protagonists:
            raise ValueError(
                f"need {num_protagonists} adult protagonists but only "
                f"{len(adult_indices)} adults in population (size={profile.size})"
            )
        protagonist_indices = set(rng.sample(adult_indices, num_protagonists))
        for i in protagonist_indices:
            existing = profiles[i]
            profiles[i] = existing.model_copy(update={
                "is_protagonist": True,
                "base_model": profile.sonnet_model,
            })

    # ai-town port + lane cove archetypes: fill identity_text + plan_text
    # for ALL agents (deterministic template fill for scripted; LLM
    # variation on top for protagonists).
    if generate_identity:
        # Stage 1 + 2: archetype-grounded identity for everyone
        from synthetic_socio_wind_tunnel.data_loader import (
            load_archetypes,
            match_archetype,
        )
        try:
            archetypes = load_archetypes()
        except FileNotFoundError as exc:
            logger.warning(
                "archetypes.json missing (%r); falling back to free-form LLM identity",
                exc,
            )
            archetypes = []

        if archetypes:
            # All agents get an archetype-derived identity_text via
            # template fill (no LLM needed, deterministic).
            profiles = _fill_archetype_identities(profiles, archetypes, rng)

        # Protagonists additionally get LLM variation on their archetype.
        if llm_client is None:
            raise ValueError(
                "sample_population: generate_identity=True requires llm_client"
            )
        profiles = asyncio.run(
            generate_identities_for_protagonists(
                profiles, llm_client=llm_client, model=identity_model,
                archetypes=archetypes,
            )
        )

    return profiles


def _fill_archetype_identities(
    profiles: list[AgentProfile],
    archetypes: list,
    rng: random.Random,
) -> list[AgentProfile]:
    """Match each profile to an archetype + render template with profile values.

    Deterministic — no LLM. Used for scripted (and as protagonist
    fallback). The LLM-variation step (`generate_identities_for_protagonists`)
    runs AFTER this and replaces protagonist identity_text with a
    creatively-varied version using the archetype as seed.
    """
    from synthetic_socio_wind_tunnel.data_loader import match_archetype

    out = list(profiles)
    for i, p in enumerate(out):
        archetype = match_archetype(p, archetypes)
        if archetype is None:
            # No good archetype fit — leave identity_text as None,
            # generate_identities_for_protagonists may still fill it via LLM
            # for protag without a template seed.
            continue

        # Deterministic template fill — handles {name}, {age}, {occupation},
        # and a few computed fields used by the lane cove archetypes.
        identity = _render_template(p, archetype)
        plan_idx = rng.randrange(len(archetype.plan_text_template_examples)) \
            if archetype.plan_text_template_examples else 0
        plan = (
            archetype.plan_text_template_examples[plan_idx]
            if archetype.plan_text_template_examples else ""
        )
        out[i] = p.model_copy(update={
            "identity_text": identity,
            "plan_text": plan,
        })
    return out


def _render_template(p: AgentProfile, archetype) -> str:
    """Render an archetype's identity_text_template with profile values.

    Handles all known placeholders. Missing placeholders fall back to a
    sensible value rather than crash. ⚠️ Templates are CHINESE prose
    (matching the LLM target language).
    """
    template = archetype.identity_text_template
    # Estimated tenure_years if community_tenure_5yr is set
    tenure_map = {
        "new_<1yr": "不到 1",
        "recent_1_5yr": "3",
        "established_5plus": "10",
    }
    tenure_years = tenure_map.get(p.community_tenure_5yr or "", "几")

    migration_years = "?"
    if p.migration_tenure_years is not None:
        migration_years = str(int(p.migration_tenure_years))

    origin_country = p.ethnicity_group or "海外"
    origin_state = "interstate"

    kid_count = "1-2"  # rough default
    if p.family_composition == "couple_kids_under_15":
        kid_count = "2"
    elif p.family_composition == "one_parent_family":
        kid_count = "1"

    years_in_business = tenure_years

    # personality_descriptor — short Chinese prose from personality bias
    p_t = p.personality
    descriptor_bits = []
    if p_t.extraversion > 0.65:
        descriptor_bits.append("外向健谈")
    elif p_t.extraversion < 0.4:
        descriptor_bits.append("内敛少言")
    if p_t.routine_adherence > 0.65:
        descriptor_bits.append("作息规律")
    elif p_t.routine_adherence < 0.4:
        descriptor_bits.append("不太按计划过日子")
    if p_t.openness > 0.65:
        descriptor_bits.append("好奇新事物")
    if not descriptor_bits:
        descriptor_bits.append("性格中等温和")
    personality_descriptor = "、".join(descriptor_bits)

    interests_list = "、".join(p.interests[:3]) if p.interests else (
        "、".join(archetype.interests_pool[:3]) if archetype.interests_pool
        else "本地的事"
    )

    placeholders = {
        "name": p.name,
        "age": str(p.age),
        "occupation": p.occupation,
        "tenure_years": tenure_years,
        "migration_years": migration_years,
        "origin_country": origin_country,
        "origin_state": origin_state,
        "kid_count": kid_count,
        "years_in_business": years_in_business,
        "personality_descriptor": personality_descriptor,
        "interests_list": interests_list,
    }
    try:
        return template.format(**placeholders)
    except KeyError as exc:
        logger.warning(
            "template missing placeholder %r for archetype %s; using raw template",
            exc, archetype.archetype_id,
        )
        return template


# ---------------------------------------------------------------------------
# ai-town port: identity / plan generation (Phase D task 16)
# ---------------------------------------------------------------------------


def _build_identity_prompt(
    p: AgentProfile,
    archetype=None,
    pre_filled_identity: str | None = None,
    pre_filled_plan: str | None = None,
) -> str:
    """Build identity-generation prompt for the LLM.

    When `archetype` is provided, asks the LLM to **vary on the archetype
    template** (preserving Lane Cove specificity) rather than write from
    scratch — anchors output to real local persona patterns. When
    `pre_filled_identity` / `pre_filled_plan` come in (from the
    deterministic template-fill pass), those are passed as the seed.
    """
    p_t = p.personality
    interests_str = ", ".join(p.interests) if p.interests else "everyday things"

    if archetype is not None:
        # Archetype-grounded path — ask LLM to embellish, not invent.
        seed_identity = pre_filled_identity or archetype.identity_text_template
        seed_plan = pre_filled_plan or (
            archetype.plan_text_template_examples[0]
            if archetype.plan_text_template_examples else ""
        )
        return (
            f"你是一位 Lane Cove (Sydney NSW 2066) 城市模拟里的人物创作者。"
            f"我已经把这个 agent 匹配到了 archetype 模板 "
            f"'{archetype.label}' ({archetype.archetype_id})；你的任务是**在模板上做"
            f"自然变奏**——保留 Lane Cove 本地化特征，但加入这个 agent 的"
            f"独特细节。**不要从零写**。\n\n"
            f"=== Agent 结构化事实 ===\n"
            f"- 姓名：{p.name}\n"
            f"- 年龄：{p.age}\n"
            f"- 职业：{p.occupation}\n"
            f"- 家庭：{p.household}\n"
            f"- Personality（0-1）：openness={p_t.openness:.2f}, "
            f"extraversion={p_t.extraversion:.2f}, "
            f"conscientiousness={p_t.conscientiousness:.2f}, "
            f"agreeableness={p_t.agreeableness:.2f}, "
            f"neuroticism={p_t.neuroticism:.2f}, "
            f"curiosity={p_t.curiosity:.2f}, "
            f"routine_adherence={p_t.routine_adherence:.2f}\n"
            f"- 兴趣：{interests_str}\n\n"
            f"=== Archetype 模板（已预填了 placeholder）===\n"
            f"identity 草稿：{seed_identity}\n"
            f"plan 草稿：{seed_plan}\n"
            f"archetype 兴趣池（参考）：{', '.join(archetype.interests_pool[:5])}\n\n"
            f"=== 输出格式 ===\n"
            f"只输出 JSON，无 prose，无 markdown fence：\n"
            f'{{"identity": "...", "plan": "..."}}\n\n'
            f"=== 任务要求 ===\n"
            f"- identity (2-3 句中文)：保留模板里的 Lane Cove 地名 / 习惯，"
            f"加入呼应 personality 数值的细节（高 extraversion = 健谈活跃；"
            f"低 openness = 偏好熟悉路径），让人物更立体。**不要复述 personality "
            f"数值本身**。\n"
            f"- plan (1 句中文)：在草稿基础上做小变奏（可换地点 / 时间 / 同伴），"
            f"保持 archetype 的活动模式。\n"
            f"- 全部用第三人称，现在时。"
        )

    # Fallback (no archetype) — original free-form path
    return (
        f"You are a creative writer crafting a persona for an AI character "
        f"in a city-life simulation set in Lane Cove, Sydney.\n\n"
        f"Profile facts (use these but don't repeat them verbatim):\n"
        f"- Name: {p.name}\n"
        f"- Age: {p.age}\n"
        f"- Occupation: {p.occupation}\n"
        f"- Household: {p.household}\n"
        f"- Lives at: {p.home_location}\n"
        f"- Personality traits (0-1 scale): "
        f"openness={p_t.openness:.2f}, "
        f"extraversion={p_t.extraversion:.2f}, "
        f"conscientiousness={p_t.conscientiousness:.2f}, "
        f"agreeableness={p_t.agreeableness:.2f}, "
        f"neuroticism={p_t.neuroticism:.2f}, "
        f"curiosity={p_t.curiosity:.2f}\n"
        f"- Interests: {interests_str}\n\n"
        f"Output JSON ONLY, no prose, no markdown fence, exactly this shape:\n"
        f'{{"identity": "...", "plan": "..."}}\n\n'
        f"Where:\n"
        f"- identity: a 2-3 sentence first-impression description of who "
        f"{p.name} is, what they care about, how they move through the day. "
        f"Reflect the personality numbers above (high extraversion → "
        f"chatty / outgoing; low openness → routine-loving; etc.). "
        f"Use third person, present tense.\n"
        f'- plan: ONE sentence describing what {p.name} wants out of today. '
        f"Vague is fine ('catch up with neighbours', 'find a quiet cafe'). "
        f"Should feel plausible given the occupation and personality."
    )


def _identity_fallback(p: AgentProfile) -> str:
    """Deterministic identity stub when LLM fails or is unavailable."""
    home = p.home_location or "the area"
    return (
        f"{p.name} is a {p.age}-year-old {p.occupation} living in {home}. "
        f"Comfortable with everyday routines."
    )


def _plan_fallback(p: AgentProfile) -> str:
    """Deterministic plan stub when LLM fails or is unavailable."""
    return f"Spend the day on {p.occupation}-related routines."


def _parse_identity_response(raw: str, p: AgentProfile) -> tuple[str, str]:
    """Parse LLM JSON response → (identity, plan). Falls back on parse error."""
    text = (raw or "").strip()
    # Strip optional ```json fences
    if text.startswith("```"):
        text = text.strip("`")
        # Remove leading "json\n" if present
        if text.lower().startswith("json"):
            text = text.split("\n", 1)[1] if "\n" in text else ""
    try:
        obj = json.loads(text)
        identity = str(obj.get("identity", "")).strip()
        plan = str(obj.get("plan", "")).strip()
        if identity and plan:
            return identity, plan
    except (json.JSONDecodeError, ValueError, AttributeError):
        pass
    logger.warning(
        "identity LLM parse failed for agent %s; using fallback",
        p.agent_id,
    )
    return _identity_fallback(p), _plan_fallback(p)


async def _fill_one_identity(
    p: AgentProfile,
    llm_client: "LLMClient",
    *,
    model: str = "",
    archetype=None,
) -> tuple[str, str]:
    try:
        prompt = _build_identity_prompt(
            p,
            archetype=archetype,
            pre_filled_identity=p.identity_text,  # may be from template fill
            pre_filled_plan=p.plan_text,
        )
        raw = await llm_client.generate(prompt, model=model)
        return _parse_identity_response(raw, p)
    except Exception as exc:
        logger.warning(
            "identity LLM call failed for agent %s: %r; using fallback",
            p.agent_id, exc,
        )
        # If we already filled from template earlier, keep that.
        if p.identity_text and p.plan_text:
            return p.identity_text, p.plan_text
        return _identity_fallback(p), _plan_fallback(p)


async def generate_identities_for_protagonists(
    profiles: list[AgentProfile],
    *,
    llm_client: "LLMClient",
    model: str = "",
    batch_size: int = 5,
    archetypes: list | None = None,
) -> list[AgentProfile]:
    """Concurrently fill identity_text + plan_text for every protagonist.

    Non-protagonists are returned unchanged. Failures fall back to
    deterministic stubs / pre-filled template values (no exceptions
    surface to caller). Batching limits concurrent LLM calls to
    `batch_size` at a time so we don't burst quota.

    When `archetypes` is provided, each protag's matched archetype is
    used as a seed so the LLM does archetype-grounded variation rather
    than free-form invention.
    """
    from synthetic_socio_wind_tunnel.data_loader import match_archetype

    out = list(profiles)
    indices = [i for i, p in enumerate(out) if p.is_protagonist]
    if not indices:
        return out

    for batch_start in range(0, len(indices), batch_size):
        batch = indices[batch_start:batch_start + batch_size]
        # Per-agent archetype lookup
        per_agent_archetype = []
        for i in batch:
            arch = (
                match_archetype(out[i], archetypes)
                if archetypes else None
            )
            per_agent_archetype.append(arch)
        results = await asyncio.gather(*[
            _fill_one_identity(out[i], llm_client, model=model, archetype=arch)
            for i, arch in zip(batch, per_agent_archetype)
        ])
        for i, (identity, plan) in zip(batch, results):
            out[i] = out[i].model_copy(update={
                "identity_text": identity,
                "plan_text": plan,
            })
    return out


def _age_bracket(age: int) -> str:
    """Age bracket key used by population cross-constraints."""
    if age < 16: return "<16"
    if age < 22: return "16-21"
    if age < 65: return "22-64"
    if age < 75: return "65-74"
    return ">=75"


# fix-realism-systemic-gaps: (age_bracket, work_mode) → list[occupation] lookup
# Avoids "5-year-old software_dev" and "94-year-old commuting nurse" issues
# found in the systemic realism audit. Maps WorkMode Literal values only
# (commute/remote/shift/nonworking).
_OCCUPATION_BY_AGE_MODE: dict[tuple[str, str], tuple[str, ...]] = {
    # children: school-going only
    ("<16", "nonworking"): ("student",),
    ("<16", "commute"): ("student",),  # safety net (shouldn't fire post-clamp)
    ("<16", "remote"): ("student",),
    ("<16", "shift"): ("student",),
    # young adults: students + early career
    ("16-21", "nonworking"): ("student", "unemployed"),
    ("16-21", "commute"): ("retail_worker", "tradesperson", "construction",
                            "student"),
    ("16-21", "remote"): ("student", "designer", "writer"),
    ("16-21", "shift"): ("retail_worker", "barista", "hospitality", "student"),
    # prime working age: full base pool
    ("22-64", "commute"): (
        "software_dev", "manager", "engineer", "teacher", "nurse",
        "doctor", "designer", "consultant", "retail_worker", "construction",
        "accountant", "lawyer", "tradesperson",
    ),
    ("22-64", "remote"): (
        "software_dev", "writer", "designer", "consultant", "accountant",
        "marketer", "analyst",
    ),
    ("22-64", "shift"): ("barista", "security_guard", "hospitality",
                          "warehouse", "tradesperson", "nurse"),
    ("22-64", "nonworking"): ("homemaker", "unemployed", "caregiver"),
    # near-retirement: mostly retired, some still in workforce part-time
    ("65-74", "nonworking"): ("retired",),
    ("65-74", "commute"): ("consultant", "manager", "tutor"),
    ("65-74", "remote"): ("consultant", "writer"),
    ("65-74", "shift"): ("volunteer_coordinator", "tutor", "retired"),
    # elders: not working
    (">=75", "nonworking"): ("retired",),
    (">=75", "commute"): ("retired",),  # safety net
    (">=75", "remote"): ("retired",),
    (">=75", "shift"): ("retired",),
}


def _occupation_for(age: int, work_mode: WorkMode, rng: random.Random) -> str:
    """Pick occupation by (age_bracket, work_mode); deterministic given rng."""
    key = (_age_bracket(age), str(work_mode))
    candidates = _OCCUPATION_BY_AGE_MODE.get(key)
    if not candidates:
        # Fallback for unexpected combos (shouldn't happen post-clamp)
        candidates = ("student" if age < 18 else
                       "retired" if age >= 65 else "consultant",)
    return rng.choice(candidates)


# fix-realism-systemic-gaps: age bracket → restricted work_mode distribution.
# Replaces the previous "draw work_mode independently of age" behavior that
# allowed 5-year-old commuters and 94-year-old shift workers.
def _work_mode_distribution_for_age(
    age: int, base_dist: dict,
) -> dict:
    """Clamp work_mode distribution by age bracket.

    Uses WorkMode Literal values only (commute/remote/shift/nonworking).
    "Student" / "retired" / "part_time" semantics are encoded via the
    occupation field, not work_mode.

    Returns a new dict suitable for _weighted_pick.
    """
    bracket = _age_bracket(age)
    if bracket == "<16":
        return {"nonworking": 1.0}
    if bracket == "16-21":
        # Mostly students (nonworking) + some part-time (shift) + few commute
        return {"nonworking": 0.60, "shift": 0.25, "commute": 0.15}
    if bracket == "65-74":
        # Mostly retired (nonworking) + occasional part-time (shift / remote)
        return {"nonworking": 0.75, "shift": 0.15, "remote": 0.10}
    if bracket == ">=75":
        return {"nonworking": 1.0}
    # 22-64 keeps the base profile distribution
    return base_dist


# fix-realism-systemic-gaps: occupation → workplace building_type set, used
# by sample_population to pick a workplace that matches the agent's role
# (e.g. teacher → school, nurse → hospital, engineer → office).
_OCCUPATION_TO_WORKPLACE_TYPES: dict[str, tuple[str, ...]] = {
    "teacher": ("school",),
    "tutor": ("school", "community"),
    "nurse": ("hospital",),
    "doctor": ("hospital",),
    "software_dev": ("office",),
    "engineer": ("office", "commercial"),
    "designer": ("office",),
    "writer": ("office",),  # remote agents have no workplace anyway
    "manager": ("office", "commercial"),
    "consultant": ("office",),
    "analyst": ("office",),
    "marketer": ("office", "commercial"),
    "accountant": ("office",),
    "lawyer": ("office",),
    "retail_worker": ("shop", "commercial"),
    "barista": ("cafe", "restaurant"),  # POI workers — workplace=None
    "hospitality": ("hotel", "restaurant", "cafe"),
    "construction": ("commercial",),
    "tradesperson": ("commercial",),
    "warehouse": ("commercial", "industrial"),
    "security_guard": ("commercial", "office"),
    "volunteer_coordinator": ("community",),
}


def _pick_workplace_near(
    home_id: str,
    work_pool: tuple[str, ...],
    occupation: str,
    atlas,
    max_m: float,
    rng: random.Random,
) -> str | None:
    """Pick a workplace matching occupation type within commute radius.

    Returns None when the occupation is POI-based (barista / hospitality)
    so the agent acts as a roving POI worker without a fixed workplace.

    Fallback chain:
    1. Occupation-typed workplaces within max_m → random.choice from closest 60%
    2. Occupation-typed workplaces beyond max_m → closest 5
    3. Any workplace in pool → closest 5
    4. None
    """
    if atlas is None:
        return rng.choice(work_pool) if work_pool else None

    target_types = _OCCUPATION_TO_WORKPLACE_TYPES.get(
        occupation, ("commercial", "office"),
    )

    # POI-based occupations: cafe/restaurant aren't in work_pool, return None
    # so build_scripted_plan treats the agent as roving (no commute pair)
    if target_types and all(
        t in ("cafe", "restaurant", "bar", "hotel") for t in target_types
    ):
        return None

    home_c = atlas.get_center(home_id)
    if home_c is None:
        return rng.choice(work_pool) if work_pool else None

    typed_within: list[tuple[float, str]] = []
    typed_outside: list[tuple[float, str]] = []
    typed_seen = False
    for wid in work_pool:
        b = atlas.get_building(wid)
        if b is None:
            continue
        wc = atlas.get_center(wid)
        if wc is None:
            continue
        d = ((wc.x - home_c.x) ** 2 + (wc.y - home_c.y) ** 2) ** 0.5
        if b.building_type in target_types:
            typed_seen = True
            if d <= max_m:
                typed_within.append((d, wid))
            else:
                typed_outside.append((d, wid))

    if typed_within:
        typed_within.sort()
        # Pick from the closest 60% to avoid always-pick-closest determinism
        n = max(1, int(len(typed_within) * 0.6))
        return rng.choice([wid for _, wid in typed_within[:n]])

    if typed_outside:
        typed_outside.sort()
        return rng.choice([wid for _, wid in typed_outside[:5]])

    # Final fallback: any workplace in pool, closest 5
    all_with_d = []
    for wid in work_pool:
        wc = atlas.get_center(wid)
        if wc is None:
            continue
        d = ((wc.x - home_c.x) ** 2 + (wc.y - home_c.y) ** 2) ** 0.5
        all_with_d.append((d, wid))
    all_with_d.sort()
    if all_with_d:
        return rng.choice([wid for _, wid in all_with_d[:5]])
    return None


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
        # B1 fix: ABS 2021 captured Sydney during Delta lockdown (remote=53%
        # COVID anomaly). Steady-state Lane Cove ~18% remote per pre-2020
        # surveys; use steady-state for publishable thesis to avoid lockdown
        # confound. Publishable report SHALL disclose this de-anomaly choice.
        "commute": 0.594,    # was 0.324 (kept low by COVID-counted remote)
        "remote": 0.180,     # was 0.527 (COVID anomaly)
        "shift": 0.127,      # 1-pp bump from absorbed commute
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
        # ABS 2021 Lane Cove SAL12275 actual proportions (not the 0%-placeholder
        # values used pre-2026-05-13). Lone person & group household are real
        # ~20% combined; prior values silently zero'd them out.
        "lone_person": 0.1903,
        "couple_no_kids": 0.2666,
        "couple_kids_under_15": 0.2200,  # ↓ from 0.4923 (was double-counted)
        "couple_kids_15plus": 0.1500,
        "one_parent_family": 0.0945,
        "group_household": 0.0480,
        "other": 0.0306,  # sum-fix
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


