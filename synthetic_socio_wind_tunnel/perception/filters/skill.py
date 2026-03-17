"""Skill-based perception filters."""

from __future__ import annotations
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.perception.filters.base import Filter

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.perception.models import ObserverContext, Observation


class SkillFilter(Filter):
    """Filter based on observer skills and knowledge."""

    def apply(
        self,
        observation: "Observation",
        context: "ObserverContext",
    ) -> "Observation | None":
        """Apply skill-based interpretation."""
        # Investigators notice more
        if context.investigation_skill > 0.7:
            if observation.source_type == "item":
                observation.is_notable = True
                observation.tags.append("investigated")

        # Knowledge affects interpretation
        for fact in context.knowledge:
            if observation.source_id.lower() in fact.lower():
                observation.is_notable = True
                observation.tags.append("relevant_to_knowledge")

        # Guilt affects perception of evidence
        if context.guilt_level > 0.5:
            if "evidence" in observation.tags:
                observation.interpreted = f"{observation.raw} - evidence of my crime?"
                observation.is_notable = True

        # Suspicion highlights certain entities
        if observation.source_type == "entity":
            if observation.source_id in context.suspicions:
                observation.is_notable = True
                observation.tags.append("suspected")

        return observation
