"""Tests for handle_do_something (agent-stack-aitown-port Phase D task 17)."""

from __future__ import annotations

import asyncio
import json

import pytest

from synthetic_socio_wind_tunnel.agent.operations.handlers import (
    handle_do_something,
)
from synthetic_socio_wind_tunnel.agent.operations.handlers.do_something import (
    _build_do_something_prompt,
    _parse_response,
)
from synthetic_socio_wind_tunnel.agent.operations.models import PendingOp


class _StubLLM:
    def __init__(self, response: str = '{"action":"wait"}',
                 *, raise_exc: bool = False) -> None:
        self.response = response
        self.raise_exc = raise_exc
        self.calls: list[str] = []

    async def generate(self, prompt: str, *, model: str = "", **kw) -> str:
        self.calls.append(prompt)
        if self.raise_exc:
            raise RuntimeError("LLM down")
        return self.response


def _op(args: dict | None = None) -> PendingOp:
    return PendingOp(
        op_id="op1", agent_id="emma", kind="do_something",
        created_tick=10, timeout_tick=34,
        args=args or _default_args(),
    )


def _default_args(**overrides) -> dict:
    base = dict(
        agent_id="emma",
        agent_name="Emma",
        agent_identity="A 30-year-old librarian who loves quiet routines.",
        agent_plan="Catch up with neighbours about the weekend market.",
        current_location_id="park_main",
        current_time="14:30",
        recent_memories=[
            "Saw a flyer about Sunday market.",
            "Linda mentioned new cafe last week.",
        ],
        nearby_agents=[
            {"agent_id": "linda", "name": "Linda", "is_familiar": True},
            {"agent_id": "stranger_42", "name": "Person", "is_familiar": False},
        ],
        candidate_destinations=["cafe_main", "library", "home"],
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


class TestPrompt:

    def test_prompt_includes_identity_and_plan(self):
        prompt = _build_do_something_prompt(_default_args())
        assert "Emma" in prompt
        assert "librarian" in prompt
        assert "weekend market" in prompt
        assert "park_main" in prompt
        assert "14:30" in prompt
        # nearby labels: familiar / stranger (not raw agent_ids)
        assert "Linda (familiar)" in prompt
        assert "(stranger)" in prompt
        assert "cafe_main" in prompt

    def test_prompt_when_no_nearby(self):
        prompt = _build_do_something_prompt(_default_args(nearby_agents=[]))
        assert "No one else is around" in prompt

    def test_action_json_schema_listed(self):
        prompt = _build_do_something_prompt(_default_args())
        assert '"action":"invite_dialogue"' in prompt
        assert '"action":"go_to"' in prompt
        assert '"action":"activity"' in prompt
        assert '"action":"wait"' in prompt


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


class TestParseResponse:

    def test_invite_dialogue(self):
        out = _parse_response('{"action":"invite_dialogue","target_agent_id":"linda"}')
        assert out == {"action": "invite_dialogue", "target_agent_id": "linda"}

    def test_invite_missing_target_rejected(self):
        out = _parse_response('{"action":"invite_dialogue"}')
        assert out is None

    def test_go_to(self):
        out = _parse_response('{"action":"go_to","destination_id":"cafe_main"}')
        assert out["action"] == "go_to"
        assert out["destination_id"] == "cafe_main"

    def test_go_to_missing_dest_rejected(self):
        out = _parse_response('{"action":"go_to"}')
        assert out is None

    def test_activity(self):
        out = _parse_response(
            '{"action":"activity","activity":"read","duration_minutes":15}'
        )
        assert out["activity"] == "read"

    def test_activity_missing_label_rejected(self):
        out = _parse_response(
            '{"action":"activity","duration_minutes":10}'
        )
        assert out is None

    def test_wait(self):
        out = _parse_response('{"action":"wait"}')
        assert out == {"action": "wait"}

    def test_unknown_action_rejected(self):
        out = _parse_response('{"action":"teleport"}')
        assert out is None

    def test_garbage_returns_none(self):
        assert _parse_response("this is not json") is None
        assert _parse_response("") is None

    def test_markdown_fence_stripped(self):
        out = _parse_response('```json\n{"action":"wait"}\n```')
        assert out == {"action": "wait"}


# ---------------------------------------------------------------------------
# handle_do_something integration
# ---------------------------------------------------------------------------


class TestHandle:

    def test_success_invite(self):
        llm = _StubLLM(
            response='{"action":"invite_dialogue","target_agent_id":"linda"}',
        )
        op = _op()
        result = asyncio.run(handle_do_something(op, llm_client=llm))
        assert result.success is True
        assert result.payload["action"] == "invite_dialogue"
        assert result.payload["target_agent_id"] == "linda"
        assert result.payload["fallback"] is False

    def test_success_go_to(self):
        llm = _StubLLM(response='{"action":"go_to","destination_id":"cafe_main"}')
        op = _op()
        result = asyncio.run(handle_do_something(op, llm_client=llm))
        assert result.success is True
        assert result.payload["action"] == "go_to"
        assert result.payload["destination_id"] == "cafe_main"

    def test_llm_failure_falls_back_to_wait_or_destination(self):
        llm = _StubLLM(raise_exc=True)
        op = _op()
        result = asyncio.run(handle_do_something(op, llm_client=llm))
        # Fallback should still produce a successful result with an
        # action — caller treats this as agent decided to wait/go.
        assert result.success is True
        assert result.payload["fallback"] is True
        # default args have candidate_destinations → fallback prefers go_to
        assert result.payload["action"] == "go_to"
        assert result.payload["destination_id"] == "cafe_main"

    def test_llm_failure_no_destinations_falls_back_to_wait(self):
        llm = _StubLLM(raise_exc=True)
        op = _op(args=_default_args(candidate_destinations=[]))
        result = asyncio.run(handle_do_something(op, llm_client=llm))
        assert result.success is True
        assert result.payload["action"] == "wait"
        assert result.payload["fallback"] is True

    def test_unparseable_response_falls_back(self):
        llm = _StubLLM(response="oops not json")
        op = _op()
        result = asyncio.run(handle_do_something(op, llm_client=llm))
        assert result.success is True
        assert result.payload["fallback"] is True
        # error tag carries reason
        assert result.payload.get("error") == "parse_failed"
