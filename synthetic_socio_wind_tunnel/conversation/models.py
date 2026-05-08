"""Information / Propagation / ShareEvent — value objects for conversation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


_VALID_CATEGORIES = ("push", "observation", "rumor")


@dataclass(frozen=True)
class Information:
    """A unit of information that can propagate through agent encounters.

    `salience` ∈ [0, 1] is the "worth-mentioning" coefficient — hyperlocal
    news ≈ 0.8, commercial push ≈ 0.5, global news ≈ 0.3. Higher salience
    yields a higher per-encounter share probability.
    """

    info_id: str
    content: str
    category: Literal["push", "observation", "rumor"]
    salience: float
    origin_tick: int
    origin_agent_id: str
    origin_day_index: int
    source_feed_item_id: str | None = None
    source_location_id: str | None = None
    # push-content-individualization：原 push 的目标受众类型（透传自
    # FeedItem.target_audience_tags），metric 层用它计 target_precision
    target_audience_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.category not in _VALID_CATEGORIES:
            raise ValueError(
                f"category must be one of {_VALID_CATEGORIES}, got {self.category!r}"
            )
        if not (0.0 <= self.salience <= 1.0):
            raise ValueError(
                f"salience must be in [0, 1], got {self.salience}"
            )


@dataclass(frozen=True)
class Propagation:
    """Aggregated view of how far a single Information has spread.

    Constructed by `ConversationService.get_propagation(info_id)`; not
    intended to be built directly by callers.
    """

    info_id: str
    reach: int                  # number of agents who know it (incl. origin)
    max_hops: int               # longest hop distance from origin
    mean_hops: float            # average over all known agents
    known_at: dict[str, int] = field(default_factory=dict)  # agent_id → first_learned_tick
    hops_at: dict[str, int] = field(default_factory=dict)   # agent_id → hops_at_learn


@dataclass(frozen=True)
class ShareEvent:
    """One info propagation event from sender → receiver in a single tick."""

    info_id: str
    from_agent: str
    to_agent: str
    tick: int
    receiver_hops: int   # hops_at_learn for receiver = sender_hops + 1
