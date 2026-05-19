"""Layer 1 — ThreadPool staggered submit (Phase G3 of stagger-worker-spawn).

Spec: openspec/specs/worker-spawn-coordination/spec.md
Requirement: "run_variant_suite ThreadPool 内部 stagger"

`run_variant_suite.py` SHALL expose a `_staggered_submit(pool, fn,
items, spacing_secs)` helper that submits items with `spacing_secs`
between submissions; spacing=0 disables sleep.

TDD red phase: helper doesn't exist yet.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest


def _get_helper():
    """Import the staggered submit helper (added by G6)."""
    from tools.run_variant_suite import _staggered_submit
    return _staggered_submit


def test_helper_exists() -> None:
    """G6 SHALL add `_staggered_submit` to run_variant_suite module."""
    helper = _get_helper()
    assert callable(helper)


def test_4_workers_submitted_with_spacing() -> None:
    """spec scenario: 4 variants × workers=4 staggered submit.

    With spacing=0.5s, 4 calls SHALL be submitted at t≈0, 0.5, 1.0, 1.5;
    helper returns immediately when submitting (doesn't wait for fn results).
    Total elapsed in test SHALL be ~1.5s ± jitter.
    """
    helper = _get_helper()
    submit_times: list[float] = []
    fn_call_times: list[float] = []
    start = time.perf_counter()

    def _track_fn(item: str) -> str:
        fn_call_times.append(time.perf_counter() - start)
        return item

    # Wrap pool.submit to record submission time
    real_pool = ThreadPoolExecutor(max_workers=4)
    real_submit = real_pool.submit

    def _tracking_submit(fn, *args, **kwargs):
        submit_times.append(time.perf_counter() - start)
        return real_submit(fn, *args, **kwargs)

    with real_pool as p:
        p.submit = _tracking_submit  # type: ignore[assignment]
        futures = helper(p, _track_fn, ["a", "b", "c", "d"], spacing_secs=0.5)
        for f in futures:
            f.result()

    assert len(submit_times) == 4
    # First submit at t≈0, subsequent at +0.5s each
    assert submit_times[0] < 0.2
    assert 0.4 < submit_times[1] < 0.7
    assert 0.9 < submit_times[2] < 1.2
    assert 1.4 < submit_times[3] < 1.7


def test_env_zero_no_sleep() -> None:
    """spec scenario: spacing=0 ThreadPool 不 sleep — all 4 submitted within 0.2s."""
    helper = _get_helper()
    submit_times: list[float] = []
    start = time.perf_counter()

    real_pool = ThreadPoolExecutor(max_workers=4)
    real_submit = real_pool.submit

    def _tracking_submit(fn, *args, **kwargs):
        submit_times.append(time.perf_counter() - start)
        return real_submit(fn, *args, **kwargs)

    with real_pool as p:
        p.submit = _tracking_submit  # type: ignore[assignment]
        futures = helper(p, lambda x: x, ["a", "b", "c", "d"], spacing_secs=0)
        for f in futures:
            f.result()

    assert len(submit_times) == 4
    # All submitted within 0.2s
    assert max(submit_times) - min(submit_times) < 0.2


def test_returns_futures_in_submission_order() -> None:
    """Helper SHALL return futures in input-list order so caller can
    correlate."""
    helper = _get_helper()
    with ThreadPoolExecutor(max_workers=4) as p:
        futures = helper(p, lambda x: x, ["a", "b", "c"], spacing_secs=0)
        results = [f.result() for f in futures]
    assert results == ["a", "b", "c"]


def test_single_item_no_sleep_regardless_of_spacing() -> None:
    """Edge case: 1 item shouldn't trigger any sleep (no "between" submissions)."""
    helper = _get_helper()
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=1) as p:
        futures = helper(p, lambda x: x, ["only"], spacing_secs=10)
        futures[0].result()
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"single item shouldn't sleep, took {elapsed}s"
