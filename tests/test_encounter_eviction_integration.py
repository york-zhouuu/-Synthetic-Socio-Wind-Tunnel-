"""Integration test — encounter events SHALL survive eviction within
grace window.

This test would have caught the 2026-05-20 04:00 bug where
`MemoryEvent.tick` (per-day 0-287) was being compared against
`before_tick` (global cutoff like 2880), evicting ALL encounter events
every single eviction cycle.

Spec: openspec/specs/memory-event-eviction/spec.md
Requirement: "encounter events SHALL accumulate in grace_days window"

Why subprocess dev smoke: previous 6 mock-based unit tests passed
because they used hand-crafted events with explicit small tick values.
The bug emerged only when caller (multi_day.py with global cutoff
arithmetic) met callee (MemoryStore filter assuming per-day tick) at
integration time. **Reading a real snapshot artifact is the gate
that catches this class of caller-callee semantic mismatch.**
"""

from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]


def _run_dev_smoke(
    tmp_path: Path, *,
    suite_name: str,
    num_days: int = 3,
    agents: int = 50,
    grace_days: int = 2,
) -> Path:
    """Run dev smoke subprocess; return suite output dir."""
    env = os.environ.copy()
    env.pop("INSTRUMENTATION_OUTPUT_DIR", None)
    env["INSTRUMENTATION_DISABLE"] = "1"  # avoid noise
    env["LLM_SAMPLE_RATE"] = "0"
    env["MEMORY_EVENT_EVICT_GRACE_DAYS"] = str(grace_days)
    env["SNAPSHOT_PRUNE_BEFORE_WRITE"] = "1"
    env["RESILIENCE_SNAPSHOT_EVERY_TICKS"] = "24"

    cmd = [
        sys.executable, "tools/run_variant_suite.py",
        "--variants", "baseline",
        "--seeds", "1", "--seed-start", "42",
        "--num-days", str(num_days),
        "--agents", str(agents),
        "--num-protagonists", str(max(10, agents // 2)),
        "--mode", "dev",
        "--phase-days", f"{num_days},0,0" if num_days <= 1 else "1,1,1",
        "--output-dir", str(tmp_path),
        "--suite-name", suite_name,
        "--skip-preflight",
    ]
    result = subprocess.run(
        cmd, env=env, capture_output=True, text=True,
        timeout=240, cwd=str(_REPO),
    )
    assert result.returncode == 0, (
        f"smoke failed rc={result.returncode}\n"
        f"stderr={result.stderr[-2000:]}"
    )
    suite_dirs = list(tmp_path.glob(f"*_{suite_name}"))
    assert len(suite_dirs) == 1
    return suite_dirs[0] / "variant_baseline"


def _latest_snapshot(out_dir: Path) -> Path:
    """Return the highest-tick snapshot file. dev smoke normal completion
    doesn't write `tick_final`, only periodic ticks."""
    candidates = []
    for p in out_dir.glob("seed_42_tick*.snapshot.json"):
        name = p.stem
        if name.endswith("tick_final.snapshot"):
            return p
        try:
            tick_n = int(name.rsplit("_tick", 1)[-1].split(".")[0])
            candidates.append((tick_n, p))
        except (ValueError, IndexError):
            continue
    assert candidates, f"no snapshots in {out_dir}"
    return sorted(candidates)[-1][1]


def _aggregate_kinds(snapshot_path: Path) -> tuple[
    collections.Counter, dict[int, collections.Counter]
]:
    """Read snapshot.json; aggregate event kinds total + per-day-index."""
    with open(snapshot_path) as f:
        snap = json.load(f)
    ae = snap["memory_store_state"]["agent_events"]
    total_kinds: collections.Counter = collections.Counter()
    by_day_kind: dict[int, collections.Counter] = collections.defaultdict(
        collections.Counter,
    )
    for aid, events in ae.items():
        for e in events:
            k = e.get("kind", "?")
            d = e.get("day_index", -1)
            total_kinds[k] += 1
            by_day_kind[d][k] += 1
    return total_kinds, dict(by_day_kind)


@pytest.mark.slow
def test_encounter_events_present_after_3day_smoke(tmp_path: Path) -> None:
    """REGRESSION GATE for 2026-05-20 04:00 bug.

    After 3-day dev smoke with grace=1, encounter events for day
    1 and day 2 SHALL survive eviction (day 0 evicted).

    Under the bug: all encounter events evicted regardless of day_index.
    Under the fix: day_index >= (current_day - grace) preserved.
    """
    out_dir = _run_dev_smoke(
        tmp_path, suite_name="enc_smoke3", num_days=3, agents=30,
        grace_days=1,
    )
    final_snap = _latest_snapshot(out_dir)
    assert final_snap.exists(), (
        f"snapshot missing at {final_snap}; dir: {list(out_dir.iterdir())}"
    )

    total_kinds, by_day = _aggregate_kinds(final_snap)
    # CORE INVARIANT: encounter events EXIST
    assert total_kinds.get("encounter", 0) > 0, (
        f"encounter events absent from memory_store after 3-day smoke. "
        f"This is the 2026-05-20 bug regression. "
        f"All kinds: {dict(total_kinds)}"
    )


@pytest.mark.slow
def test_encounter_events_outside_grace_evicted(tmp_path: Path) -> None:
    """day_index outside grace window SHALL be evicted (= 0 events).

    With num_days=3, grace=1: at final state day_index=2, evict
    before_day_index = max(0, 2-1) = 1. So day_index 0 evicted,
    day_index 1 and 2 preserved.
    """
    out_dir = _run_dev_smoke(
        tmp_path, suite_name="enc_outside", num_days=3, agents=30,
        grace_days=1,
    )
    final_snap = _latest_snapshot(out_dir)
    _, by_day = _aggregate_kinds(final_snap)

    # day 0 encounter SHALL be evicted (= 0)
    day_0_encounters = by_day.get(0, collections.Counter()).get("encounter", 0)
    assert day_0_encounters == 0, (
        f"day 0 encounter events should be evicted (grace=1, current "
        f"day=2), got {day_0_encounters}"
    )


@pytest.mark.slow
def test_encounter_events_within_grace_preserved(tmp_path: Path) -> None:
    """day_index within grace window SHALL be preserved."""
    out_dir = _run_dev_smoke(
        tmp_path, suite_name="enc_within", num_days=3, agents=30,
        grace_days=1,
    )
    final_snap = _latest_snapshot(out_dir)
    _, by_day = _aggregate_kinds(final_snap)

    # day 2 (the final day) encounter SHALL be present
    day_2_encounters = by_day.get(2, collections.Counter()).get("encounter", 0)
    assert day_2_encounters > 0, (
        f"day 2 encounter events should be preserved (current day, "
        f"within grace), got {day_2_encounters}. by_day: {dict(by_day)}"
    )
