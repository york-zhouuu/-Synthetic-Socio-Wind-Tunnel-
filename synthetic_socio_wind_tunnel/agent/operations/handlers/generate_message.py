"""
handle_generate_message — produces the next dialogue message via LLM.

Ports ai-town's `startConversationMessage` / `continueConversationMessage`
/ `leaveConversationMessage` (convex/agent/conversation.ts:13-183).

Single handler with `phase` arg:
- phase="start" — first message ("You just started a conversation with Linda")
- phase="continue" — mid-conversation ("Below is the chat history; respond")
- phase="leave" — graceful exit ("politely tell them you're leaving")

Args (in op.args):
- dialogue_id: str
- speaker_id: str (the agent producing the message)
- other_agent_id: str
- speaker_identity: str (from AgentProfile.identity_text)
- speaker_plan: str (from AgentProfile.plan_text)
- other_identity: str | None (other agent's identity_text)
- other_name: str
- speaker_name: str
- recent_messages: list[(speaker_id, content)]  # for continue/leave phase
- relevant_memories: list[str]  # ai-town searches by embedding; we pass pre-fetched
- phase: "start" | "continue" | "leave"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.agent.operations.models import (
    OperationResult,
    PendingOp,
)

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.planner import LLMClient


def _agent_lines(
    speaker_name: str,
    speaker_identity: str,
    speaker_plan: str,
    other_name: str,
    other_identity: str | None,
) -> list[str]:
    """1:1 port of agentPrompts() (conversation.ts:185-199)."""
    out: list[str] = []
    if speaker_identity:
        out.append(f"About you: {speaker_identity}")
    if speaker_plan:
        out.append(f"Your goals for the conversation: {speaker_plan}")
    if other_identity:
        out.append(f"About {other_name}: {other_identity}")
    return out


def _memories_block(memories: list[str]) -> list[str]:
    """1:1 port of relatedMemoriesPrompt()."""
    if not memories:
        return []
    out = ["Relevant memories you have:"]
    for m in memories:
        out.append(f"- {m}")
    return out


def _build_start_prompt(args: dict) -> str:
    speaker_name = args["speaker_name"]
    other_name = args["other_name"]
    parts = [
        f"You are {speaker_name}, and you just started a conversation with {other_name}.",
    ]
    parts.extend(_agent_lines(
        speaker_name,
        args.get("speaker_identity", ""),
        args.get("speaker_plan", ""),
        other_name,
        args.get("other_identity"),
    ))
    parts.extend(_memories_block(args.get("relevant_memories", [])))
    parts.append(f"{speaker_name} to {other_name}:")
    return "\n".join(parts)


def _build_continue_prompt(args: dict) -> str:
    speaker_name = args["speaker_name"]
    other_name = args["other_name"]
    parts = [
        f"You are {speaker_name}, and you're currently in a conversation with {other_name}.",
    ]
    parts.extend(_agent_lines(
        speaker_name,
        args.get("speaker_identity", ""),
        args.get("speaker_plan", ""),
        other_name,
        args.get("other_identity"),
    ))
    parts.extend(_memories_block(args.get("relevant_memories", [])))
    parts.append(
        f"Below is the current chat history between you and {other_name}."
    )
    parts.append(
        'DO NOT greet them again. Do NOT use the word "Hey" too often. '
        'Your response should be brief and within 200 characters.'
    )
    # Append history
    for speaker, content in args.get("recent_messages", []):
        parts.append(f"{speaker}: {content}")
    parts.append(f"{speaker_name} to {other_name}:")
    return "\n".join(parts)


def _build_leave_prompt(args: dict) -> str:
    speaker_name = args["speaker_name"]
    other_name = args["other_name"]
    parts = [
        f"You are {speaker_name}, and you're currently in a conversation with {other_name}.",
        "You've decided to leave the conversation and would like to politely tell them you're leaving.",
    ]
    parts.extend(_agent_lines(
        speaker_name,
        args.get("speaker_identity", ""),
        args.get("speaker_plan", ""),
        other_name,
        args.get("other_identity"),
    ))
    parts.append(
        f"Below is the current chat history between you and {other_name}."
    )
    parts.append(
        "How would you like to tell them that you're leaving? "
        "Your response should be brief and within 200 characters."
    )
    for speaker, content in args.get("recent_messages", []):
        parts.append(f"{speaker}: {content}")
    parts.append(f"{speaker_name} to {other_name}:")
    return "\n".join(parts)


def _trim_prefix(content: str, last_prompt: str) -> str:
    """1:1 port of trimContentPrefx (conversation.ts:71-76)."""
    if content.startswith(last_prompt):
        return content[len(last_prompt) :].strip()
    return content


async def handle_generate_message(
    op: PendingOp,
    *,
    llm_client: "LLMClient",
    **kwargs,
) -> OperationResult:
    """Produce the next dialogue message. Returns OperationResult with
    payload {"dialogue_id", "speaker_id", "content"}.
    """
    args = op.args
    phase = args.get("phase", "continue")
    speaker_name = args["speaker_name"]
    other_name = args["other_name"]

    if phase == "start":
        prompt = _build_start_prompt(args)
    elif phase == "leave":
        prompt = _build_leave_prompt(args)
    else:
        prompt = _build_continue_prompt(args)

    last_prompt_marker = f"{speaker_name} to {other_name}:"
    try:
        raw = await llm_client.generate(prompt, model=args.get("model", ""))
    except Exception as exc:
        return OperationResult(
            op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
            success=False, error_msg=f"LLM error: {exc}",
        )
    content = _trim_prefix(raw or "", last_prompt_marker).strip()
    if not content:
        return OperationResult(
            op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
            success=False, error_msg="empty response",
        )
    return OperationResult(
        op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
        success=True,
        payload={
            "dialogue_id": args["dialogue_id"],
            "speaker_id": args["speaker_id"],
            "content": content,
            "phase": phase,
        },
    )


__all__ = ["handle_generate_message"]
