"""
ReflectionService — 1:1 port of ai-town's `reflectOnMemories`.

Reference: convex/agent/memory.ts:325-397.

Algorithm (ported from ai-town verbatim):
1. Fetch latest 100 memories for an agent.
2. Sum importance of memories newer than `last_reflection_time`.
3. If sum > THRESHOLD (ai-town: 500 in 0-9 scale; we use 50.0 in [0,1] scale
   ≈ 50 events at importance=1.0, 100 events at importance=0.5; equivalent
   ratio to ai-town's 500/9 ≈ 55.5 / 100).
4. LLM prompt:
       [no prose]
       [Output only JSON]
       You are {name}, statements about you:
       Statement 0: <description>
       Statement 1: ...
       ...
       What 3 high-level insights can you infer from the above statements?
       Return JSON: [{insight: "...", statementIds: [1,2]}, ...]
5. Parse JSON → for each insight, score importance + embed → insert as
   MemoryEvent[kind="reflection"] with related_memory_ids.

This is intentionally minimalist — ai-town's prompt is exactly this terse
("[no prose] [Output only JSON]" + bare statements). We don't add personality
context or temporal framing.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from synthetic_socio_wind_tunnel.memory.models import MemoryEvent

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.agent.planner import LLMClient
    from synthetic_socio_wind_tunnel.memory.embeddings_cache import EmbeddingsCache
    from synthetic_socio_wind_tunnel.memory.importance import ImportanceScorer


logger = logging.getLogger(__name__)


# ai-town: 100 (memory.ts:336)
RECENT_MEMORY_WINDOW = 100

# ai-town: sum > 500 in [0, 9] importance scale (memory.ts:343).
# We use [0, 1] scale → equivalent threshold = 500 / 9 ≈ 55.6 → round to 50
# for slightly easier triggering (closer to ai-town behavior than exact math).
DEFAULT_IMPORTANCE_THRESHOLD = 50.0


def _build_reflection_prompt(
    *, agent_name: str, memories: list[MemoryEvent],
) -> str:
    """1:1 port of ai-town's prompt structure (memory.ts:350-360)."""
    lines = [
        "[no prose]",
        "[Output only JSON]",
        f"You are {agent_name}, statements about you:",
    ]
    for idx, m in enumerate(memories):
        lines.append(f"Statement {idx}: {m.content}")
    lines.append(
        "What 3 high-level insights can you infer from the above statements?"
    )
    lines.append(
        'Return in JSON format, where the key is a list of input statements '
        'that contributed to your insights and value is your insight. Make '
        'the response parseable by JSON.parse() function. DO NOT escape '
        'characters or include "\\n" or white space in response.'
    )
    lines.append(
        'Example: [{"insight": "...", "statementIds": [1,2]}, '
        '{"insight": "...", "statementIds": [1]}, ...]'
    )
    return "\n".join(lines)


class ReflectionService:
    """Triggers + executes reflection passes for an agent.

    Stateless — caller (MemoryService) provides the recent memory window and
    last_reflection_tick. The "should reflect / not reflect" gate is a pure
    function of inputs.
    """

    __slots__ = ("_llm_client", "_importance_scorer", "_embeddings_cache",
                 "_threshold", "_model")

    def __init__(
        self,
        *,
        llm_client: "LLMClient",
        importance_scorer: "ImportanceScorer | None" = None,
        embeddings_cache: "EmbeddingsCache | None" = None,
        importance_threshold: float = DEFAULT_IMPORTANCE_THRESHOLD,
        model: str = "",
    ) -> None:
        self._llm_client = llm_client
        self._importance_scorer = importance_scorer
        self._embeddings_cache = embeddings_cache
        self._threshold = importance_threshold
        self._model = model

    def should_reflect(
        self,
        recent_memories: list[MemoryEvent],
        *,
        last_reflection_time: datetime | None,
        force_for_day_end: bool = False,
    ) -> bool:
        """Return True if the agent should run reflection now.

        Triggers (matching ai-town pattern + day-end addition):
        1. Sum of importance over memories newer than `last_reflection_time` > threshold.
        2. (SSWT addition) `force_for_day_end=True` — orchestrator's on_day_end
           hook can force one reflection per day even if threshold not hit.
        """
        if force_for_day_end:
            return True
        if not recent_memories:
            return False
        cutoff = last_reflection_time
        eligible = (
            recent_memories
            if cutoff is None
            else [m for m in recent_memories if m.simulated_time > cutoff]
        )
        if not eligible:
            return False
        total_importance = sum(m.importance for m in eligible)
        return total_importance > self._threshold

    async def reflect(
        self,
        agent_id: str,
        agent_name: str,
        recent_memories: list[MemoryEvent],
        *,
        current_tick: int,
        simulated_time: datetime,
        day_index: int,
        event_id_factory,  # Callable[[str, int], str]
    ) -> list[MemoryEvent]:
        """Run a reflection pass; return 0+ MemoryEvent[kind="reflection"].

        Never raises — LLM failure / parse failure → empty list + warning log.
        Caller (MemoryService) is responsible for `record()`-ing the events.
        """
        if not recent_memories:
            return []
        # ai-town takes the latest 100 (memory.ts:336)
        window = recent_memories[-RECENT_MEMORY_WINDOW:]
        prompt = _build_reflection_prompt(
            agent_name=agent_name, memories=window,
        )
        try:
            raw = await self._llm_client.generate(prompt, model=self._model)
        except Exception as exc:
            logger.warning("reflect failed (LLM error) for %s: %s", agent_id, exc)
            return []
        try:
            insights = self._parse_insights(raw)
        except Exception as exc:
            logger.warning(
                "reflect failed (parse error) for %s: %s; raw=%r",
                agent_id, exc, raw[:200],
            )
            return []
        if not insights:
            return []

        out: list[MemoryEvent] = []
        for i, item in enumerate(insights):
            insight_text = item.get("insight", "").strip()
            if not insight_text:
                continue
            statement_ids = item.get("statementIds", [])
            # Resolve back to event_ids (clamp out-of-range indices)
            related_ids = tuple(
                window[idx].event_id
                for idx in statement_ids
                if isinstance(idx, int) and 0 <= idx < len(window)
            )
            # Importance scoring: optional (only if scorer available)
            if self._importance_scorer is not None:
                placeholder = MemoryEvent(
                    event_id="placeholder",
                    agent_id=agent_id,
                    tick=current_tick,
                    simulated_time=simulated_time,
                    kind="reflection",
                    content=insight_text,
                )
                importance = await self._importance_scorer.score(placeholder)
            else:
                importance = 0.8  # ai-town default for reflections is high
            # Optional embedding via cache
            embedding: tuple[float, ...] | None = None
            if self._embeddings_cache is not None:
                try:
                    embedding = self._embeddings_cache.fetch(insight_text)
                except Exception as exc:  # pragma: no cover (defensive)
                    logger.warning("embed insight failed: %s", exc)
            out.append(MemoryEvent(
                event_id=event_id_factory(agent_id, current_tick + i),
                agent_id=agent_id,
                tick=current_tick,
                simulated_time=simulated_time,
                kind="reflection",
                content=insight_text,
                day_index=day_index,
                importance=importance,
                tags=("reflection",),
                embedding=embedding,
                related_memory_ids=related_ids,
                last_access=simulated_time,
            ))
        return out

    @staticmethod
    def _parse_insights(raw: str) -> list[dict]:
        """Tolerantly parse ai-town's JSON-array insight format.

        Tolerates:
        - Surrounding markdown code fence ```json ... ```
        - Leading/trailing whitespace
        - "insight" / "statementIds" key spellings
        """
        text = (raw or "").strip()
        if not text:
            return []
        # Strip markdown code fences
        if text.startswith("```"):
            # find first newline → drop ```...; drop trailing ```
            first_nl = text.find("\n")
            if first_nl > 0:
                text = text[first_nl + 1 :]
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3].rstrip()
        # Find first '[' to start, last ']' to end (some LLMs add commentary)
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end <= start:
            return []
        text = text[start : end + 1]
        try:
            data = json.loads(text)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        out: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            insight = item.get("insight") or item.get("Insight")
            ids = item.get("statementIds") or item.get("statement_ids") or []
            if isinstance(insight, str) and isinstance(ids, list):
                out.append({"insight": insight, "statementIds": ids})
        return out


__all__ = ["ReflectionService", "DEFAULT_IMPORTANCE_THRESHOLD"]
