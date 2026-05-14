"""Tests for run_variant_suite's phase_config parsing into reproducibility_lock.

Regression for B8 from docs/audit/2026-05-09-bug-hunt.md: original code did
``phase_days[0]`` on the raw arg string "4,6,4", writing the literal characters
"4", ",", "6" into the lock instead of integers. Fix uses
``_parse_phase_days_to_dict`` which splits and casts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from run_variant_suite import _parse_phase_days_to_dict  # type: ignore

from synthetic_socio_wind_tunnel.metrics.reproducibility import (
    compute_reproducibility_lock,
)


class TestParsePhaseDaysToDict:

    def test_basic_split(self):
        assert _parse_phase_days_to_dict("4,6,4") == {
            "baseline_days": 4, "intervention_days": 6, "post_days": 4,
        }

    def test_with_whitespace(self):
        assert _parse_phase_days_to_dict(" 4 , 6 , 4 ") == {
            "baseline_days": 4, "intervention_days": 6, "post_days": 4,
        }

    def test_returns_ints_not_strings(self):
        pc = _parse_phase_days_to_dict("4,6,4")
        for v in pc.values():
            assert isinstance(v, int)

    def test_wrong_count_raises(self):
        with pytest.raises(ValueError):
            _parse_phase_days_to_dict("4,6")
        with pytest.raises(ValueError):
            _parse_phase_days_to_dict("4,6,4,2")


class TestPhaseConfigInReproducibilityLock:
    """Lock metadata SHALL contain int phase_config (not chars from a raw str)."""

    def test_phase_config_values_are_ints(self):
        pc = _parse_phase_days_to_dict("4,6,4")
        lock = compute_reproducibility_lock(
            seed_pool=[42],
            use_real_llm=False,
            variant_names=["baseline"],
            phase_config=pc,
        )
        stored = lock["phase_config"]
        assert isinstance(stored["baseline_days"], int)
        assert isinstance(stored["intervention_days"], int)
        assert isinstance(stored["post_days"], int)
        assert stored["baseline_days"] >= 0
        assert stored["intervention_days"] >= 0
        assert stored["post_days"] >= 0

    def test_phase_config_no_comma_chars(self):
        """B8 regression: ensure no field is the literal "," character."""
        pc = _parse_phase_days_to_dict("4,6,4")
        lock = compute_reproducibility_lock(
            seed_pool=[42],
            use_real_llm=False,
            variant_names=["baseline"],
            phase_config=pc,
        )
        for v in lock["phase_config"].values():
            assert v != ","
            assert v != "4"
            assert v != "6"
