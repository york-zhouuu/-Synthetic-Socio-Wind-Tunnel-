"""
agent/operations — async LLM operation pool (ai-town port).

Ports ai-town's `agent.startOperation()` + `agentOperations.ts` async
action pattern (convex/aiTown/agent.ts:32-269, agentOperations.ts:18-179).

Five operation kinds:
- `do_something` — agent decides next free-form action (sonnet tier)
- `generate_message` — produce next dialogue message (sonnet tier)
- `remember_conversation` — summarise ended dialogue → memory (haiku)
- `reflect` — abstract memory cluster → insight (haiku)
- `score_importance` — rate event poignancy 0-9 (nano)

OperationPool runs handlers async via asyncio.gather, with per-agent single-op
queue, per-tick timeout (24 simulated-ticks default ≈ 120 simulated minutes),
tier-routed LLM clients, and cost telemetry.

V1 only protagonist agents schedule ops; scripted agents skip the pool entirely.
"""

from synthetic_socio_wind_tunnel.agent.operations.models import (
    ConcurrentOperationError,
    OpKind,
    OperationResult,
    PendingOp,
)
from synthetic_socio_wind_tunnel.agent.operations.pool import OperationPool

__all__ = [
    "ConcurrentOperationError",
    "OpKind",
    "OperationPool",
    "OperationResult",
    "PendingOp",
]
