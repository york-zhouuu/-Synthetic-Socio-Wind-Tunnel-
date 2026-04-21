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

    # === 结构性身份维度（realign-to-social-thesis）===
    ethnicity_group: str | None = None
    migration_tenure_years: float | None = Field(default=None, ge=0.0)
    housing_tenure: HousingTenure | None = None
    income_tier: IncomeTier | None = None
    work_mode: WorkMode | None = None
    digital: DigitalProfile = Field(default_factory=DigitalProfile)

    model_config = {"frozen": True, "extra": "forbid"}
    # extra="forbid" so that removed fields like personality_traits / personality_description
    # raise ValidationError if re-introduced — catches migration regressions.
