"""synthetic_socio_wind_tunnel.agent — Agent 自主决策系统。"""

from .intent import (
    ExamineIntent,
    Intent,
    LockIntent,
    MoveIntent,
    OpenDoorIntent,
    PickupIntent,
    UnlockIntent,
    WaitIntent,
)
from .personality import EmotionalState, PersonalityTraits, Skills
# NOTE: audit module is intentionally NOT re-exported from this package
# init — it would leak into sim hot path via `from agent import ...`.
# Import directly: `from synthetic_socio_wind_tunnel.agent.audit import ...`
# (see stereotype-audit spec; only `tools/run_stereotype_audit.py` imports it).
from .profile import (
    AgentProfile,
    Gender,
    Household,
    HousingTenure,
    IncomeTier,
    LifePattern,
    WorkMode,
)
from .scripted_plan import build_scripted_plan
from .planner import DailyPlan, LLMClient, PlanAction, PlanStep, Planner, SocialIntent
from .population import (
    LANE_COVE_PROFILE,
    DigitalParams,
    PersonalityParams,
    PopulationProfile,
    sample_population,
)
from .runtime import AgentRuntime

__all__ = [
    "AgentProfile",
    "AgentRuntime",
    "DailyPlan",
    "DigitalParams",
    "EmotionalState",
    "ExamineIntent",
    "Gender",
    "Household",
    "HousingTenure",
    "IncomeTier",
    "Intent",
    "LANE_COVE_PROFILE",
    "LifePattern",
    "LLMClient",
    "LockIntent",
    "MoveIntent",
    "OpenDoorIntent",
    "PersonalityParams",
    "PersonalityTraits",
    "PickupIntent",
    "PlanAction",
    "PlanStep",
    "Planner",
    "PopulationProfile",
    "Skills",
    "SocialIntent",
    "UnlockIntent",
    "WaitIntent",
    "WorkMode",
    "build_scripted_plan",
    "sample_population",
]
