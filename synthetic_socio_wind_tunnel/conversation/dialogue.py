"""
Dialogue — bilateral LLM-driven conversation (ai-town port).

Reference: convex/aiTown/conversation.ts:15-225 + convex/aiTown/conversationMembership.ts.

State machine (ai-town verbatim, simplified for 5-min ticks):

    initiator: walking_over     +    invitee: invited
                ↓ accept_invite                ↓
    initiator: walking_over     +    invitee: walking_over
                            ↓ both_at_target
                            participating
                            ↓ leave / max_messages / timeout
                                ended

Differences from ai-town (5-min tick adaptations):
- No isTyping mutex (single tick = single message)
- Walking_over → participating uses location_id equality (not Euclidean distance)
- Conversation lasts at most max_messages (8) or max_duration_minutes (30)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


DialogueStatus = Literal["invited", "walking_over", "participating", "ended"]
"""Per-dialogue overall status; for member-level status use Dialogue.member_status."""


@dataclass(frozen=True)
class DialogueMessage:
    """Single message in a dialogue. Frozen — once spoken, immutable."""

    message_id: str
    speaker_id: str
    content: str
    tick: int


@dataclass
class Dialogue:
    """Live or ended bilateral dialogue.

    Mutable (status / messages / ended_tick / end_reason can change). The
    invariants are enforced by `DialogueService` (no direct setattr by callers).

    Invariants (verified by service):
    - `initiator_id != invitee_id`
    - `member_status[initiator]` and `member_status[invitee]` always present
    - `status` reflects "joint" state: any member in earlier state → dialogue
      in earlier state; both must agree to advance
    """

    dialogue_id: str
    initiator_id: str
    invitee_id: str
    target_location_id: str
    started_tick: int
    last_message_tick: int
    started_at: "datetime | None" = None  # simulated wall time at start
    member_status: dict[str, DialogueStatus] = field(default_factory=dict)
    messages: list[DialogueMessage] = field(default_factory=list)
    ended_tick: int | None = None
    end_reason: str | None = None

    def __post_init__(self) -> None:
        if self.initiator_id == self.invitee_id:
            raise ValueError(
                f"Cannot dialogue with self (both initiator and invitee = "
                f"{self.initiator_id!r})"
            )

    @property
    def participants(self) -> tuple[str, str]:
        """Canonical (initiator, invitee) tuple."""
        return (self.initiator_id, self.invitee_id)

    @property
    def status(self) -> DialogueStatus:
        """Joint dialogue state — derived from member_status.

        - Either ended → ended
        - Both invited / walking_over / participating → that state
        - Mixed walking_over + invited → walking_over (initiator already moved)
        - Otherwise → invited
        """
        if self.ended_tick is not None:
            return "ended"
        s = list(self.member_status.values())
        if not s:
            return "invited"
        if all(x == "participating" for x in s):
            return "participating"
        if all(x == "walking_over" for x in s):
            return "walking_over"
        if "walking_over" in s:
            return "walking_over"
        return "invited"

    def other_participant(self, agent_id: str) -> str:
        """Return the other participant's id, or raise if `agent_id` not in this dialogue."""
        if agent_id == self.initiator_id:
            return self.invitee_id
        if agent_id == self.invitee_id:
            return self.initiator_id
        raise ValueError(f"agent {agent_id!r} not in dialogue {self.dialogue_id!r}")

    def has_participant(self, agent_id: str) -> bool:
        return agent_id == self.initiator_id or agent_id == self.invitee_id

    def message_count(self) -> int:
        return len(self.messages)


__all__ = [
    "Dialogue",
    "DialogueMessage",
    "DialogueStatus",
]
