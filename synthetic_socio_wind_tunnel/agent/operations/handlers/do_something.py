"""
handle_do_something — protagonist agent's "what should I do next" LLM call.

Ports ai-town's `agentDoSomething` (convex/agent/agent.ts:153-282), the
function the Agent fires when it has finished a conversation (or never had
one) and needs to decide whether to go somewhere, invite someone to chat,
or just continue current activity.

The handler returns one of three structured actions in OperationResult.payload:
    {"action": "invite_dialogue", "target_agent_id": str}
    {"action": "go_to", "destination_id": str}
    {"action": "activity", "activity": str, "duration_minutes": int}

The agent's `step()` (Phase D task 18) reads this from the agent's input
queue on the following tick and applies it.

Args (in op.args):
- agent_id: str
- agent_name: str
- agent_identity: str | None
- agent_plan: str | None
- current_location_id: str
- recent_memories: list[str]   # pre-rendered, e.g. last 5 memory contents
- nearby_agents: list[dict]    # {"agent_id", "name", "is_familiar": bool}
- candidate_destinations: list[str]  # dest_ids the agent could pick from
- current_time: str            # "HH:MM" for prompt
- model: str                   # optional override
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from synthetic_socio_wind_tunnel.agent.operations.models import (
    OperationResult,
    PendingOp,
)

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.planner import LLMClient


logger = logging.getLogger(__name__)


_VALID_ACTIONS = ("invite_dialogue", "go_to", "activity", "wait")


def _build_do_something_prompt(args: dict) -> str:
    """1:1-spirit port of agentDoSomething's prompt construction."""
    name = args["agent_name"]
    identity = args.get("agent_identity") or ""
    plan = args.get("agent_plan") or ""
    location = args.get("current_location_id", "")
    current_time = args.get("current_time", "")
    recent = args.get("recent_memories", [])
    nearby = args.get("nearby_agents", [])
    destinations = args.get("candidate_destinations", [])

    parts: list[str] = []
    parts.append(
        f"You are {name}, deciding what to do next in your day. "
        f"It is currently {current_time} and you are at {location}."
    )
    if identity:
        parts.append(f"About you: {identity}")
    if plan:
        parts.append(f"Your plan for today: {plan}")

    if recent:
        parts.append("Recent things on your mind:")
        for m in recent:
            parts.append(f"- {m}")

    if nearby:
        parts.append("People nearby:")
        for n in nearby:
            tag = "familiar" if n.get("is_familiar") else "stranger"
            parts.append(f"- {n.get('name', n.get('agent_id', '?'))} ({tag})")
    else:
        parts.append("No one else is around.")

    if destinations:
        dest_list = ", ".join(destinations)
        parts.append(f"Places you could head to: {dest_list}")

    # B4: hyperlocal conversation topics for grounding (Lane Cove discourse)
    local_topics = args.get("local_topics", ())
    if local_topics:
        parts.append("Recent local topics in your area:")
        for t in local_topics:
            parts.append(f"- {t}")

    parts.append(
        "Pick exactly ONE action and output JSON ONLY (no prose, no markdown):\n"
        '  {"action":"invite_dialogue","target_agent_id":"<id>"}    -- '
        "if you want to talk to a familiar nearby person\n"
        '  {"action":"go_to","destination_id":"<dest_id>"}          -- '
        "if you want to walk to one of the listed destinations\n"
        '  {"action":"activity","activity":"<short verb>",'
        '"duration_minutes":<int 5-30>}                              -- '
        "if you want to stay and do something\n"
        '  {"action":"wait"}                                        -- '
        "if you want to just observe / do nothing"
    )
    return "\n".join(parts)


def _parse_response(raw: str) -> dict[str, Any] | None:
    """Parse LLM JSON → action dict. Returns None on parse fail."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text.split("\n", 1)[1] if "\n" in text else ""
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    action = obj.get("action")
    if action not in _VALID_ACTIONS:
        return None
    if action == "invite_dialogue" and not obj.get("target_agent_id"):
        return None
    if action == "go_to" and not obj.get("destination_id"):
        return None
    if action == "activity" and not obj.get("activity"):
        return None
    return obj


def _fallback_action(args: dict) -> dict[str, Any]:
    """Deterministic fallback when LLM fails / parses poorly.

    Heuristic: prefer waiting. If candidate_destinations are present pick
    the first one as a go_to. Never tries to invite (avoids spurious
    dialogues from a fallback path).
    """
    destinations = args.get("candidate_destinations") or []
    if destinations:
        return {"action": "go_to", "destination_id": destinations[0]}
    return {"action": "wait"}


async def handle_do_something(
    op: PendingOp,
    *,
    llm_client: "LLMClient",
    **kwargs,
) -> OperationResult:
    """Decide the agent's next high-level action via LLM.

    Returns OperationResult with payload like:
        {"action": "invite_dialogue", "target_agent_id": "linda"}
    or
        {"action": "go_to", "destination_id": "cafe_main"}
    or
        {"action": "activity", "activity": "read_book", "duration_minutes": 15}
    or
        {"action": "wait"}

    Failures fall back deterministically — never raises.
    """
    # Capability 1.13 (2026-05-19): wire LLMHealthTracker for budget enforcement.
    from synthetic_socio_wind_tunnel.run_resilience.circuit_breaker import (
        AllKeysOpenError,
    )
    from synthetic_socio_wind_tunnel.run_resilience.llm_health import get_tracker

    args = op.args
    prompt = _build_do_something_prompt(args)
    tracker = get_tracker()
    try:
        raw = await llm_client.generate(prompt, model=args.get("model", ""))
    except AllKeysOpenError:
        # Structural failure — record + re-raise. Per-call fallback would
        # mask 8-keys-out-of-8 cooldown as healthy noise.
        tracker.record_all_keys_open()
        raise
    except Exception as exc:
        logger.warning(
            "do_something LLM failed for agent %s: %r — using fallback",
            op.agent_id, exc,
        )
        tracker.record_fallback()
        action = _fallback_action(args)
        return OperationResult(
            op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
            success=True,
            payload={**action, "fallback": True, "error": f"LLM error: {exc}"},
        )

    parsed = _parse_response(raw)
    if parsed is None:
        logger.warning(
            "do_something LLM returned unparseable response for agent %s; "
            "raw=%r — using fallback",
            op.agent_id, (raw or "")[:200],
        )
        tracker.record_fallback()
        action = _fallback_action(args)
        return OperationResult(
            op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
            success=True,
            payload={**action, "fallback": True, "error": "parse_failed"},
        )
    tracker.record_success()
    return OperationResult(
        op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
        success=True,
        payload={**parsed, "fallback": False},
    )


__all__ = ["handle_do_something"]
