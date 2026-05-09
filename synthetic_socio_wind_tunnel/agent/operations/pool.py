"""OperationPool — async dispatcher + tier router for agent operations.

Lifecycle per protagonist agent per tick:

    decision_tree → pool.schedule(op, handler_kwargs)
    [ ... orchestrator runs other ticks / sync work ... ]
    pool.process_pending(tick) → asyncio.gather all ready handlers
    → OperationResult written to tick_inputs[agent_id]
    next tick → decision_tree consumes tick_inputs

`process_pending` is `async`; orchestrator wires it as an `on_tick_end_async`
hook (added in Phase E). Per-agent single-pending-op invariant enforced.

Tier routing: pool holds `dict[OpKind, LLMClient]`; handler picks client by
op.kind. Falls back to `default_llm_client` if tier missing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from synthetic_socio_wind_tunnel.agent.operations.models import (
    ConcurrentOperationError,
    OpKind,
    OperationResult,
    PendingOp,
)

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.planner import LLMClient


logger = logging.getLogger(__name__)


# Default tier mapping (design D2)
DEFAULT_TIER_FOR_KIND: dict[OpKind, str] = {
    "do_something": "sonnet",
    "generate_message": "sonnet",
    "remember_conversation": "haiku",
    "reflect": "haiku",
    "score_importance": "nano",
}


# A handler signature: (op, kwargs) -> awaitable[OperationResult]
HandlerFn = Callable[..., Awaitable[OperationResult]]


class OperationPool:
    """Async operation dispatcher with per-agent single-pending invariant."""

    __slots__ = (
        "_handlers",
        "_llm_clients",
        "_tier_for_kind",
        "_in_flight",
        "_handler_kwargs",
        "_completed_log",
        "_timeout_log",
        "_error_log",
        "_default_tier",
    )

    def __init__(
        self,
        *,
        handlers: dict[OpKind, HandlerFn],
        llm_clients: dict[str, "LLMClient"],
        tier_for_kind: dict[OpKind, str] | None = None,
        default_tier: str = "sonnet",
    ) -> None:
        self._handlers: dict[OpKind, HandlerFn] = dict(handlers)
        self._llm_clients: dict[str, "LLMClient"] = dict(llm_clients)
        self._tier_for_kind: dict[OpKind, str] = (
            dict(tier_for_kind) if tier_for_kind else dict(DEFAULT_TIER_FOR_KIND)
        )
        self._default_tier = default_tier
        # in-flight: agent_id → PendingOp
        self._in_flight: dict[str, PendingOp] = {}
        # extra kwargs the caller passed at schedule time (non-LLM args)
        self._handler_kwargs: dict[str, dict[str, Any]] = {}
        # cost telemetry
        self._completed_log: list[OperationResult] = []
        self._timeout_log: list[PendingOp] = []
        self._error_log: list[OperationResult] = []

    # ---- API ----

    def schedule(self, op: PendingOp, *, handler_kwargs: dict[str, Any] | None = None) -> None:
        """Queue an async op for `op.agent_id`.

        Raises ConcurrentOperationError if agent already has a pending op
        (caller must `cancel(agent_id, reason)` first).
        """
        existing = self._in_flight.get(op.agent_id)
        if existing is not None:
            raise ConcurrentOperationError(
                f"agent {op.agent_id} already has pending {existing.kind} "
                f"({existing.op_id}); cancel before scheduling new one"
            )
        if op.kind not in self._handlers:
            raise ValueError(f"no handler registered for op kind {op.kind!r}")
        self._in_flight[op.agent_id] = op
        self._handler_kwargs[op.agent_id] = handler_kwargs or {}

    def cancel(self, agent_id: str, reason: str = "explicit_cancel") -> bool:
        """Drop the pending op for `agent_id`; returns True if one was cancelled."""
        op = self._in_flight.pop(agent_id, None)
        self._handler_kwargs.pop(agent_id, None)
        if op is not None:
            logger.debug("cancelled %s op for %s: %s", op.kind, agent_id, reason)
            return True
        return False

    def get_pending(self, agent_id: str) -> PendingOp | None:
        return self._in_flight.get(agent_id)

    async def process_pending(self, current_tick: int) -> list[OperationResult]:
        """Run all in-flight ops concurrently; collect results.

        Side effects:
        - timed-out ops (created_tick + N <= current_tick) move to _timeout_log
        - completed ops move to _completed_log; error ops also go to _error_log
        - returns list of completed OperationResult (not timeouts)

        Caller (orchestrator on_tick_end_async hook) is responsible for
        threading these results back into `tick_inputs[agent_id]`.
        """
        timed_out: list[str] = []
        running: list[tuple[str, asyncio.Task[OperationResult]]] = []

        for agent_id, op in list(self._in_flight.items()):
            if current_tick >= op.timeout_tick:
                timed_out.append(agent_id)
                self._timeout_log.append(op)
                continue
            handler = self._handlers[op.kind]
            llm_client = self._select_llm(op.kind)
            base_kwargs = self._handler_kwargs.get(agent_id, {})
            running.append(
                (agent_id, asyncio.create_task(
                    handler(op, llm_client=llm_client, **base_kwargs),
                ))
            )

        # Sweep timeouts
        for agent_id in timed_out:
            self._in_flight.pop(agent_id, None)
            self._handler_kwargs.pop(agent_id, None)

        if not running:
            return []

        # Concurrent execution
        completed = await asyncio.gather(
            *[task for _, task in running], return_exceptions=True,
        )

        results: list[OperationResult] = []
        for (agent_id, _task), out in zip(running, completed):
            if isinstance(out, Exception):
                op = self._in_flight.get(agent_id)
                err_result = OperationResult(
                    op_id=op.op_id if op else "?",
                    agent_id=agent_id,
                    kind=op.kind if op else "do_something",
                    success=False,
                    error_msg=f"{type(out).__name__}: {out}",
                )
                self._error_log.append(err_result)
                results.append(err_result)
                logger.warning(
                    "op handler raised for %s: %s", agent_id, out,
                )
            else:
                self._completed_log.append(out)
                if not out.success:
                    self._error_log.append(out)
                results.append(out)
            # Clear pending entry
            self._in_flight.pop(agent_id, None)
            self._handler_kwargs.pop(agent_id, None)

        return results

    def _select_llm(self, kind: OpKind) -> "LLMClient":
        tier = self._tier_for_kind.get(kind, self._default_tier)
        client = self._llm_clients.get(tier)
        if client is None:
            # Fallback chain: requested tier → default tier → first available
            client = self._llm_clients.get(self._default_tier)
            if client is None and self._llm_clients:
                client = next(iter(self._llm_clients.values()))
            if client is None:
                raise RuntimeError(
                    f"No LLMClient available; cannot dispatch op kind {kind!r}"
                )
        return client

    # ---- Telemetry ----

    def get_cost_summary(self) -> dict[str, Any]:
        """Aggregated counts + token usage by op-kind / by tier."""
        by_kind: dict[str, int] = {}
        by_tier: dict[str, dict[str, int]] = {}
        for result in self._completed_log:
            by_kind[result.kind] = by_kind.get(result.kind, 0) + 1
            tier = self._tier_for_kind.get(result.kind, self._default_tier)
            tier_stats = by_tier.setdefault(
                tier, {"prompt_tokens": 0, "completion_tokens": 0, "count": 0},
            )
            tier_stats["prompt_tokens"] += result.prompt_tokens
            tier_stats["completion_tokens"] += result.completion_tokens
            tier_stats["count"] += 1
        return {
            "total_ops": len(self._completed_log),
            "by_kind": by_kind,
            "by_tier": by_tier,
            "timeouts": len(self._timeout_log),
            "errors": len(self._error_log),
        }

    def in_flight_count(self) -> int:
        return len(self._in_flight)
