"""LLMHealthTracker — rolling fallback-rate budget for publishable runs.

Capability 1.13 (2026-05-19) — born out of D2 attempt 4's "silent
disaster": 4 workers ran 16+ hours in 100% LLM-fallback mode because
DeepSeek balance ran dry. Each per-call fallback was correctly logged
as a warning, but there was no aggregator and no abort budget — the run
looked healthy from outside while producing template-everywhere garbage.

Design:
- Handlers (do_something, reflect, importance, replan, …) call
  `record_success()` / `record_fallback()` on a process-singleton
  tracker after each LLM operation.
- MultiDayRunner asks the tracker on on_tick_end whether the rolling
  window fallback rate exceeds the budget. If yes for N consecutive
  ticks, raise `FallbackBudgetExceeded` — runner writes a partial and
  surfaces the error (graceful abort with non-zero exit).
- AllKeysOpenError (from circuit_breaker.py) is special: it signals
  structural failure (all 8 keys cooldown'd) and is NOT counted as a
  per-call fallback — it short-circuits the budget and aborts faster.

Default budget: rolling 5-minute window; abort if fallback rate > 20%
for 12 consecutive ticks (~5 min at 24s/tick). Override via env vars or
constructor args.

Not threadsafe in a strict sense — the simulation is single-event-loop;
all handler `record_*` calls happen on the orchestrator thread. Counters
use simple int += 1 which is atomic under CPython's GIL.
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


class FallbackBudgetExceeded(RuntimeError):
    """Raised by MultiDayRunner when rolling fallback rate breaches budget.

    Carries the observed rate + the threshold so callers (and partial
    writers) can record exactly what tripped the abort.
    """

    def __init__(
        self,
        *,
        observed_rate: float,
        max_rate: float,
        ticks_breached: int,
        window_secs: float,
    ) -> None:
        super().__init__(
            f"fallback budget exceeded: observed={observed_rate:.1%} > "
            f"max={max_rate:.1%} for {ticks_breached} consecutive ticks "
            f"(rolling window={window_secs:.0f}s)",
        )
        self.observed_rate = observed_rate
        self.max_rate = max_rate
        self.ticks_breached = ticks_breached
        self.window_secs = window_secs


@dataclass
class _Sample:
    """A single LLM-call outcome, time-stamped via monotonic clock."""
    t: float  # monotonic seconds
    fallback: bool  # True if this call resolved via fallback


@dataclass
class LLMHealthTracker:
    """Per-process singleton tracking LLM call outcomes.

    Args:
        window_secs: Rolling window in monotonic seconds.
        max_fallback_rate: Abort when rolling rate > this for N ticks.
        ticks_to_breach: Consecutive ticks-over-budget required to trip.

    Defaults from env:
        FALLBACK_BUDGET_WINDOW_SECS (default 300.0)
        FALLBACK_BUDGET_MAX_RATE    (default 0.20 = 20%)
        FALLBACK_BUDGET_TICKS       (default 12)
    """

    window_secs: float = 300.0
    max_fallback_rate: float = 0.20
    ticks_to_breach: int = 12

    _samples: deque[_Sample] = field(default_factory=deque)
    _consecutive_breached_ticks: int = 0
    _all_keys_open_count: int = 0

    @classmethod
    def from_env(cls) -> LLMHealthTracker:
        def _float(name: str, default: float) -> float:
            raw = os.environ.get(name)
            if raw is None:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        def _int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            if raw is None:
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        return cls(
            window_secs=_float("FALLBACK_BUDGET_WINDOW_SECS", 300.0),
            max_fallback_rate=_float("FALLBACK_BUDGET_MAX_RATE", 0.20),
            ticks_to_breach=_int("FALLBACK_BUDGET_TICKS", 12),
        )

    # ---- recording ----

    def record_success(self) -> None:
        self._samples.append(_Sample(t=time.monotonic(), fallback=False))
        self._evict_old()

    def record_fallback(self) -> None:
        self._samples.append(_Sample(t=time.monotonic(), fallback=True))
        self._evict_old()

    def record_all_keys_open(self) -> None:
        """Distinct counter for AllKeysOpenError — structural, not per-call."""
        self._all_keys_open_count += 1
        # Also count as fallback so rolling rate reflects reality.
        self.record_fallback()

    def _evict_old(self) -> None:
        cutoff = time.monotonic() - self.window_secs
        while self._samples and self._samples[0].t < cutoff:
            self._samples.popleft()

    # ---- query ----

    def rolling_rate(self) -> tuple[float, int]:
        """Return (fallback_rate, n_samples) over the current window."""
        self._evict_old()
        n = len(self._samples)
        if n == 0:
            return (0.0, 0)
        fb = sum(1 for s in self._samples if s.fallback)
        return (fb / n, n)

    def all_keys_open_count(self) -> int:
        return self._all_keys_open_count

    # ---- tick-level budget check ----

    def check_budget(self, *, min_samples: int = 50) -> None:
        """Raise FallbackBudgetExceeded if rate has breached for N ticks.

        Called by MultiDayRunner.on_tick_end (or equivalent). Increments
        an internal counter each call where rate exceeds threshold;
        resets to 0 on a healthy tick. Trips only when the counter
        reaches `ticks_to_breach`.

        `min_samples` guards against early-tick spikes when very few
        LLM calls have happened (e.g., the first 30 seconds of a run).
        """
        rate, n = self.rolling_rate()
        if n < min_samples:
            return
        if rate > self.max_fallback_rate:
            self._consecutive_breached_ticks += 1
            if self._consecutive_breached_ticks >= self.ticks_to_breach:
                raise FallbackBudgetExceeded(
                    observed_rate=rate,
                    max_rate=self.max_fallback_rate,
                    ticks_breached=self._consecutive_breached_ticks,
                    window_secs=self.window_secs,
                )
        else:
            self._consecutive_breached_ticks = 0

    def reset_counter(self) -> None:
        """Clear consecutive-breach counter (e.g., on resume from snapshot)."""
        self._consecutive_breached_ticks = 0


# ---- module-level singleton (process scope) ----

_GLOBAL: Optional[LLMHealthTracker] = None


def get_tracker() -> LLMHealthTracker:
    """Return process-wide LLMHealthTracker, lazily initialized from env."""
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = LLMHealthTracker.from_env()
    return _GLOBAL


def reset_tracker_for_tests() -> None:
    """Used by tests to start each test with a clean tracker."""
    global _GLOBAL
    _GLOBAL = None


__all__ = [
    "FallbackBudgetExceeded",
    "LLMHealthTracker",
    "get_tracker",
    "reset_tracker_for_tests",
]
