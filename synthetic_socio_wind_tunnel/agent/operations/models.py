"""PendingOp / OperationResult — value objects for the agent operation pool.

Port of ai-town's operationId tracking pattern. Frozen so they survive
asyncio.gather without surprise mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


# Five operation kinds (ai-town: agentDoSomething / agentGenerateMessage /
# agentRememberConversation; ai-town port adds reflect / score_importance).
OpKind = Literal[
    "do_something",
    "generate_message",
    "remember_conversation",
    "reflect",
    "score_importance",
]


class ConcurrentOperationError(RuntimeError):
    """Raised when scheduling a second op for an agent already with a pending one."""


@dataclass(frozen=True)
class PendingOp:
    """An async operation in flight for one agent.

    Caller (decision tree) creates via `OperationPool.schedule(...)`.
    Pool runs the corresponding handler async and writes result to the
    agent's tick_inputs queue when done.

    Invariants:
    - `op_id` globally unique; combine agent_id + tick + kind for stability
    - `timeout_tick > created_tick`
    - `args` is operation-specific (see handlers)
    """

    op_id: str
    agent_id: str
    kind: OpKind
    created_tick: int
    timeout_tick: int
    args: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timeout_tick <= self.created_tick:
            raise ValueError(
                f"timeout_tick must exceed created_tick "
                f"(got {self.timeout_tick} <= {self.created_tick})"
            )


@dataclass(frozen=True)
class OperationResult:
    """The output of running a PendingOp's handler.

    `success=False` is non-fatal — caller's decision tree should handle
    gracefully (clear pending op, continue normal flow).

    `payload` is op-specific:
    - do_something: {"action": "invite_dialogue" | "go_to" | "activity", ...}
    - generate_message: {"dialogue_id", "speaker_id", "content"}
    - remember_conversation: {"summary", "dialogue_id"}
    - reflect: {"insights": [{"text", "source_event_ids", "importance"}]}
    - score_importance: {"event_id", "importance": float}
    """

    op_id: str
    agent_id: str
    kind: OpKind
    success: bool
    payload: dict[str, Any] = field(default_factory=dict)
    error_msg: str | None = None
    # Cost telemetry (filled by handler from LLM client response when available)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens
