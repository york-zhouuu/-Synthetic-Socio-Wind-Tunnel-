"""
ImportanceScorer — LLM-rated 0-9 → normalized to [0, 1] importance.

Ports ai-town's `calculateImportance()` (convex/agent/memory.ts:246-269).
Each MemoryEvent (for protagonist agents only) gets a one-shot LLM rating
of "poignancy" 0-9, normalized and stored on the event. Defaults to 0.5
(the SSWT MemoryEvent default) on LLM failure / parse error.

Cost note: only protagonist events score (10/1000 agents). Use a nano-tier
LLM to keep per-seed importance budget < $1.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.planner import LLMClient
    from synthetic_socio_wind_tunnel.memory.models import MemoryEvent


logger = logging.getLogger(__name__)


_PROMPT_TEMPLATE = (
    "On a scale from 0 to 9, rate how poignant / memorable / "
    "potentially-relevant-for-future-decisions the following memory is. "
    "0 = trivial / forgettable; 9 = life-defining / radically important. "
    "Reply with a single integer 0-9, nothing else.\n\n"
    "Memory: {content}"
)


class ImportanceScorer:
    """LLM-driven importance scoring for memory events.

    Stateless service (no internal cache; caller is responsible for not
    re-scoring the same event_id). Pair with EmbeddingsCache if you want
    text-keyed dedup of identical content strings.
    """

    __slots__ = ("_llm_client", "_model", "_default_on_failure")

    def __init__(
        self,
        *,
        llm_client: "LLMClient",
        model: str = "",
        default_on_failure: float = 0.5,
    ) -> None:
        self._llm_client = llm_client
        self._model = model
        self._default_on_failure = default_on_failure

    async def score(self, event: "MemoryEvent") -> float:
        """Return importance ∈ [0, 1] for `event.content`. Never raises."""
        if not event.content:
            return self._default_on_failure
        prompt = _PROMPT_TEMPLATE.format(content=event.content)
        try:
            raw = await self._llm_client.generate(prompt, model=self._model)
        except Exception as exc:  # pragma: no cover (defensive)
            logger.warning("importance scoring failed (LLM error): %s", exc)
            return self._default_on_failure
        return self._parse(raw)

    async def score_batch(
        self, events: list["MemoryEvent"], *, batch_size: int = 5,
    ) -> list[float]:
        """Score N events concurrently in chunks of `batch_size`."""
        results: list[float] = []
        for i in range(0, len(events), batch_size):
            chunk = events[i : i + batch_size]
            chunk_results = await asyncio.gather(
                *[self.score(e) for e in chunk]
            )
            results.extend(chunk_results)
        return results

    def _parse(self, raw: str) -> float:
        """Parse LLM response → integer 0-9 → normalized [0, 1].

        Tolerates: leading/trailing whitespace, "Importance: 7", "7/9",
        "Score=3", a single digit. Falls back to `default_on_failure` on
        any parse error.
        """
        text = (raw or "").strip()
        if not text:
            return self._default_on_failure
        # Look for the first digit 0-9 in the response
        for ch in text:
            if ch.isdigit():
                rating = int(ch)
                if 0 <= rating <= 9:
                    return rating / 9.0
        logger.warning("importance scoring failed (no digit in response): %r", text[:80])
        return self._default_on_failure


__all__ = ["ImportanceScorer"]
