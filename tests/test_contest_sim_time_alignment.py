"""2026-05-21 sim-time alignment regression.

Watchdog auto-resume can load a snapshot whose ledger.current_time
diverged from other variants' day 0 start_date — causing different
sim-time windows across variants. Without detection, raw cross-variant
contest comparison is confounded by calendar offset (different weekdays
covered = different baseline encounter density, etc).

These tests verify:
- ContestReport flags `sim_time_misaligned=True` when variants have
  different sim-time windows
- Overlap window is correctly computed (max start, min end)
- When all variants aligned, no flag set
- write_markdown emits the alignment warning banner when flagged
"""

from __future__ import annotations

from pathlib import Path

from synthetic_socio_wind_tunnel.metrics import (
    SuiteAggregate,
    build_contest_report,
)
from synthetic_socio_wind_tunnel.metrics.report import write_markdown


def _make_agg(
    name: str, *, start: str | None = None, end: str | None = None,
) -> SuiteAggregate:
    """Helper — minimal SuiteAggregate with optional sim-time window."""
    return SuiteAggregate(
        variant_name=name,
        seed_count=30,
        seeds=tuple(range(30)),
        per_metric_stats={
            "encounter.per_day_median": {
                "median": 100.0, "iqr_lo": 97.0, "iqr_hi": 103.0,
                "ci95_lo": 95.0, "ci95_hi": 105.0,
            },
        },
        variant_metadata={"name": name},
        sim_time_start_iso=start,
        sim_time_end_iso=end,
    )


def test_aligned_windows_no_misalignment_flag():
    """All variants with identical sim-time windows → no warning."""
    aggs = {
        "baseline": _make_agg("baseline", start="2026-04-22", end="2026-05-05"),
        "hyperlocal_push": _make_agg(
            "hyperlocal_push", start="2026-04-22", end="2026-05-05",
        ),
    }
    contest = build_contest_report(aggs, suite_name="t_aligned")
    assert contest.sim_time_misaligned is False
    assert contest.sim_time_overlap_days is None
    assert contest.sim_time_overlap_start_iso is None


def test_misaligned_start_triggers_warning():
    """When start dates differ, flag and compute overlap."""
    aggs = {
        "baseline": _make_agg("baseline", start="2026-04-22", end="2026-05-05"),
        # gd starts 1 day later (e.g. watchdog resumed from later snapshot)
        "global_distraction": _make_agg(
            "global_distraction", start="2026-04-23", end="2026-05-06",
        ),
    }
    contest = build_contest_report(aggs, suite_name="t_misalign")
    assert contest.sim_time_misaligned is True
    # Overlap: max(start) = 2026-04-23, min(end) = 2026-05-05 → 13 days
    assert contest.sim_time_overlap_start_iso == "2026-04-23"
    assert contest.sim_time_overlap_end_iso == "2026-05-05"
    assert contest.sim_time_overlap_days == 13.0


def test_misaligned_end_triggers_warning():
    """When end dates differ (one ran fewer days), flag + overlap."""
    aggs = {
        "baseline": _make_agg("baseline", start="2026-04-22", end="2026-05-05"),
        "phone_friction": _make_agg(
            "phone_friction", start="2026-04-22", end="2026-04-30",
        ),
    }
    contest = build_contest_report(aggs, suite_name="t_short_end")
    assert contest.sim_time_misaligned is True
    assert contest.sim_time_overlap_start_iso == "2026-04-22"
    assert contest.sim_time_overlap_end_iso == "2026-04-30"
    assert contest.sim_time_overlap_days == 9.0


def test_no_sim_time_info_no_flag():
    """When all variants lack sim_time info (legacy), no flag (back-compat)."""
    aggs = {
        "baseline": _make_agg("baseline"),  # no start/end
        "hyperlocal_push": _make_agg("hyperlocal_push"),
    }
    contest = build_contest_report(aggs, suite_name="t_legacy")
    assert contest.sim_time_misaligned is False
    assert contest.sim_time_overlap_days is None


def test_write_markdown_emits_alignment_warning(tmp_path: Path):
    """report.md SHALL include the alignment warning when flagged."""
    aggs = {
        "baseline": _make_agg("baseline", start="2026-04-22", end="2026-05-05"),
        "global_distraction": _make_agg(
            "global_distraction", start="2026-04-23", end="2026-05-06",
        ),
    }
    contest = build_contest_report(aggs, suite_name="t_warning")
    write_markdown(contest, aggs, tmp_path)
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    # Banner present
    assert "sim-time misalignment detected" in text
    # Overlap window present
    assert "2026-04-23" in text
    assert "13" in text  # overlap days
    # Each variant's window listed
    assert "baseline" in text
    assert "global_distraction" in text


def test_write_markdown_no_warning_when_aligned(tmp_path: Path):
    """When aligned, no alignment banner in report."""
    aggs = {
        "baseline": _make_agg("baseline", start="2026-04-22", end="2026-05-05"),
        "phone_friction": _make_agg(
            "phone_friction", start="2026-04-22", end="2026-05-05",
        ),
    }
    contest = build_contest_report(aggs, suite_name="t_clean")
    write_markdown(contest, aggs, tmp_path)
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "sim-time misalignment detected" not in text
