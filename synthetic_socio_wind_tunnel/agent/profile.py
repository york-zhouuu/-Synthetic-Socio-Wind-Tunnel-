"""Agent 的静态身份和性格定义。模拟期间不变。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from synthetic_socio_wind_tunnel.attention.models import DigitalProfile

from .personality import PersonalityTraits


HousingTenure = Literal["owner_occupier", "renter", "public_housing"]
IncomeTier = Literal["low", "mid", "high"]
WorkMode = Literal["commute", "remote", "shift", "nonworking"]
Household = Literal["single", "couple", "family_with_kids"]
Gender = Literal["male", "female", "non_binary"]

# === agent-profile-enrich (2026-04-27): 13 thesis-direct ABS dimensions ===
# Tier 1 — thesis core (rooted vs floating)
CommunityTenure = Literal["new_<1yr", "recent_1_5yr", "established_5plus"]
CareHours = Literal["none", "1_14", "15_29", "30plus"]  # for unpaid_*_hours
DisabilityCare = Literal["none", "yes"]  # G25 binary
VolunteerStatus = Literal["volunteer", "non_volunteer"]
# Tier 2 — refinements
EnglishProficiency = Literal[
    "very_well", "well", "not_well", "not_at_all", "english_only",
]
FamilyComposition = Literal[
    "lone_person", "couple_no_kids", "couple_kids_under_15",
    "couple_kids_15plus", "one_parent_family", "group_household", "other",
]
DwellingStructure = Literal[
    "separate_house", "semi_detached", "flat_apartment", "other_dwelling",
]
VehiclesAtDwelling = Literal["0", "1", "2", "3plus"]
YearOfArrival = Literal[
    "pre_2000", "2000_2010", "2011_2015", "2016_2021", "australian_born",
]
# Tier 3 — completeness
IndigenousStatus = Literal["indigenous", "non_indigenous"]
DisabilityStatus = Literal["needs_assistance", "no_assistance"]
EducationLevel = Literal[
    "postgrad", "bachelor", "diploma", "year_12",
    "year_11_or_below", "no_qualification",
]
HouseholdRole = Literal["parent", "child", "partner", "lone"]


class LifePattern(BaseModel):
    """
    Per-agent sticky routine anchor (agent-realistic-routine, 2026-04-28).

    Sampled once at population creation; persists across the full sim run.
    `personality.routine_adherence` controls how often plan generation
    actually uses these preferences (vs exploring fresh destinations).
    """
    preferred_cafe: str | None = None
    preferred_leisure_park: str | None = None
    preferred_errand_destination: str | None = None
    morning_commute_minute: int = Field(default=30, ge=0, le=59)
    """Offset within the 7-9am rush window; gaussian-sampled (mean 30, std 12)."""
    evening_return_minute: int = Field(default=30, ge=0, le=59)
    """Offset within the 17-19pm return window."""
    weekend_outing_destination: str | None = None

    model_config = {"frozen": True}


class AgentProfile(BaseModel):
    """Agent 的静态身份和性格定义。模拟期间不变。"""

    # === 身份 ===
    agent_id: str
    name: str
    age: int
    occupation: str
    household: Household

    # === 居住 ===
    home_location: str  # 家的 location_id (初始值，可被 Life Pattern 更新)

    # === 工作地（fix-population-uses-typed-locations）===
    # 通勤/远程/班次的 agent SHALL 有 workplace（取自 LocationPools.work_pool）。
    # retired/unemployed/homemaker/not_working SHALL workplace=None。
    workplace: str | None = None

    # === 出行速度（add-walking-speed-budget）===
    # 由 vehicles_at_dwelling 推导。Orchestrator 用此值 × tick_minutes 决定
    # 每 tick 能走多远；NavigationService 用 prefer_driving 决定 route filter。
    walking_speed_m_per_min: float = 80.0  # 5 km/h default walking pace
    prefer_driving: bool = False           # 0-vehicle households stay on foot

    # === A2 / realism-household-coupling: household identity ===
    # Multiple agents sharing a household_id SHALL share the same home_location.
    # Default = "household_<agent_id>" (solo household) for backwards compat
    # with current population sampling (which assigns unique home_0000 etc.).
    household_id: str = ""  # Filled by sample_population; default empty (solo)
    household_role: HouseholdRole = "lone"

    # === 人格（typed-personality change 引入，替换 dict[str, float]）===
    personality: PersonalityTraits = Field(default_factory=PersonalityTraits)

    # === 社交偏好 ===
    preferred_social_size: int = 2  # 1=独处, 5=派对
    interests: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=lambda: ["mandarin"])

    # === 日常习惯 ===
    wake_time: str = "7:00"
    sleep_time: str = "23:00"

    # === LLM 配置 ===
    is_protagonist: bool = False
    base_model: str = "claude-haiku-4-5-20251001"

    # === ai-town port (agent-stack-aitown-port): identity / plan free-text ===
    # ai-town's `agent.identity` (~3-sentence persona prose) and `agent.plan`
    # (~1-sentence current goal) — fed verbatim into conversation prompts via
    # _agent_lines() in handle_generate_message. Frozen at population sampling.
    # Default None for scripted agents and backwards compat with existing
    # protagonists; population.sample_population fills them via LLM batch when
    # generate_identity=True.
    identity_text: str | None = None
    plan_text: str | None = None

    # === 结构性身份维度（realign-to-social-thesis）===
    ethnicity_group: str | None = None
    migration_tenure_years: float | None = Field(default=None, ge=0.0)
    housing_tenure: HousingTenure | None = None
    income_tier: IncomeTier | None = None
    work_mode: WorkMode | None = None
    # gender 加入用于 ABS Census calibration（agent-calibration change）。
    # 注：Planner / name generator 暂未使用此字段——name×gender 一致性
    # defer 到 stereotype-audit 或独立 change（见 calibration design Open Q5）。
    gender: Gender | None = None
    digital: DigitalProfile = Field(default_factory=DigitalProfile)

    # === agent-profile-enrich (2026-04-27): 13 thesis-direct ABS dimensions ===
    # All Optional, default None for backwards compat. Literal types defined above.
    # Tier 1 — thesis core (rooted vs floating)
    community_tenure_5yr: CommunityTenure | None = None
    unpaid_child_care_hours: CareHours | None = None
    unpaid_domestic_hours: CareHours | None = None
    unpaid_disability_care_hours: DisabilityCare | None = None
    volunteer_status: VolunteerStatus | None = None
    # Tier 2 — refinements
    english_proficiency: EnglishProficiency | None = None
    family_composition: FamilyComposition | None = None
    dwelling_structure: DwellingStructure | None = None
    vehicles_at_dwelling: VehiclesAtDwelling | None = None
    year_of_arrival_bucket: YearOfArrival | None = None
    # Tier 3 — completeness
    indigenous_status: IndigenousStatus | None = None
    disability_status: DisabilityStatus | None = None
    education_level: EducationLevel | None = None

    # === agent-realistic-routine (2026-04-28): per-agent sticky routine anchor
    life_pattern: LifePattern | None = None

    model_config = {"frozen": True, "extra": "forbid"}
    # extra="forbid" so that removed fields like personality_traits / personality_description
    # raise ValidationError if re-introduced — catches migration regressions.


def validate_against_atlas(profile: "AgentProfile", atlas) -> None:
    """Assert profile.home_location and workplace match atlas semantics.

    Raises ValueError on:
    - home_location is not a building OR not building_type == "residential"
    - workplace is not a building OR not in {office, school, commercial,
      community, hospital} (when non-None)
    """
    home = atlas.get_building(profile.home_location)
    if home is None:
        raise ValueError(
            f"home_location {profile.home_location!r} is not a building; "
            f"home_location MUST be a residential building"
        )
    if home.building_type != "residential":
        raise ValueError(
            f"home_location {profile.home_location!r} has type "
            f"{home.building_type!r}, MUST be residential"
        )

    if profile.workplace is not None:
        work = atlas.get_building(profile.workplace)
        if work is None:
            raise ValueError(
                f"workplace {profile.workplace!r} is not a building"
            )
        valid_work_types = {
            "commercial", "community", "hospital", "office", "school",
        }
        if work.building_type not in valid_work_types:
            raise ValueError(
                f"workplace {profile.workplace!r} has type "
                f"{work.building_type!r}, MUST be in {sorted(valid_work_types)}"
            )
