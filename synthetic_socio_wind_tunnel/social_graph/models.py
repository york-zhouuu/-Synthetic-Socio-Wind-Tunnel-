"""Tie — pairwise relationship between two agents (frozen)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tie:
    """Pairwise tie between two agents.

    Invariants:
    - `agent_a < agent_b` (lexicographic) — canonical ordering ensures dedup.
    - `encounter_count >= 1`.
    - `strength` is monotonic in `encounter_count`; computed by service via
      formula `N / (N + K)`.
    - `first_seen_*` set on creation, never modified.
    - `last_seen_tick` is the most recent encounter tick.

    Frozen: state changes via `dataclasses.replace(...)` to a new instance.
    """

    agent_a: str
    agent_b: str
    encounter_count: int
    strength: float
    first_seen_tick: int
    last_seen_tick: int
    first_seen_day: int

    def __post_init__(self) -> None:
        if self.agent_a >= self.agent_b:
            raise ValueError(
                f"Tie pair must satisfy agent_a < agent_b (lex); "
                f"got a={self.agent_a!r}, b={self.agent_b!r}"
            )
        if self.encounter_count < 1:
            raise ValueError(f"encounter_count must be ≥ 1, got {self.encounter_count}")


def canonical_pair(a: str, b: str) -> tuple[str, str]:
    """Return (a, b) with smaller-lex first.

    Two agents passed in any order produce the same canonical key — used for
    dict dedup.
    """
    if a == b:
        raise ValueError(f"cannot form tie with same agent on both sides: {a!r}")
    return (a, b) if a < b else (b, a)
