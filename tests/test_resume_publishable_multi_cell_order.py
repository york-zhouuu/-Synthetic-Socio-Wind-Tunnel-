"""Layer 1 — multi-cell serial selection (Phase G2 of stagger-worker-spawn).

Spec: openspec/specs/worker-spawn-coordination/spec.md
Requirement: "多 INTERRUPTED cell 串行处理顺序"

resume_publishable.main() SHALL process up to 1 INTERRUPTED cell per
LaunchAgent fire when spacing guard is active; the remaining cells get
action="deferred_due_to_stagger" in the report.

TDD red phase: main() doesn't honor the guard yet.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def fake_suite(tmp_path: Path) -> Path:
    """Build a fake suite directory with 4 INTERRUPTED cells (different variants).

    Each variant_<v>/seed_42_tickN.snapshot.json exists, no live worker,
    no seed_42.json — that's _cell_state's INTERRUPTED signature.
    """
    suite = tmp_path / "fake_suite"
    for variant in ("baseline", "global_distraction", "hyperlocal_push",
                    "phone_friction"):
        vdir = suite / f"variant_{variant}"
        vdir.mkdir(parents=True)
        # snapshot file = INTERRUPTED state hint
        (vdir / "seed_42_tick100.snapshot.json").write_text("{}")
    return suite


def _run_main_with_args(
    suite_path: Path, tmp_timestamp: Path, monkeypatch: pytest.MonkeyPatch,
    extra_args: list[str] | None = None,
) -> tuple[int, list[dict]]:
    """Invoke resume_publishable.main() in dry-run mode and capture report."""
    from tools import resume_publishable

    monkeypatch.setenv("SPAWN_STAGGER_TIMESTAMP_FILE", str(tmp_timestamp))

    # Capture stdout to extract JSON report (main uses print + indent=2)
    captured: list[dict] = []
    import io
    import contextlib

    buf = io.StringIO()

    argv = [
        "--suite", f"{suite_path}=42",
        "--variants", "baseline,global_distraction,hyperlocal_push,phone_friction",
        "--dry-run",
        "--json",
        "--log-file", str(tmp_timestamp.parent / "main.log"),
    ]
    if extra_args:
        argv.extend(extra_args)

    with contextlib.redirect_stdout(buf):
        rc = resume_publishable.main(argv)

    # Extract JSON from captured stdout (main emits indent=2 JSON)
    text = buf.getvalue()
    # Find first '{' and last '}' — JSON is the multi-line block between
    if "{" in text and "}" in text:
        json_start = text.index("{")
        json_end = text.rindex("}") + 1
        try:
            parsed = json.loads(text[json_start:json_end])
            captured.append(parsed)
        except json.JSONDecodeError:
            pass

    return rc, captured[-1]["cells"] if captured else []


def test_4_interrupted_cells_only_first_spawned_dict_order(
    fake_suite: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """spec: 字典序第 1 个 spawn，剩 3 个 deferred_due_to_stagger."""
    tmp_ts = tmp_path / "spawn-ts.json"
    rc, report = _run_main_with_args(fake_suite, tmp_ts, monkeypatch)
    # exit code 1 = at least 1 cell incomplete (3 deferred + 1 spawned still
    # not DONE in this fake setup)
    assert rc == 1
    assert len(report) == 4

    by_variant = {e["variant"]: e for e in report}
    # Alphabetical order: baseline, global_distraction, hyperlocal_push,
    # phone_friction. First in dict order is `baseline` — it SHALL be spawned.
    assert by_variant["baseline"]["action"] == "spawn_resume"
    for v in ("global_distraction", "hyperlocal_push", "phone_friction"):
        assert by_variant[v]["action"] == "deferred_due_to_stagger", (
            f"{v} should be deferred but got {by_variant[v]['action']}"
        )


def test_deferred_cells_get_next_eligible_time(
    fake_suite: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """spec: deferred entry SHALL include next_eligible_iso."""
    tmp_ts = tmp_path / "spawn-ts.json"
    _, report = _run_main_with_args(fake_suite, tmp_ts, monkeypatch)
    deferred = [e for e in report if e.get("action") == "deferred_due_to_stagger"]
    assert len(deferred) == 3
    for e in deferred:
        assert "next_eligible_iso" in e
        assert isinstance(e["next_eligible_iso"], str)
        assert "T" in e["next_eligible_iso"]  # ISO-8601 marker


def test_subsequent_run_picks_up_remaining_cells(
    fake_suite: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """spec: 下个 LaunchAgent 周期重新评估，仍 INTERRUPTED 的 cell 处理.

    Simulate: timestamp file shows last spawn was 400s ago → fresh tick
    should be allowed to spawn the next-alphabetical cell.
    """
    import time
    tmp_ts = tmp_path / "spawn-ts.json"
    # Pretend baseline was spawned 400s ago
    tmp_ts.write_text(json.dumps({
        "last_spawn_epoch": time.time() - 400,
        "last_spawn_iso": "2026-05-19T12:00:00+00:00",
        "last_spawn_cell": {"seed": 42, "variant": "baseline"},
        "version": 1,
    }))
    _, report = _run_main_with_args(fake_suite, tmp_ts, monkeypatch)
    # baseline still INTERRUPTED (we didn't really spawn last time, dry-run),
    # so dict-order picks baseline again. The test point is: spacing guard
    # is NOT blocking (400s > 300s default) → action="spawn_resume" on
    # the first cell again.
    by_variant = {e["variant"]: e for e in report}
    assert by_variant["baseline"]["action"] == "spawn_resume"


def test_env_zero_spawns_all_cells_in_one_run(
    fake_suite: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """spec: env override 关闭 spacing — all 4 cells get spawn_resume in one run."""
    monkeypatch.setenv("RESILIENCE_MIN_SPAWN_SPACING_SECS", "0")
    tmp_ts = tmp_path / "spawn-ts.json"
    _, report = _run_main_with_args(fake_suite, tmp_ts, monkeypatch)
    # With env=0, all 4 cells SHALL spawn (no deferred)
    spawn_count = sum(1 for e in report if e.get("action") == "spawn_resume")
    deferred_count = sum(
        1 for e in report if e.get("action") == "deferred_due_to_stagger"
    )
    assert spawn_count == 4, f"expected 4 spawn_resume, got {spawn_count}"
    assert deferred_count == 0
