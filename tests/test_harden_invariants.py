"""Regression tests for the 3 CLAUDE.md invariants formalized by
harden-worker-resilience:

1. monitor-as-control-plane: tools/resume_publishable.py SHALL NOT call
   os.kill (or any termination signal) on a live worker — it observes
   and reports only.
2. sigusr1-graceful-stop-corruption: tools/run_variant_suite.py SHALL
   skip writing seed_N.json + cleanup_partials when metadata
   `graceful_stop=True`, so partials remain for resume.
3. memory-auto-restart: MultiDayRunner._init_memory_management_hooks
   honors RSS_RESTART_MB env to trigger graceful_stop when over budget,
   and GC_EVERY_N_TICKS to periodically call gc.collect().
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------
# Invariant 1: monitor-as-control-plane
# --------------------------------------------------------------------


def test_resume_publishable_does_not_call_os_kill() -> None:
    """Source-level scan: resume_publishable.py must NOT contain any
    `os.kill(`, `signal.SIGUSR1`, `signal.SIGTERM`, etc. — termination
    authority belongs to human via monitor (CLAUDE.md
    monitor-as-control-plane).
    """
    src = (REPO / "tools" / "resume_publishable.py").read_text()
    # Strip comments to avoid false matches in doc explaining "what NOT to do"
    no_comments = re.sub(r"#.*", "", src)
    # Strip docstrings (triple-quoted) — also explain anti-patterns
    no_docstrings = re.sub(r'"""[\s\S]*?"""', "", no_comments)
    forbidden = ["os.kill(", "signal.SIG", "kill -USR", "kill -TERM"]
    for pattern in forbidden:
        assert pattern not in no_docstrings, (
            f"resume_publishable.py contains forbidden pattern {pattern!r}: "
            f"the monitor-as-control-plane invariant says this script must "
            f"never send termination signals. Use spawn-on-missing only."
        )


def test_resume_publishable_report_only_action_on_stale() -> None:
    """Inspect source: the RUNNING_STALE branch in main() SHALL set
    entry['action'] = 'report_only', not 'sigusr1' or 'kill'.
    """
    src = (REPO / "tools" / "resume_publishable.py").read_text()
    # Locate the literal action line under the RUNNING_STALE branch
    assert 'entry["action"] = "report_only"' in src, (
        "RUNNING_STALE branch must explicitly set "
        '`entry["action"] = "report_only"` to preserve audit trail; '
        "anything else (e.g., 'sigusr1', 'kill', 'terminate') violates "
        "monitor-as-control-plane."
    )
    # Negative: no termination action strings should appear in code
    assert 'entry["action"] = "sigusr1"' not in src
    assert 'entry["action"] = "kill"' not in src


# --------------------------------------------------------------------
# Invariant 2: sigusr1-graceful-stop-corruption
# --------------------------------------------------------------------


def test_run_variant_suite_skips_seed_json_on_graceful_stop() -> None:
    """Source-level: the per-seed write block in run_variant_suite.py
    SHALL be gated by `if graceful_stop: ... else: write seed_N.json +
    cleanup_partials`.
    """
    src = (REPO / "tools" / "run_variant_suite.py").read_text()
    # Find the graceful_stop check near the seed_file write
    assert "graceful_stop" in src, "run_variant_suite.py must reference graceful_stop"
    # Verify the gating structure: graceful_stop branch exists with
    # "NOT written" message; the cleanup_partials call must be inside
    # the else branch.
    assert "GRACEFUL_STOP after" in src, (
        "Expected graceful_stop log message 'GRACEFUL_STOP after K day(s) — "
        "seed_N.json NOT written'"
    )
    # cleanup_partials should be inside the else branch (after seed_file write),
    # not at the top level of the seed loop
    cleanup_idx = src.find("cleanup_partials(")
    seed_file_write_idx = src.find('open(seed_file, "w"')
    assert cleanup_idx > seed_file_write_idx, (
        "cleanup_partials must come AFTER seed_file write (so it only runs "
        "when seed_N.json was actually written)"
    )


# --------------------------------------------------------------------
# Invariant 3: memory-auto-restart
# --------------------------------------------------------------------


def test_rss_threshold_triggers_graceful_stop() -> None:
    """RSS over RSS_RESTART_MB SHALL set _graceful_stop_requested=True."""
    from synthetic_socio_wind_tunnel.orchestrator.multi_day import MultiDayRunner

    runner = MultiDayRunner.__new__(MultiDayRunner)
    runner._graceful_stop_requested = False
    fake_orch_hooks: list = []

    class FakeOrch:
        def register_on_tick_end(self, hook):
            fake_orch_hooks.append(hook)

    runner._orchestrator = FakeOrch()

    with patch.dict(os.environ, {
        "RSS_RESTART_MB": "100",
        "RSS_CHECK_EVERY_N_TICKS": "5",
        "GC_EVERY_N_TICKS": "0",
    }):
        runner._init_memory_management_hooks(ticks_per_day=10)

    assert len(fake_orch_hooks) == 1
    hook = fake_orch_hooks[0]

    # Fire the hook with mock tick_result; the helper reads RSS via
    # resource.getrusage — patch that to return over-budget value.
    class FakeTick:
        day_index = 0
        tick_index = 5  # tick_global = 5, matches RSS_CHECK_EVERY_N_TICKS=5

    # _self_rss_mb() does lazy `import resource` — patch the resource
    # module itself.
    import resource as _resource

    class _RU:
        ru_maxrss = 200 * 1024 * 1024  # darwin: bytes → 200 MB

    with patch.object(_resource, "getrusage", return_value=_RU()), \
         patch("sys.platform", "darwin"):
        hook(FakeTick())

    assert runner._graceful_stop_requested is True


def test_gc_every_n_ticks_invokes_collect() -> None:
    """GC_EVERY_N_TICKS=10 + run to tick_global=20 → gc.collect called ≥ 2."""
    from synthetic_socio_wind_tunnel.orchestrator.multi_day import MultiDayRunner

    runner = MultiDayRunner.__new__(MultiDayRunner)
    runner._graceful_stop_requested = False
    fake_orch_hooks: list = []

    class FakeOrch:
        def register_on_tick_end(self, hook):
            fake_orch_hooks.append(hook)

    runner._orchestrator = FakeOrch()

    with patch.dict(os.environ, {
        "GC_EVERY_N_TICKS": "10",
        "RSS_RESTART_MB": "0",
    }):
        runner._init_memory_management_hooks(ticks_per_day=10)

    hook = fake_orch_hooks[0]

    class FakeTick:
        def __init__(self, day_index, tick_index):
            self.day_index = day_index
            self.tick_index = tick_index

    with patch("synthetic_socio_wind_tunnel.orchestrator.multi_day.gc.collect") as gc_mock:
        gc_mock.return_value = 0
        # tick_global = day_idx*ticks_per_day + tick_idx
        # ticks_per_day=10, day=0/tick=10 → 10; day=1/tick=10 → 20
        hook(FakeTick(0, 10))  # gc fires (tick_global=10 % 10 == 0)
        hook(FakeTick(1, 10))  # gc fires (tick_global=20 % 10 == 0)
        assert gc_mock.call_count == 2


def test_rss_off_by_default_does_not_set_graceful_stop() -> None:
    """RSS_RESTART_MB unset (or 0) → no RSS monitoring, no flag set."""
    from synthetic_socio_wind_tunnel.orchestrator.multi_day import MultiDayRunner

    runner = MultiDayRunner.__new__(MultiDayRunner)
    runner._graceful_stop_requested = False
    fake_orch_hooks: list = []

    class FakeOrch:
        def register_on_tick_end(self, hook):
            fake_orch_hooks.append(hook)

    runner._orchestrator = FakeOrch()

    # Both gc and rss off → method returns early, no hook registered
    with patch.dict(os.environ, {"GC_EVERY_N_TICKS": "0", "RSS_RESTART_MB": "0"}, clear=False):
        runner._init_memory_management_hooks(ticks_per_day=10)

    assert fake_orch_hooks == []
    assert runner._graceful_stop_requested is False
