"""Tests for B6: OperationPool stamps Gemini tokens onto OperationResult.

The handlers don't populate prompt_tokens / completion_tokens on the
OperationResult. The pool reads `_last_usage` from the dispatched client
after each handler returns and stamps it via dataclass.replace.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

from synthetic_socio_wind_tunnel.agent.operations.models import (
    OperationResult,
    PendingOp,
)
from synthetic_socio_wind_tunnel.agent.operations.pool import OperationPool


class _FakeClientWithUsage:
    def __init__(self, last_usage: dict | None) -> None:
        self._last_usage = last_usage

    async def generate(self, prompt: str, *, model: str = "", **_: Any) -> str:
        return "fake response"


async def _fake_handler(op: PendingOp, *, llm_client: Any, **_: Any) -> OperationResult:
    """Return a result with no token info — pool should stamp it."""
    # Simulate the LLM call producing the usage
    await llm_client.generate("dummy")
    return OperationResult(
        op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
        success=True, payload={"action": "wait"},
    )


class TestOperationPoolStampsTokens:

    def test_stamps_tokens_when_client_has_last_usage(self):
        client = _FakeClientWithUsage({
            "prompt_tokens": 250,
            "completion_tokens": 75,
        })
        pool = OperationPool(
            handlers={"do_something": _fake_handler},
            llm_clients={"sonnet": client, "haiku": client, "nano": client},
        )
        op = PendingOp(
            op_id="op1", agent_id="a", kind="do_something",
            args={}, created_tick=0, timeout_tick=10,
        )
        pool.schedule(op)
        results = asyncio.run(pool.process_pending(current_tick=1))

        assert len(results) == 1
        r = results[0]
        assert r.prompt_tokens == 250
        assert r.completion_tokens == 75

    def test_no_stamp_when_client_has_no_last_usage(self):
        client = _FakeClientWithUsage(None)
        pool = OperationPool(
            handlers={"do_something": _fake_handler},
            llm_clients={"sonnet": client, "haiku": client, "nano": client},
        )
        op = PendingOp(
            op_id="op2", agent_id="b", kind="do_something",
            args={}, created_tick=0, timeout_tick=10,
        )
        pool.schedule(op)
        results = asyncio.run(pool.process_pending(current_tick=1))

        assert results[0].prompt_tokens == 0
        assert results[0].completion_tokens == 0

    def test_existing_handler_tokens_respected(self):
        """If the handler already set tokens, pool SHALL NOT overwrite."""
        client = _FakeClientWithUsage({
            "prompt_tokens": 999,
            "completion_tokens": 999,
        })

        async def _handler_with_tokens(op, *, llm_client, **_):
            await llm_client.generate("x")
            return OperationResult(
                op_id=op.op_id, agent_id=op.agent_id, kind=op.kind,
                success=True, payload={"action": "wait"},
                prompt_tokens=10, completion_tokens=5,
            )

        pool = OperationPool(
            handlers={"do_something": _handler_with_tokens},
            llm_clients={"sonnet": client, "haiku": client, "nano": client},
        )
        op = PendingOp(
            op_id="op3", agent_id="c", kind="do_something",
            args={}, created_tick=0, timeout_tick=10,
        )
        pool.schedule(op)
        results = asyncio.run(pool.process_pending(current_tick=1))

        # Handler-supplied counts SHALL be preserved (10/5, not 999/999).
        assert results[0].prompt_tokens == 10
        assert results[0].completion_tokens == 5
