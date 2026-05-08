"""PushTemplate + PushPersonalizer (push-content-individualization).

Per-recipient personalized push content + relevance scoring. Used by
HyperlocalPushVariant to generate individualized FeedItems sharing the
same topic_id (so conversation can still aggregate them as one logical
Information).

V1: rule-based audience tag → string lookup, no LLM. See change
proposal for thesis motivation.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from synthetic_socio_wind_tunnel.attention.models import FeedItem, FeedSource

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.profile import AgentProfile


# 5 audience tags (design D3); covers most ABS Lane Cove profiles
AudienceTag = Literal["parents", "young_adult", "elderly", "newcomer", "default"]
ALL_AUDIENCE_TAGS: tuple[str, ...] = (
    "parents", "young_adult", "elderly", "newcomer", "default",
)


class PushTemplate(BaseModel):
    """A parametric hyperlocal push, with audience-aware content variants."""

    model_config = ConfigDict(frozen=True)

    template_id: str
    topic_id: str  # cross-recipient shared key for conversation aggregation
    base_content: str  # legacy / fallback if audience_variants miss
    audience_variants: dict[str, str]  # audience_tag → content string
    target_audience_tags: tuple[str, ...]  # design intent: who should hear it
    base_salience: float = Field(ge=0.0, le=1.0)

    @field_validator("audience_variants")
    @classmethod
    def _has_default_variant(cls, v: dict[str, str]) -> dict[str, str]:
        if "default" not in v:
            raise ValueError(
                "PushTemplate.audience_variants must contain 'default' key as fallback"
            )
        return v

    @field_validator("target_audience_tags")
    @classmethod
    def _target_tags_nonempty(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError(
                "PushTemplate.target_audience_tags must be non-empty "
                "(design risk R2: empty tags would make every recipient 'default'-relevant)"
            )
        return v


class PushPersonalizer:
    """Profile → personalized FeedItem + relevance score.

    Stateless service. All computation is pure on (profile, template).
    """

    @staticmethod
    def audience_tag_for(profile: "AgentProfile") -> str:
        """Map a profile to one of 5 audience tags (design D3)."""
        if profile.family_composition == "couple_kids_under_15":
            return "parents"
        if profile.community_tenure_5yr == "new_<1yr":
            return "newcomer"
        if (profile.age >= 65) or (profile.community_tenure_5yr == "established_5plus"):
            return "elderly"
        if (profile.age < 30) and (profile.household == "single"):
            return "young_adult"
        return "default"

    @classmethod
    def relevance(
        cls, profile: "AgentProfile", template: PushTemplate,
    ) -> float:
        """3-tier relevance (design D4): match=1.0, default=0.6, mismatch=0.3."""
        tag = cls.audience_tag_for(profile)
        if tag in template.target_audience_tags:
            return 1.0
        if tag == "default":
            return 0.6
        return 0.3

    @classmethod
    def personalize(
        cls,
        template: PushTemplate,
        profile: "AgentProfile",
        *,
        location: str,
        feed_item_id: str,
        created_at: datetime,
        source: FeedSource = "local_news",
        base_urgency: float = 0.6,
        hyperlocal_radius_m: float | None = 500.0,
        origin_hack_id: str | None = None,
    ) -> tuple[FeedItem, float]:
        """Render a personalized FeedItem for `profile` from `template`.

        Returns (FeedItem, relevance). Caller (variant) typically
        injects this into AttentionService for a single recipient.
        """
        tag = cls.audience_tag_for(profile)
        # Pick variant content; fall back to "default" if tag absent
        content_template = template.audience_variants.get(
            tag, template.audience_variants["default"],
        )
        content = content_template.replace("{location}", str(location))
        rel = cls.relevance(profile, template)
        # urgency = base × (0.5 + 0.5 × relevance), clamp to [0, 1]
        urgency = max(0.0, min(1.0, base_urgency * (0.5 + 0.5 * rel)))

        item = FeedItem(
            feed_item_id=feed_item_id,
            content=content,
            source=source,
            hyperlocal_radius=hyperlocal_radius_m,
            category="event",
            urgency=urgency,
            created_at=created_at,
            origin_hack_id=origin_hack_id,
            topic_id=template.topic_id,
            target_audience_tags=template.target_audience_tags,
        )
        return item, rel


__all__ = [
    "ALL_AUDIENCE_TAGS",
    "AudienceTag",
    "PushPersonalizer",
    "PushTemplate",
]
