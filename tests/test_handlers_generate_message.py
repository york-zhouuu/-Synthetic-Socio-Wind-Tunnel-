"""Tests for handle_generate_message + handle_remember_conversation."""

from __future__ import annotations

import asyncio

import pytest

from synthetic_socio_wind_tunnel.agent.operations.handlers import (
    handle_generate_message,
    handle_remember_conversation,
)
from synthetic_socio_wind_tunnel.agent.operations.handlers.generate_message import (
    _build_start_prompt,
    _build_continue_prompt,
    _build_leave_prompt,
    _trim_prefix,
)
from synthetic_socio_wind_tunnel.agent.operations.models import PendingOp


class _StubLLM:
    def __init__(self, response: str = "Hi Linda, nice to see you!",
                 *, raise_exc: bool = False) -> None:
        self.response = response
        self.raise_exc = raise_exc
        self.calls: list[str] = []

    async def generate(self, prompt: str, *, model: str = "", **kw) -> str:
        self.calls.append(prompt)
        if self.raise_exc:
            raise RuntimeError("LLM down")
        return self.response


def _op(kind: str = "generate_message", args: dict | None = None) -> PendingOp:
    return PendingOp(
        op_id="op1", agent_id="emma", kind=kind,  # type: ignore[arg-type]
        created_tick=10, timeout_tick=34,
        args=args or {},
    )


# ---------------------------------------------------------------------------
# Prompt building (verify ai-town fidelity)
# ---------------------------------------------------------------------------


class TestPromptStructure:

    def _args(self, **overrides) -> dict:
        base = dict(
            dialogue_id="d1",
            speaker_id="emma", other_agent_id="linda",
            speaker_name="Emma", other_name="Linda",
            speaker_identity="A 30-year-old librarian who loves quiet routines.",
            speaker_plan="Catch up with neighbours about the weekend market.",
            other_identity="A new resident still finding her way around.",
            recent_messages=[],
            relevant_memories=[],
        )
        base.update(overrides)
        return base

    def test_start_prompt_contains_aitown_markers(self):
        prompt = _build_start_prompt(self._args(phase="start"))
        # ai-town verbatim
        assert prompt.startswith(
            "You are Emma, and you just started a conversation with Linda."
        )
        assert "About you: A 30-year-old librarian" in prompt
        assert "Your goals for the conversation: Catch up" in prompt
        assert "About Linda: A new resident" in prompt
        assert prompt.endswith("Emma to Linda:")

    def test_continue_prompt_with_history(self):
        args = self._args(
            recent_messages=[("Emma", "Hi!"), ("Linda", "Oh hi Emma")],
        )
        prompt = _build_continue_prompt(args)
        assert "currently in a conversation with Linda" in prompt
        # ai-town verbatim instructions (conversation.ts:107-110)
        assert 'DO NOT greet them again' in prompt
        assert 'within 200 characters' in prompt
        assert "Emma: Hi!" in prompt
        assert "Linda: Oh hi Emma" in prompt
        assert prompt.endswith("Emma to Linda:")

    def test_leave_prompt_polite_exit(self):
        prompt = _build_leave_prompt(self._args())
        assert "decided to leave the conversation" in prompt
        assert "politely tell them you're leaving" in prompt

    def test_relevant_memories_block(self):
        prompt = _build_start_prompt(self._args(
            phase="start",
            relevant_memories=["Emma mentioned the cafe last Tuesday."],
        ))
        assert "Relevant memories you have:" in prompt
        assert "- Emma mentioned the cafe last Tuesday." in prompt


# ---------------------------------------------------------------------------
# trim_prefix util (1:1 port)
# ---------------------------------------------------------------------------


class TestTrimPrefix:

    def test_strips_self_prefix(self):
        assert _trim_prefix("Emma to Linda: Hi!", "Emma to Linda:") == "Hi!"

    def test_no_strip_when_absent(self):
        assert _trim_prefix("Just hi!", "Emma to Linda:") == "Just hi!"


# ---------------------------------------------------------------------------
# handle_generate_message
# ---------------------------------------------------------------------------


class TestHandleGenerateMessage:

    def _make_op(self, phase: str = "start") -> PendingOp:
        return _op(args={
            "dialogue_id": "d1",
            "speaker_id": "emma", "other_agent_id": "linda",
            "speaker_name": "Emma", "other_name": "Linda",
            "speaker_identity": "id",
            "speaker_plan": "plan",
            "other_identity": "other id",
            "recent_messages": [],
            "relevant_memories": [],
            "phase": phase,
        })

    def test_success(self):
        llm = _StubLLM(response="Nice to see you!")
        op = self._make_op()
        result = asyncio.run(handle_generate_message(op, llm_client=llm))
        assert result.success is True
        assert result.payload["content"] == "Nice to see you!"
        assert result.payload["dialogue_id"] == "d1"
        assert result.payload["speaker_id"] == "emma"
        assert result.payload["phase"] == "start"

    def test_strips_self_prefix(self):
        llm = _StubLLM(response="Emma to Linda: Hello!")
        op = self._make_op()
        result = asyncio.run(handle_generate_message(op, llm_client=llm))
        assert result.payload["content"] == "Hello!"

    def test_llm_failure(self):
        llm = _StubLLM(raise_exc=True)
        op = self._make_op()
        result = asyncio.run(handle_generate_message(op, llm_client=llm))
        assert result.success is False
        assert "LLM error" in (result.error_msg or "")

    def test_empty_response_failed(self):
        llm = _StubLLM(response="")
        op = self._make_op()
        result = asyncio.run(handle_generate_message(op, llm_client=llm))
        assert result.success is False

    def test_phase_routes_to_correct_prompt(self):
        llm = _StubLLM(response="ok")
        for phase in ["start", "continue", "leave"]:
            op = self._make_op(phase=phase)
            asyncio.run(handle_generate_message(op, llm_client=llm))
        # 3 different prompts
        assert len(llm.calls) == 3
        assert "you just started" in llm.calls[0]
        assert "DO NOT greet" in llm.calls[1]
        assert "decided to leave" in llm.calls[2]


# ---------------------------------------------------------------------------
# handle_remember_conversation
# ---------------------------------------------------------------------------


class TestHandleRemember:

    def test_summary_success(self):
        llm = _StubLLM(response="I had a nice chat with Linda.")
        op = _op(kind="remember_conversation", args={
            "dialogue_id": "d1",
            "speaker_id": "emma",
            "speaker_name": "Emma", "other_name": "Linda",
            "messages": [
                ("emma", "hi"), ("linda", "hello"), ("emma", "bye"),
            ],
        })
        result = asyncio.run(handle_remember_conversation(op, llm_client=llm))
        assert result.success is True
        assert result.payload["summary"] == "I had a nice chat with Linda."
        # 1:1 port — verify prompt contains ai-town's verbatim opening
        prompt = llm.calls[0]
        assert "you just finished a conversation with Linda" in prompt
        assert 'first-person pronouns like "I,"' in prompt
        assert "Emma to Linda: hi" in prompt
        assert "Linda to Emma: hello" in prompt

    def test_no_messages_skipped(self):
        op = _op(kind="remember_conversation", args={
            "dialogue_id": "d1",
            "speaker_id": "emma",
            "speaker_name": "Emma", "other_name": "Linda",
            "messages": [],
        })
        # Should skip LLM entirely
        llm = _StubLLM()
        result = asyncio.run(handle_remember_conversation(op, llm_client=llm))
        assert result.success is True
        assert result.payload.get("skipped") is True
        assert llm.calls == []

    def test_llm_failure(self):
        llm = _StubLLM(raise_exc=True)
        op = _op(kind="remember_conversation", args={
            "dialogue_id": "d1",
            "speaker_id": "emma",
            "speaker_name": "Emma", "other_name": "Linda",
            "messages": [("emma", "hi")],
        })
        result = asyncio.run(handle_remember_conversation(op, llm_client=llm))
        assert result.success is False
