"""
handle_remember_conversation — summarises an ended dialogue → memory.

Ports ai-town's `rememberConversation()` (convex/agent/memory.ts:24-86).

Args (in op.args):
- dialogue_id: str
- speaker_id: str (the agent doing the remembering)
- other_name: str
- speaker_name: str
- messages: list[(speaker_id, content)]
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.agent.operations.models import (
    OperationResult,
    PendingOp,
)

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.planner import LLMClient


def _build_summary_prompt(args: dict) -> str:
    """1:1 port of ai-town's summary prompt (memory.ts:42-60)."""
    speaker_name = args["speaker_name"]
    other_name = args["other_name"]
    speaker_id = args["speaker_id"]
    messages = args.get("messages", [])
    lines = [
        (f"You are {speaker_name}, and you just finished a conversation with "
         f"{other_name}. I would like you to summarize the conversation from "
         f"{speaker_name}'s perspective, using first-person pronouns like "
         f'"I," and add if you liked or disliked this interaction.'),
    ]
    for sid, content in messages:
        author_name = speaker_name if sid == speaker_id else other_name
        recipient_name = other_name if sid == speaker_id else speaker_name
        lines.append(f"{author_name} to {recipient_name}: {content}")
    lines.append("Summary:")
    return "\n".join(lines)


async def handle_remember_conversation(
    op: PendingOp,
    *,
    llm_client: "LLMClient",
    **kwargs,
) -> OperationResult:
    """Summarise dialogue → returns payload {"dialogue_id", "summary"}."""
    args = op.args
    if not args.get("messages"):
        return OperationResult(
            op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
            success=True,  # no messages → trivial empty summary
            payload={
                "dialogue_id": args.get("dialogue_id", ""),
                "summary": "",
                "skipped": True,
            },
        )
    prompt = _build_summary_prompt(args)
    try:
        raw = await llm_client.generate(prompt, model=args.get("model", ""))
    except Exception as exc:
        return OperationResult(
            op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
            success=False, error_msg=f"LLM error: {exc}",
        )
    summary = (raw or "").strip()
    return OperationResult(
        op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
        success=True,
        payload={
            "dialogue_id": args["dialogue_id"],
            "summary": summary,
            "speaker_name": args["speaker_name"],
            "other_name": args["other_name"],
        },
    )


__all__ = ["handle_remember_conversation"]
