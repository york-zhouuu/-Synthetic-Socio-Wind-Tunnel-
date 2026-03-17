"""
CollapseService - The Schrödinger Engine (薛定谔引擎)

Handles lazy detail generation:
- Container contents
- Location details
- Environmental descriptions

Details don't exist until observed. When examined:
1. Check if detail already exists in Ledger
2. If not, generate via callback and store
3. Return the (now permanent) detail

Respects:
- Spatial Budget: Container capacity limits from Atlas
- Evidence Blueprints: Plot-required evidence from Ledger
- Director Context: Narrative atmosphere guidance (v0.4.0)

Reads: Atlas (for context, capacity), Ledger (for existing details, evidence)
Writes: Ledger (new generated details, container states)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Protocol

from synthetic_socio_wind_tunnel.ledger.models import GeneratedDetail, ItemState

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.atlas import Atlas
    from synthetic_socio_wind_tunnel.atlas.models import ContainerDef
    from synthetic_socio_wind_tunnel.ledger import Ledger
    from synthetic_socio_wind_tunnel.ledger.models import EvidenceBlueprint


@dataclass
class DirectorContext:
    """
    导演意图上下文 - 控制生成内容的氛围和风格

    这是"导演 Agent"传递给坍缩服务的指令，用于：
    1. 控制生成内容的情绪基调
    2. 暗示应该出现的元素类型
    3. 约束不应该出现的内容

    设计为非结构化文本友好，因为导演 Agent 背后是 LLM。
    """

    # 叙事氛围 (自由文本，LLM 友好)
    narrative_hint: str = ""
    # 例如: "这是高潮前的紧张时刻，Emma 即将发现关键证据"
    # 例如: "轻松的日常场景，角色在咖啡馆闲聊"
    # 例如: "暴风雨之夜，图书馆里弥漫着不安的气氛"

    # 情绪基调 (可选的结构化字段)
    mood: str = "neutral"  # "tense", "relaxed", "mysterious", "urgent", "melancholic"
    tension_level: float = 0.5  # 0.0 (平静) - 1.0 (高潮)

    # 生成提示
    should_include: list[str] = field(default_factory=list)
    # 例如: ["带血的物品", "隐藏的信件", "可疑的痕迹"]

    should_avoid: list[str] = field(default_factory=list)
    # 例如: ["直接揭示凶手", "过于明显的线索"]

    # 风格指导
    detail_level: str = "normal"  # "minimal", "normal", "rich"
    writing_style: str = ""  # 自由文本风格指导
    # 例如: "使用短句，营造紧迫感"
    # 例如: "细腻描写感官细节"

    # 剧情阶段
    story_phase: str = ""  # "setup", "rising_action", "climax", "falling_action", "resolution"

    # 额外的自由文本指令 (最灵活的字段)
    director_notes: str = ""
    # 例如: "这个抽屉里应该有一封信，信的内容暗示 Linda 和受害者的关系，
    #        但不要直接说明她是凶手。信纸应该有咖啡渍，暗示是在 Betty's Cafe 写的。"

    def to_prompt_context(self) -> str:
        """转换为可以直接嵌入 LLM prompt 的文本"""
        parts = []

        if self.narrative_hint:
            parts.append(f"场景氛围: {self.narrative_hint}")

        if self.mood != "neutral":
            parts.append(f"情绪基调: {self.mood}")

        if self.tension_level > 0.7:
            parts.append(f"紧张程度: 高 ({self.tension_level:.1f})")
        elif self.tension_level < 0.3:
            parts.append(f"紧张程度: 低 ({self.tension_level:.1f})")

        if self.should_include:
            parts.append(f"应包含元素: {', '.join(self.should_include)}")

        if self.should_avoid:
            parts.append(f"应避免元素: {', '.join(self.should_avoid)}")

        if self.writing_style:
            parts.append(f"写作风格: {self.writing_style}")

        if self.story_phase:
            parts.append(f"剧情阶段: {self.story_phase}")

        if self.director_notes:
            parts.append(f"导演备注: {self.director_notes}")

        return "\n".join(parts) if parts else ""


@dataclass
class CollapseContext:
    """Context passed to detail generators."""
    target_id: str
    target_type: str  # "container", "location_detail", "item"
    examiner: str
    location_id: str | None = None
    location_name: str | None = None

    # Container-specific
    container_def: "ContainerDef | None" = None
    item_capacity: int = 5
    current_item_count: int = 0

    # Evidence constraints
    required_evidence: list["EvidenceBlueprint"] | None = None

    # Director context (v0.4.0)
    director: DirectorContext | None = None

    # Additional context
    extra: dict | None = None


class DetailGenerator(Protocol):
    """Protocol for detail generation callbacks."""

    def __call__(
        self,
        target_id: str,
        target_type: str,
        context: dict,
    ) -> str:
        """
        Generate detail content.

        Args:
            target_id: What is being examined
            target_type: "container", "location", "item"
            context: Additional context (location, examiner, etc.)

        Returns:
            Generated detail text
        """
        ...


def default_generator(target_id: str, target_type: str, context: dict) -> str:
    """Default placeholder generator."""
    # If there's required evidence, include it in placeholder
    evidence = context.get("required_evidence", [])
    if evidence:
        evidence_items = ", ".join(
            item for ev in evidence for item in ev.get("must_contain", [])
        )
        return f"[Generated {target_type} for {target_id}. Required items: {evidence_items}]"
    return f"[Generated {target_type} detail for {target_id}]"


class CollapseService:
    """
    Schrödinger detail generation service.

    Manages lazy loading of world details. Before observation,
    details exist in superposition. Upon examination, they
    "collapse" into a single permanent state.

    Now with:
    - Spatial Budget: Respects container capacity from Atlas
    - Evidence Blueprints: Ensures plot-required items appear

    Example:
        collapse = CollapseService(atlas, ledger, llm_generator)

        # First examination - generates and stores
        detail = collapse.examine_container("desk_drawer", "emma")
        # → "A crumpled receipt from Betty's Cafe dated last Tuesday..."

        # Second examination - returns stored detail
        detail = collapse.examine_container("desk_drawer", "bob")
        # → Same content (already collapsed)
    """

    __slots__ = ("_atlas", "_ledger", "_generator")

    def __init__(
        self,
        atlas: "Atlas",
        ledger: "Ledger",
        generator: DetailGenerator | None = None,
    ):
        """
        Initialize collapse service.

        Args:
            atlas: Read-only map data (for context)
            ledger: Read-write state (for storing details)
            generator: Callback for generating details (defaults to placeholder)
        """
        self._atlas = atlas
        self._ledger = ledger
        self._generator = generator or default_generator

    def set_generator(self, generator: DetailGenerator) -> None:
        """Replace the detail generator (e.g., switch to LLM)."""
        self._generator = generator

    # ========== Container Examination ==========

    def examine_container(
        self,
        container_id: str,
        examiner: str,
        location_id: str | None = None,
        examination_depth: float = 0.5,
        director: DirectorContext | None = None,
    ) -> str:
        """
        Examine a container, collapsing its contents.

        If contents haven't been generated, generates them while:
        - Respecting spatial budget (item_capacity from Atlas)
        - Including required evidence (EvidenceBlueprint from Ledger)
        - Following director guidance (DirectorContext)

        Args:
            container_id: The container being examined
            examiner: Who is examining
            location_id: Where the container is (for context)
            examination_depth: How thoroughly searched (0-1)
            director: Director context for narrative control (v0.4.0)

        Returns:
            The container's detail content
        """
        detail_id = f"container:{container_id}"

        # Record the examination
        self._ledger.record_examination(container_id, examiner, examination_depth)

        # Check if already collapsed
        if self._ledger.is_container_collapsed(container_id):
            existing = self._ledger.get_detail(detail_id)
            if existing:
                return existing.content

        # Get container definition from Atlas (for capacity)
        container_def = self._atlas.get_container_def(container_id)
        item_capacity = container_def.item_capacity if container_def else 5

        # Count existing items
        current_count = self._ledger.count_items_in(container_id)
        remaining_capacity = max(0, item_capacity - current_count)

        # Get required evidence for this container
        required_evidence = self._ledger.get_evidence_for_container(container_id)

        # Build context for generator
        context = {
            "examiner": examiner,
            "location_id": location_id,
            "container_id": container_id,
            "container_type": container_def.container_type if container_def else "unknown",
            "container_name": container_def.name if container_def else container_id,
            "item_capacity": item_capacity,
            "remaining_capacity": remaining_capacity,
            "examination_depth": examination_depth,
        }

        # Add location context
        if location_id:
            loc = self._atlas.get_location(location_id)
            if loc:
                context["location_name"] = loc.name

        # Add evidence blueprints
        if required_evidence:
            context["required_evidence"] = [
                {
                    "evidence_id": ev.evidence_id,
                    "must_contain": ev.must_contain,
                    "appearance_hints": ev.appearance_hints,
                    "forbidden_details": ev.forbidden_details,
                    "min_discovery_skill": ev.min_discovery_skill,
                }
                for ev in required_evidence
            ]
            context["_evidence_objects"] = required_evidence  # For post-processing

        # Add director context (v0.4.0)
        if director:
            context["director"] = {
                "narrative_hint": director.narrative_hint,
                "mood": director.mood,
                "tension_level": director.tension_level,
                "should_include": director.should_include,
                "should_avoid": director.should_avoid,
                "detail_level": director.detail_level,
                "writing_style": director.writing_style,
                "story_phase": director.story_phase,
                "director_notes": director.director_notes,
                # 便于 LLM 直接使用的文本版本
                "prompt_context": director.to_prompt_context(),
            }

        content = self._generator(container_id, "container", context)

        # Mark container as collapsed
        self._ledger.mark_container_collapsed(container_id, examiner)

        # Update evidence blueprints with generated descriptions
        for ev in required_evidence:
            ev.generated_description = content

        # Store the collapse
        detail = GeneratedDetail(
            detail_id=detail_id,
            target_id=container_id,
            content=content,
            generated_by=examiner,
            generated_at=self._ledger.current_time,
        )
        self._ledger.set_detail(detail)

        return content

    def get_container_capacity_info(self, container_id: str) -> dict:
        """Get capacity information for a container."""
        container_def = self._atlas.get_container_def(container_id)
        current_count = self._ledger.count_items_in(container_id)

        return {
            "container_id": container_id,
            "item_capacity": container_def.item_capacity if container_def else 5,
            "surface_capacity": container_def.surface_capacity if container_def else 3,
            "current_items": current_count,
            "remaining_capacity": (container_def.item_capacity if container_def else 5) - current_count,
            "is_collapsed": self._ledger.is_container_collapsed(container_id),
        }

    # ========== Location Detail ==========

    def examine_location_detail(
        self,
        location_id: str,
        detail_type: str,
        examiner: str,
    ) -> str:
        """
        Examine a specific detail of a location.

        Args:
            location_id: The location
            detail_type: Type of detail ("bookshelf", "window_view", "floor")
            examiner: Who is examining

        Returns:
            The detail content
        """
        detail_id = f"location:{location_id}:{detail_type}"

        existing = self._ledger.get_detail(detail_id)
        if existing:
            return existing.content

        # Gather context
        context = {
            "examiner": examiner,
            "location_id": location_id,
            "detail_type": detail_type,
        }

        loc = self._atlas.get_location(location_id)
        if loc:
            context["location_name"] = loc.name

        content = self._generator(f"{location_id}:{detail_type}", "location_detail", context)

        detail = GeneratedDetail(
            detail_id=detail_id,
            target_id=location_id,
            content=content,
            generated_by=examiner,
            generated_at=self._ledger.current_time,
        )
        self._ledger.set_detail(detail)

        return content

    # ========== Item Detail ==========

    def examine_item_detail(
        self,
        item_id: str,
        examiner: str,
    ) -> str:
        """
        Examine an item closely, generating details.

        Args:
            item_id: The item
            examiner: Who is examining

        Returns:
            Detailed description of the item
        """
        detail_id = f"item:{item_id}"

        existing = self._ledger.get_detail(detail_id)
        if existing:
            return existing.content

        item = self._ledger.get_item(item_id)
        context = {
            "examiner": examiner,
            "item_id": item_id,
            "item_name": item.name if item else item_id,
        }

        content = self._generator(item_id, "item", context)

        detail = GeneratedDetail(
            detail_id=detail_id,
            target_id=item_id,
            content=content,
            generated_by=examiner,
            generated_at=self._ledger.current_time,
        )
        self._ledger.set_detail(detail)

        return content

    # ========== Batch Operations ==========

    def get_all_details_for(self, target_id: str) -> list[GeneratedDetail]:
        """Get all generated details for a target."""
        return list(self._ledger.details_for(target_id))

    def has_been_examined(self, detail_id: str) -> bool:
        """Check if something has been examined (detail exists)."""
        return self._ledger.has_detail(detail_id)

    # ========== Utility ==========

    def preview_collapse(
        self,
        target_id: str,
        target_type: str,
        context: dict,
    ) -> str:
        """
        Preview what would be generated WITHOUT storing.

        Useful for debugging or preview features.
        """
        return self._generator(target_id, target_type, context)

    def get_room_spatial_budget(self, room_id: str) -> dict | None:
        """
        Get spatial budget summary for a room.

        Returns container capacities and current usage.
        """
        room = self._atlas.get_room(room_id)
        if not room:
            return None

        containers_info = {}
        total_capacity = 0
        total_used = 0

        for container_id, container_def in room.containers.items():
            current = self._ledger.count_items_in(container_id)
            containers_info[container_id] = {
                "name": container_def.name,
                "type": container_def.container_type,
                "capacity": container_def.item_capacity,
                "used": current,
                "collapsed": self._ledger.is_container_collapsed(container_id),
            }
            total_capacity += container_def.item_capacity
            total_used += current

        return {
            "room_id": room_id,
            "room_name": room.name,
            "total_capacity": total_capacity,
            "total_used": total_used,
            "containers": containers_info,
        }
