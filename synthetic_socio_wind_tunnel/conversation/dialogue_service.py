"""
DialogueService — state machine for bilateral LLM dialogues.

Ports ai-town's Conversation.start() / acceptInvite() / rejectInvite() /
tick() / leave() / stop() into a service-style API. Replaces ai-town's
in-world container model (game.world.conversations Map) with a single
DialogueService instance — matches SSWT's per-entity state philosophy.

Per design D8 + D3:
- 2-participant only (V1; 3+ groups → V2)
- Status transitions enforced (no participating → invited rollback)
- Same-pair cooldown (24 simulated hours) blocks repeat invites
- Auto-end on max_messages (8) or max_duration_minutes (30) — ai-town's
  ACTION_TIMEOUT analog adapted to 5-min tick scale
"""

from __future__ import annotations

import logging
import random
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.conversation.dialogue import (
    Dialogue,
    DialogueMessage,
    DialogueStatus,
)

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.conversation.service import ConversationService
    from synthetic_socio_wind_tunnel.memory.service import MemoryService
    from synthetic_socio_wind_tunnel.social_graph import SocialGraphService


logger = logging.getLogger(__name__)


# Ported defaults (ai-town: aiTown/constants.ts).
DEFAULT_MAX_MESSAGES = 8
DEFAULT_MAX_DURATION_MINUTES = 30
# Same-pair cooldown — ai-town has an implicit cooldown via lastConversation;
# we make it explicit. 24 simulated hours = "yesterday" rule of thumb.
DEFAULT_COOLDOWN_MINUTES = 24 * 60


class DialogueAlreadyExistsError(RuntimeError):
    """Caller tried to schedule a dialogue while one of the agents is busy."""


class DialogueCooldownError(RuntimeError):
    """Caller tried to schedule a dialogue within cooldown of last ended one."""


class InvalidDialogueStateError(RuntimeError):
    """Operation incompatible with dialogue's current status."""


class DialogueService:
    """Per-run dialogue state machine.

    Single-process, in-memory. Seeded RNG for invite-accept stochasticity
    so dialog outcomes are reproducible per (seed, tick, agent pair).
    """

    __slots__ = (
        "_dialogues",
        "_active_by_agent",
        "_cooldown_minutes",
        "_max_messages",
        "_max_duration_minutes",
        "_rng",
        "_message_counter",
        "_last_ended_at",
        "_bridged",
    )

    def __init__(
        self,
        *,
        seed: int | None = None,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        max_duration_minutes: int = DEFAULT_MAX_DURATION_MINUTES,
        cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
    ) -> None:
        self._dialogues: dict[str, Dialogue] = {}
        self._active_by_agent: dict[str, str] = {}  # agent_id → dialogue_id
        self._cooldown_minutes = cooldown_minutes
        self._max_messages = max_messages
        self._max_duration_minutes = max_duration_minutes
        self._rng = random.Random(seed) if seed is not None else random.Random()
        self._message_counter: int = 0
        # canonical pair (sorted tuple) → datetime when last dialogue ended
        self._last_ended_at: dict[tuple[str, str], datetime] = {}
        # idempotency: dialogue_ids already bridged to memory/propagation/graph
        self._bridged: set[str] = set()

    # -- creation -----------------------------------------------------

    def schedule_invite(
        self,
        initiator_id: str,
        invitee_id: str,
        target_location_id: str,
        *,
        tick: int,
        simulated_time: datetime,
        force: bool = False,
    ) -> Dialogue:
        """Initiate a dialogue. Both agents become busy (active_by_agent).

        Status: initiator → walking_over (already moving), invitee → invited.

        Raises:
        - DialogueAlreadyExistsError if either agent already in active dialogue
        - DialogueCooldownError if the pair just ended a dialogue (unless force=True)
        - ValueError if initiator_id == invitee_id
        """
        if initiator_id == invitee_id:
            raise ValueError("Cannot schedule a dialogue with self")

        if initiator_id in self._active_by_agent:
            raise DialogueAlreadyExistsError(
                f"agent {initiator_id} already in dialogue "
                f"{self._active_by_agent[initiator_id]}"
            )
        if invitee_id in self._active_by_agent:
            raise DialogueAlreadyExistsError(
                f"agent {invitee_id} already in dialogue "
                f"{self._active_by_agent[invitee_id]}"
            )

        if not force:
            pair = self._canonical_pair(initiator_id, invitee_id)
            ended = self._last_ended_at.get(pair)
            if ended is not None:
                elapsed = (simulated_time - ended).total_seconds() / 60.0
                if elapsed < self._cooldown_minutes:
                    raise DialogueCooldownError(
                        f"pair {pair} ended dialogue {elapsed:.0f} min ago; "
                        f"cooldown {self._cooldown_minutes} min"
                    )

        dialogue_id = self._next_dialogue_id(initiator_id, invitee_id, tick)
        d = Dialogue(
            dialogue_id=dialogue_id,
            initiator_id=initiator_id,
            invitee_id=invitee_id,
            target_location_id=target_location_id,
            started_tick=tick,
            last_message_tick=tick,
            started_at=simulated_time,
            member_status={
                initiator_id: "walking_over",
                invitee_id: "invited",
            },
        )
        self._dialogues[dialogue_id] = d
        self._active_by_agent[initiator_id] = dialogue_id
        self._active_by_agent[invitee_id] = dialogue_id
        return d

    def accept_invite(self, dialogue_id: str, agent_id: str) -> Dialogue:
        """Invitee accepts → both walking_over."""
        d = self._require(dialogue_id)
        if d.member_status.get(agent_id) != "invited":
            raise InvalidDialogueStateError(
                f"agent {agent_id} not in 'invited' status for {dialogue_id}; "
                f"got {d.member_status.get(agent_id)!r}"
            )
        d.member_status[agent_id] = "walking_over"
        return d

    def reject_invite(self, dialogue_id: str, agent_id: str, reason: str,
                      *, tick: int, simulated_time: datetime) -> Dialogue:
        """Invitee rejects → dialogue ends (similar to ai-town's stop on reject)."""
        d = self._require(dialogue_id)
        if d.member_status.get(agent_id) != "invited":
            raise InvalidDialogueStateError(
                f"reject in wrong status for {agent_id}: "
                f"{d.member_status.get(agent_id)!r}"
            )
        return self._end(d, end_reason=f"rejected:{reason}",
                         tick=tick, simulated_time=simulated_time)

    # -- transitions --------------------------------------------------

    def advance_to_participating(
        self, dialogue_id: str, *, tick: int,
    ) -> Dialogue:
        """Both members at target → status becomes participating.

        Caller (decision tree / orchestrator) must verify both members
        physically arrived; here we just transition status.

        Idempotent: if already participating, returns d unchanged.
        """
        d = self._require(dialogue_id)
        if d.status == "participating":
            return d
        if d.status != "walking_over":
            raise InvalidDialogueStateError(
                f"cannot advance to participating from status {d.status!r}"
            )
        for agent_id in (d.initiator_id, d.invitee_id):
            d.member_status[agent_id] = "participating"
        d.last_message_tick = tick
        return d

    def append_message(
        self,
        dialogue_id: str,
        speaker_id: str,
        content: str,
        *,
        tick: int,
        simulated_time: datetime,
    ) -> tuple[Dialogue, DialogueMessage]:
        """Add a message to the dialogue (must be participating).

        Auto-ends on max_messages / max_duration_minutes.
        """
        d = self._require(dialogue_id)
        if d.status != "participating":
            raise InvalidDialogueStateError(
                f"cannot speak in dialogue with status {d.status!r}"
            )
        if not d.has_participant(speaker_id):
            raise ValueError(
                f"speaker {speaker_id!r} not a participant of {dialogue_id!r}"
            )
        self._message_counter += 1
        msg = DialogueMessage(
            message_id=f"msg_{dialogue_id}_{self._message_counter}",
            speaker_id=speaker_id,
            content=content,
            tick=tick,
        )
        d.messages.append(msg)
        d.last_message_tick = tick

        # Auto-end checks
        if d.message_count() >= self._max_messages:
            self._end(d, end_reason="max_messages",
                     tick=tick, simulated_time=simulated_time)
        elif d.started_at is not None:
            duration_min = (simulated_time - d.started_at).total_seconds() / 60.0
            if duration_min > self._max_duration_minutes:
                self._end(d, end_reason="timeout",
                         tick=tick, simulated_time=simulated_time)
        return d, msg

    def leave(self, dialogue_id: str, agent_id: str,
              *, tick: int, simulated_time: datetime) -> Dialogue:
        """Agent voluntarily leaves; ends the dialogue (1:1 ai-town behavior)."""
        d = self._require(dialogue_id)
        if not d.has_participant(agent_id):
            raise ValueError(
                f"agent {agent_id!r} not in {dialogue_id!r}"
            )
        return self._end(d, end_reason="leave",
                         tick=tick, simulated_time=simulated_time)

    def end(self, dialogue_id: str, end_reason: str,
            *, tick: int, simulated_time: datetime) -> Dialogue:
        """Force-end (for orchestrator timeout / external interrupt)."""
        d = self._require(dialogue_id)
        return self._end(d, end_reason=end_reason,
                         tick=tick, simulated_time=simulated_time)

    # -- bridge ------------------------------------------------------

    def bridge_to_memory_and_propagation(
        self,
        dialogue_id: str,
        *,
        memory_service: "MemoryService",
        conversation_service: "ConversationService | None" = None,
        social_graph: "SocialGraphService | None" = None,
        simulated_time: datetime,
        day_index: int = 0,
        summary: str | None = None,
        encounter_importance: float = 0.7,
        info_salience: float = 0.6,
    ) -> dict:
        """When a Dialogue ends, fan out three downstream writes (1:1
        ai-town conversation post-amble + SSWT propagation):

        1. memory side: each participant gets a MemoryEvent[kind="encounter"]
           with importance=encounter_importance (default 0.7, higher than
           generic-encounter 0.5 because dialogue is intentional).
           `related_memory_ids` is empty here — the actual conversation
           summary memory (kind="conversation") is written later by the
           remember_conversation op handler.
        2. propagation side: dialogue summary wrapped as
           Information(category="dialogue", salience=info_salience,
           default 0.6); record_origin called with initiator_id at
           dialogue's ended_tick. Propagates from next tick onward.
        3. social_graph side: record_encounter(a, b, tick, day_index)
           strengthens the pairwise tie.

        Idempotent: a dialogue_id already bridged is a no-op (returns
        cached result metadata). Safe to call from both the
        remember_conversation handler and an orchestrator hook.

        Skipping rule: if dialogue ended via "rejected:*" with zero
        messages, NO bridging happens (parallel to ai-town's
        rememberConversation skipping zero-message conversations).

        Args:
            dialogue_id: must be a known, ended dialogue.
            memory_service: required.
            conversation_service: optional; if None, propagation step
                is skipped (memory + social_graph still run).
            social_graph: optional; if None, social_graph step is
                skipped.
            simulated_time: clock time to stamp on memory events.
            day_index: matches orchestrator's day_index.
            summary: dialogue summary text (from remember_conversation
                handler). If None, falls back to "<dialogue {id}
                ended>".
            encounter_importance: importance for the encounter memory
                events. Default 0.7.
            info_salience: salience for the Information. Default 0.6.

        Returns:
            dict with metadata for inspector / metrics:
            {
                "skipped": bool,
                "memory_event_ids": tuple[str, str] | (),
                "info_id": str | None,
                "tie_strength": float | None,
            }
        """
        from synthetic_socio_wind_tunnel.memory.models import MemoryEvent

        d = self._require(dialogue_id)
        if d.ended_tick is None:
            raise InvalidDialogueStateError(
                f"cannot bridge dialogue {dialogue_id!r} — not ended yet"
            )
        if dialogue_id in self._bridged:
            return {
                "skipped": True,
                "reason": "already_bridged",
                "memory_event_ids": (),
                "info_id": None,
                "tie_strength": None,
            }

        reason = d.end_reason or ""
        if reason.startswith("rejected") and not d.messages:
            # Pure-reject with no exchange — don't fabricate an encounter.
            self._bridged.add(dialogue_id)
            return {
                "skipped": True,
                "reason": "rejected_no_messages",
                "memory_event_ids": (),
                "info_id": None,
                "tie_strength": None,
            }

        a = d.initiator_id
        b = d.invitee_id
        tick = d.ended_tick
        summary_text = (summary or "").strip() or (
            f"<dialogue {dialogue_id} ended:{reason or 'unknown'}>"
        )
        location = d.target_location_id

        # 1. memory side — bidirectional encounter events ---------------
        events: list[MemoryEvent] = []
        for me, other in ((a, b), (b, a)):
            ev = MemoryEvent(
                event_id=f"ev_dlg_{dialogue_id}_{me}_encounter",
                agent_id=me,
                tick=tick,
                simulated_time=simulated_time,
                kind="encounter",
                content=(
                    f"had a conversation with {other}"
                    + (f" at {location}" if location else "")
                    + (f": {summary_text}" if summary else "")
                ),
                actor_id=other,
                location_id=location,
                urgency=0.0,
                importance=encounter_importance,
                participants=(other,),
                tags=("encounter", "dialogue"),
                day_index=day_index,
            )
            memory_service.record(me, ev)
            events.append(ev)

        # 2. propagation side — dialogue → Information ------------------
        info_id: str | None = None
        if conversation_service is not None:
            from synthetic_socio_wind_tunnel.conversation import Information
            info_id = f"info_dlg_{dialogue_id}"
            info = Information(
                info_id=info_id,
                content=summary_text,
                category="dialogue",
                salience=info_salience,
                origin_tick=tick,
                origin_agent_id=a,
                origin_day_index=day_index,
                source_location_id=location,
            )
            conversation_service.record_origin(info, a, tick=tick)

        # 3. social_graph side — strengthen tie -------------------------
        tie_strength: float | None = None
        if social_graph is not None:
            tie = social_graph.record_encounter(a, b, tick=tick, day_index=day_index)
            tie_strength = tie.strength

        self._bridged.add(dialogue_id)
        return {
            "skipped": False,
            "reason": None,
            "memory_event_ids": tuple(e.event_id for e in events),
            "info_id": info_id,
            "tie_strength": tie_strength,
        }

    def has_bridged(self, dialogue_id: str) -> bool:
        """Inspector / debug: did we already bridge this dialogue?"""
        return dialogue_id in self._bridged

    def _end(self, d: Dialogue, *, end_reason: str,
             tick: int, simulated_time: datetime) -> Dialogue:
        if d.ended_tick is not None:
            return d  # already ended; idempotent
        d.ended_tick = tick
        d.end_reason = end_reason
        for agent_id in (d.initiator_id, d.invitee_id):
            d.member_status[agent_id] = "ended"
            self._active_by_agent.pop(agent_id, None)
        pair = self._canonical_pair(d.initiator_id, d.invitee_id)
        self._last_ended_at[pair] = simulated_time
        return d

    # -- queries -----------------------------------------------------

    def get(self, dialogue_id: str) -> Dialogue | None:
        return self._dialogues.get(dialogue_id)

    def active_for(self, agent_id: str) -> Dialogue | None:
        d_id = self._active_by_agent.get(agent_id)
        if d_id is None:
            return None
        return self._dialogues.get(d_id)

    def ended_for(
        self, agent_id: str, since_tick: int = 0,
    ) -> list[Dialogue]:
        return [
            d for d in self._dialogues.values()
            if d.has_participant(agent_id)
            and d.ended_tick is not None
            and d.ended_tick >= since_tick
        ]

    def all_dialogues(self) -> list[Dialogue]:
        return list(self._dialogues.values())

    # -- metrics -----------------------------------------------------

    def total_count(self) -> int:
        return len(self._dialogues)

    def active_count(self) -> int:
        return sum(1 for d in self._dialogues.values() if d.ended_tick is None)

    def ended_count(self) -> int:
        return sum(1 for d in self._dialogues.values() if d.ended_tick is not None)

    def avg_message_count(self) -> float:
        ended = [d for d in self._dialogues.values() if d.ended_tick is not None]
        if not ended:
            return 0.0
        return sum(d.message_count() for d in ended) / len(ended)

    def avg_duration_ticks(self) -> float:
        ended = [d for d in self._dialogues.values() if d.ended_tick is not None]
        if not ended:
            return 0.0
        return sum(
            (d.ended_tick - d.started_tick) for d in ended
        ) / len(ended)

    def counts_by_end_reason(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in self._dialogues.values():
            if d.end_reason:
                # Strip "rejected:..." suffix to "rejected" for grouping
                key = d.end_reason.split(":", 1)[0]
                out[key] = out.get(key, 0) + 1
        return out

    # -- internals ----------------------------------------------------

    def _require(self, dialogue_id: str) -> Dialogue:
        d = self._dialogues.get(dialogue_id)
        if d is None:
            raise KeyError(f"unknown dialogue_id {dialogue_id!r}")
        return d

    @staticmethod
    def _canonical_pair(a: str, b: str) -> tuple[str, str]:
        return (a, b) if a < b else (b, a)

    def _next_dialogue_id(self, a: str, b: str, tick: int) -> str:
        """Stable id from (canonical pair, tick). If repeated within same tick,
        suffix counter."""
        pair = self._canonical_pair(a, b)
        base = f"d_{pair[0]}_{pair[1]}_{tick}"
        if base not in self._dialogues:
            return base
        # extremely rare; loop suffix
        i = 1
        while f"{base}_{i}" in self._dialogues:
            i += 1
        return f"{base}_{i}"



__all__ = [
    "DialogueAlreadyExistsError",
    "DialogueCooldownError",
    "DialogueService",
    "InvalidDialogueStateError",
    "DEFAULT_COOLDOWN_MINUTES",
    "DEFAULT_MAX_MESSAGES",
    "DEFAULT_MAX_DURATION_MINUTES",
]
