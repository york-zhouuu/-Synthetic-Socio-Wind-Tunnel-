"""
Perception Data Models - Subjective experience structures.

These models define HOW characters perceive the world.
The same objective reality appears different through different lenses.

Key insight: Perception is NOT just filtering visibility.
It's about interpretation based on knowledge, skills, and emotions.

v0.4.0: Added snapshot objects for entities/items (not just IDs)
"""

from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field

from synthetic_socio_wind_tunnel.atlas.models import Coord


class SenseType(str, Enum):
    """Types of sensory perception."""
    VISUAL = "visual"
    AUDITORY = "auditory"
    OLFACTORY = "olfactory"


# ========== Snapshot Models (v0.4.0) ==========

class EntitySnapshot(BaseModel):
    """
    实体快照 - 观察者看到的实体状态

    不是完整的 EntityState，而是观察者能感知到的信息。
    避免 Agent 需要二次查询。
    """
    entity_id: str
    name: str = ""  # 显示名称
    location_id: str
    activity: str | None = None  # 正在做什么
    posture: str = "standing"  # "standing", "sitting", "lying", "crouching"
    facing_direction: str | None = None  # 面朝方向
    visible_items: list[str] = Field(default_factory=list)  # 可见的持有物品
    apparent_mood: str | None = None  # 表面情绪 (观察者的判断)
    distance: float = 0.0  # 与观察者的距离
    is_familiar: bool = False  # 观察者是否认识此人


class ItemSnapshot(BaseModel):
    """
    物品快照 - 观察者看到的物品状态

    包含物品的可见属性，避免二次查询。
    """
    item_id: str
    name: str
    location_type: str = "floor"  # "floor", "surface", "container", "held"
    container_id: str | None = None  # 如果在容器中
    holder_id: str | None = None  # 如果被持有
    position_description: str = ""  # "在桌子上", "在地板角落"
    visible_state: str = ""  # "打开的", "破损的", "沾有污渍的"
    is_notable: bool = False  # 是否引人注目
    distance: float = 0.0


class ContainerSnapshot(BaseModel):
    """
    容器快照 - 观察者看到的容器状态
    """
    container_id: str
    name: str
    container_type: str
    is_open: bool = False
    is_locked: bool = False
    visible_contents: list[str] = Field(default_factory=list)  # 可见的内容物 (如果打开)
    surface_items: list[str] = Field(default_factory=list)  # 表面物品
    is_collapsed: bool = False  # 是否已坍缩


class ClueSnapshot(BaseModel):
    """
    线索快照 - 观察者发现的线索
    """
    clue_id: str
    description: str = ""  # 线索的外观描述
    location_description: str = ""  # 在哪里发现的
    is_new: bool = True  # 是否是新发现的
    significance: str = "normal"  # "minor", "normal", "major", "critical"


# ========== Observer Context ==========

class ObserverContext(BaseModel):
    """
    Who is observing and how.

    This captures everything about the observer that affects perception:
    - Physical: position, sensory capabilities
    - Mental: skills, knowledge, suspicions
    - Emotional: guilt, anxiety, curiosity

    Different contexts produce different SubjectiveViews.
    """
    entity_id: str
    position: Coord
    location_id: str | None = None  # Current location (room/area ID)

    # Capabilities
    skills: dict[str, float] = Field(default_factory=dict)
    # Common skills: "investigation", "perception", "stealth"

    # Knowledge
    knowledge: list[str] = Field(default_factory=list)  # Known facts
    suspicions: list[str] = Field(default_factory=list)  # Suspected entities
    secrets: list[str] = Field(default_factory=list)  # Own secrets

    # Emotional state
    emotional_state: dict[str, float] = Field(default_factory=dict)
    # Common: "guilt", "anxiety", "curiosity", "fear"

    # Focus
    looking_for: list[str] = Field(default_factory=list)  # Active search targets
    attention: float = 0.5  # 0-1, how carefully looking

    # Impairments
    vision_impaired: bool = False
    hearing_impaired: bool = False

    def get_skill(self, skill: str, default: float = 0.5) -> float:
        """Get skill level with default."""
        return self.skills.get(skill, default)

    def get_emotion(self, emotion: str, default: float = 0.0) -> float:
        """Get emotion level with default."""
        return self.emotional_state.get(emotion, default)

    @property
    def investigation_skill(self) -> float:
        return self.get_skill("investigation")

    @property
    def perception_skill(self) -> float:
        return self.get_skill("perception")

    @property
    def guilt_level(self) -> float:
        return self.get_emotion("guilt")

    @property
    def anxiety_level(self) -> float:
        return self.get_emotion("anxiety")


class AgentProfile(BaseModel):
    """
    Agent background identity for social perception filtering.

    Distinct from ObserverContext (which captures real-time sensory state),
    AgentProfile captures the stable socio-cultural identity that shapes
    how an agent reads and interprets social spaces.

    Same physical location → same SocialProfile → different AgentProfile
    → different comfort/belonging/exclusion experience.
    """
    agent_id: str
    name: str
    age_group: str = "adult"          # "elderly", "adult", "youth"
    class_background: str = "middle"  # "working_class", "middle", "upper_middle"
    languages: tuple[str, ...] = ("English",)
    income_level: str = "mid"         # "low", "mid", "high"
    home_side: str = "none"           # "old", "new", "both", "none"
    social_groups: tuple[str, ...] = ()


class Observation(BaseModel):
    """A single sensory observation."""
    sense: SenseType
    source_id: str
    source_type: str  # "entity", "item", "container", "environment", "ambient"
    source_location: str | None = None  # Where the source is (for cross-room perception)
    confidence: float = 1.0  # 0-1, how sure
    distance: float = 0.0
    raw: str = ""  # Objective description
    interpreted: str = ""  # Subjective interpretation
    is_notable: bool = False  # Stands out to this observer
    tags: list[str] = Field(default_factory=list)


class SubjectiveView(BaseModel):
    """
    The complete subjective perception of a location.

    This is the OUTPUT of the perception pipeline.
    Same location + different observers = different views.

    The Rashomon effect in data form.

    v0.4.0: Added snapshot objects (entities, items, containers, clues)
            for Agent-friendly access without secondary queries.
    """
    observer_id: str
    location_id: str
    location_name: str

    # What was perceived
    observations: list[Observation] = Field(default_factory=list)

    # === Legacy ID lists (保持向后兼容) ===
    entities_seen: list[str] = Field(default_factory=list)
    items_noticed: list[str] = Field(default_factory=list)
    clues_found: list[str] = Field(default_factory=list)

    # === Snapshot objects (v0.4.0 新增) ===
    # Agent 可以直接使用这些对象，无需二次查询
    entity_snapshots: list[EntitySnapshot] = Field(default_factory=list)
    item_snapshots: list[ItemSnapshot] = Field(default_factory=list)
    container_snapshots: list[ContainerSnapshot] = Field(default_factory=list)
    clue_snapshots: list[ClueSnapshot] = Field(default_factory=list)

    # Environment
    lighting: str = "normal"  # "dark", "dim", "normal", "bright"
    ambient_sounds: list[str] = Field(default_factory=list)
    ambient_smells: list[str] = Field(default_factory=list)

    # The rendered narrative
    narrative: str = ""

    # Metadata
    timestamp: str = ""
    weather: str = "clear"

    def get_observations_by_type(self, source_type: str) -> list[Observation]:
        """Filter observations by source type."""
        return [o for o in self.observations if o.source_type == source_type]

    def get_notable_observations(self) -> list[Observation]:
        """Get observations marked as notable."""
        return [o for o in self.observations if o.is_notable]

    # === Snapshot accessors (v0.4.0) ===

    def get_entity(self, entity_id: str) -> EntitySnapshot | None:
        """Get entity snapshot by ID."""
        for e in self.entity_snapshots:
            if e.entity_id == entity_id:
                return e
        return None

    def get_item(self, item_id: str) -> ItemSnapshot | None:
        """Get item snapshot by ID."""
        for i in self.item_snapshots:
            if i.item_id == item_id:
                return i
        return None

    def get_container(self, container_id: str) -> ContainerSnapshot | None:
        """Get container snapshot by ID."""
        for c in self.container_snapshots:
            if c.container_id == container_id:
                return c
        return None

    def get_nearby_entities(self, max_distance: float = 5.0) -> list[EntitySnapshot]:
        """Get entities within distance."""
        return [e for e in self.entity_snapshots if e.distance <= max_distance]

    def get_notable_items(self) -> list[ItemSnapshot]:
        """Get items marked as notable."""
        return [i for i in self.item_snapshots if i.is_notable]
