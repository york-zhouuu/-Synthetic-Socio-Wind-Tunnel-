"""Phase G2 — memstat schema + RSS correctness (no mocking of measurements).

These tests use REAL psutil / gc / resource readings to verify
instrumentation values reflect reality. The ru_maxrss bug went
undetected because previous tests mocked the value source.
"""

from __future__ import annotations

import gc
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_singleton():
    try:
        from synthetic_socio_wind_tunnel.observability import instrumentation
        instrumentation.reset_for_tests()
        yield
        instrumentation.reset_for_tests()
    except ImportError:
        yield


@pytest.fixture
def tmp_output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("INSTRUMENTATION_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("INSTRUMENTATION_SEED", "42")
    return tmp_path


def _read_memstat_lines(out_dir: Path) -> list[dict]:
    f = out_dir / "seed_42.memstat.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l]


def test_rss_mb_matches_psutil_independently(tmp_output_dir: Path) -> None:
    """Sample rss_mb SHALL be within 5% of an independent psutil reading."""
    import psutil
    from synthetic_socio_wind_tunnel.observability import instrumentation

    inst = instrumentation.get_instrumentation()
    inst.sample_metrics(tick_global=12, day_index=0, tick_in_day=12)

    independent_rss_mb = (
        psutil.Process().memory_info().rss // (1024 * 1024)
    )
    samples = _read_memstat_lines(tmp_output_dir)
    assert len(samples) >= 1
    sample_rss = samples[-1]["memory"]["rss_mb"]
    # Within 5% (process growth in microseconds between calls)
    diff_ratio = abs(sample_rss - independent_rss_mb) / max(
        independent_rss_mb, 1,
    )
    assert diff_ratio < 0.05, (
        f"rss_mb={sample_rss} vs psutil={independent_rss_mb} "
        f"diff_ratio={diff_ratio:.3f}"
    )


def test_rss_mb_uses_psutil_current_not_ru_maxrss(
    tmp_output_dir: Path,
) -> None:
    """CRITICAL BUG REGRESSION: rss_mb (current) MUST be a separate
    measurement from rss_peak_mb (ru_maxrss lifetime peak).

    Strategy: use mmap which is guaranteed to release on close (unlike
    pymalloc-retained Python objects). Allocate 500MB via mmap, sample
    at peak, close mmap, sample after. peak.rss_mb SHALL be larger than
    freed.rss_mb if the impl reads psutil current (correct), but they
    SHALL be equal if impl reads ru_maxrss (the bug we're guarding).

    Also verifies fundamental invariant: rss_peak_mb >= rss_mb always.
    """
    import mmap as _mmap
    from synthetic_socio_wind_tunnel.observability import instrumentation

    inst = instrumentation.get_instrumentation()

    # Baseline
    inst.sample_metrics(tick_global=12, day_index=0, tick_in_day=12)

    # Anon mmap 500MB — must touch pages to actually allocate
    block = _mmap.mmap(-1, 500 * 1024 * 1024)
    # Write to force resident
    for off in range(0, 500 * 1024 * 1024, 4096):
        block[off:off + 1] = b"x"
    inst.sample_metrics(tick_global=24, day_index=0, tick_in_day=24)

    # Explicit close → munmap → pages return to OS
    block.close()
    gc.collect()
    inst.sample_metrics(tick_global=36, day_index=0, tick_in_day=36)

    samples = _read_memstat_lines(tmp_output_dir)
    assert len(samples) == 3
    baseline, alloc, freed = samples

    # Invariant 1: peak >= current at all times
    for label, s in [("baseline", baseline), ("alloc", alloc),
                     ("freed", freed)]:
        assert s["memory"]["rss_peak_mb"] >= s["memory"]["rss_mb"], (
            f"{label}: peak {s['memory']['rss_peak_mb']} < "
            f"current {s['memory']['rss_mb']}"
        )

    # Invariant 2: alloc allocated something (>= 200MB delta from baseline)
    assert alloc["memory"]["rss_mb"] - baseline["memory"]["rss_mb"] >= 200, (
        f"baseline={baseline['memory']['rss_mb']} "
        f"alloc={alloc['memory']['rss_mb']} — alloc didn't grow"
    )

    # Invariant 3 (THE BUG REGRESSION): after mmap close, current RSS
    # SHALL drop. If impl reads ru_maxrss (peak), this fails.
    assert freed["memory"]["rss_mb"] < alloc["memory"]["rss_mb"], (
        f"current RSS didn't drop after mmap close: "
        f"alloc={alloc['memory']['rss_mb']}MB → "
        f"freed={freed['memory']['rss_mb']}MB. "
        f"If rss_mb tracks ru_maxrss (peak), this fails."
    )

    # Invariant 4: peak monotonically non-decreasing across samples
    assert (
        freed["memory"]["rss_peak_mb"]
        >= alloc["memory"]["rss_peak_mb"]
    ), "rss_peak_mb should be monotonic non-decreasing"


def test_memstat_schema_has_all_documented_top_level_keys(
    tmp_output_dir: Path,
) -> None:
    """spec: memstat sample has v, ts_iso, tick_global, day_index,
    tick_in_day, memory, cpu, gc, memory_store, dialogue_service,
    llm_health, handler_times_sec."""
    from synthetic_socio_wind_tunnel.observability import instrumentation

    inst = instrumentation.get_instrumentation()
    inst.sample_metrics(tick_global=12, day_index=0, tick_in_day=12)

    samples = _read_memstat_lines(tmp_output_dir)
    assert len(samples) == 1
    s = samples[0]
    required = {
        "v", "ts_iso", "ts_monotonic", "tick_global", "day_index",
        "tick_in_day", "memory", "cpu", "gc", "memory_store",
        "dialogue_service", "llm_health", "handler_times_sec",
    }
    missing = required - set(s.keys())
    assert not missing, f"missing top-level keys: {missing}"

    # memory submap
    mem_required = {"rss_mb", "vms_mb", "rss_peak_mb", "threads"}
    missing_mem = mem_required - set(s["memory"].keys())
    assert not missing_mem, f"memory missing: {missing_mem}"

    # cpu submap
    cpu_required = {
        "percent_recent", "user_sec", "sys_sec",
        "wall_since_last_sample_sec", "tick_count_since_last_sample",
    }
    missing_cpu = cpu_required - set(s["cpu"].keys())
    assert not missing_cpu, f"cpu missing: {missing_cpu}"


def test_sample_cadence_respects_env_n_ticks(
    tmp_output_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If env says sample every 50 ticks, calling sample_metrics 10×
    SHALL still produce 10 lines (cadence enforcement is at the caller,
    here we just verify the API records every call)."""
    from synthetic_socio_wind_tunnel.observability import instrumentation
    inst = instrumentation.get_instrumentation()
    for tick in (50, 100, 150, 200):
        inst.sample_metrics(tick_global=tick, day_index=0, tick_in_day=tick)
    samples = _read_memstat_lines(tmp_output_dir)
    assert len(samples) == 4


def test_psutil_unavailable_logs_warning_and_falls_back(
    tmp_output_dir: Path, caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If psutil import fails, SHALL fall back to ru_maxrss with warning."""
    import builtins
    real_import = builtins.__import__

    def _patched_import(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("simulated missing psutil")
        return real_import(name, *args, **kwargs)

    # Reset singleton + patch import
    from synthetic_socio_wind_tunnel.observability import instrumentation
    instrumentation.reset_for_tests()

    import logging
    with caplog.at_level(logging.WARNING):
        with monkeypatch.context() as mp:
            mp.setattr(builtins, "__import__", _patched_import)
            inst = instrumentation.get_instrumentation()
            inst.sample_metrics(tick_global=12, day_index=0, tick_in_day=12)

    # SHALL log warning about psutil unavailable
    warns = [
        r for r in caplog.records
        if "psutil" in r.message.lower() or "peak" in r.message.lower()
    ]
    assert len(warns) >= 1
    # And SHALL still produce a sample (fallback path)
    assert len(_read_memstat_lines(tmp_output_dir)) >= 1
