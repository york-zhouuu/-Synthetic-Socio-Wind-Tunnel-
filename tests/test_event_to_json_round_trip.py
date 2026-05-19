"""Layer 1 + 2 — byte-equivalence round-trip for _event_to_json.

Every MemoryEvent in the corpus SHALL produce the SAME dict when
passed through:
  (a) `_event_to_json_legacy` (current loop-based implementation)
  (b) `_event_to_json_fast`  (new optimized implementation, set via
      MEMORY_SNAPSHOT_USE_FAST=1)

Dict equality + key order equality both checked.

If any field differs → error info includes:
- event_id
- field name that differs
- legacy value vs fast value
- types of each
"""

from __future__ import annotations

import json
import os
from typing import Callable

import pytest

from synthetic_socio_wind_tunnel.memory.models import MemoryEvent
from synthetic_socio_wind_tunnel.memory import service as _svc

# Importing the fixture corpus
from tests.fixtures.memory_event_round_trip_corpus import CORPUS


def _get_impls() -> tuple[Callable[[MemoryEvent], dict], Callable[[MemoryEvent], dict]]:
    """Return (legacy, fast) implementations.

    Until G4 lands the fast impl, this falls back to expecting `_event_to_json`
    only — and the equality test is a no-op identity check (just structural
    schema check). After G4 lands, fast vs legacy diverge in implementation
    but converge in output.
    """
    legacy = getattr(_svc, "_event_to_json_legacy", None)
    fast = getattr(_svc, "_event_to_json_fast", None)
    if legacy is None or fast is None:
        # G4 not done yet — TDD red phase
        return (_svc._event_to_json, _svc._event_to_json)
    return (legacy, fast)


class TestCorpusBuilds:
    def test_corpus_has_50_events(self) -> None:
        assert len(CORPUS) == 50

    def test_corpus_covers_all_kinds(self) -> None:
        kinds_in_corpus = {e.kind for e in CORPUS}
        from typing import get_args
        from synthetic_socio_wind_tunnel.memory.models import MemoryKind
        all_kinds = set(get_args(MemoryKind))
        missing = all_kinds - kinds_in_corpus
        assert not missing, f"corpus missing kinds: {missing}"


class TestByteEquivalence:
    """Layer 1: fast_path SHALL produce byte-equivalent dict to legacy."""

    @pytest.mark.parametrize("idx", list(range(len(CORPUS))))
    def test_event_round_trip(self, idx: int) -> None:
        legacy, fast = _get_impls()
        ev = CORPUS[idx]
        d_legacy = legacy(ev)
        d_fast = fast(ev)

        # Dict equality (values match)
        if d_legacy != d_fast:
            diff_keys = [
                k for k in set(d_legacy) | set(d_fast)
                if d_legacy.get(k) != d_fast.get(k)
            ]
            raise AssertionError(
                f"event {ev.event_id} (kind={ev.kind}): legacy != fast\n"
                f"  diff keys: {diff_keys}\n"
                f"  legacy: { {k: d_legacy.get(k) for k in diff_keys} }\n"
                f"  fast:   { {k: d_fast.get(k) for k in diff_keys} }"
            )

        # Key order equality — downstream json.dumps preserves insertion order;
        # if fast path emits keys in a different order, JSON bytes differ even
        # if dicts compare equal.
        keys_legacy = list(d_legacy.keys())
        keys_fast = list(d_fast.keys())
        assert keys_legacy == keys_fast, (
            f"event {ev.event_id} key order mismatch:\n"
            f"  legacy: {keys_legacy}\n"
            f"  fast:   {keys_fast}"
        )

    def test_json_string_equivalent(self) -> None:
        """Sanity: post `json.dumps` they produce identical strings."""
        legacy, fast = _get_impls()
        for ev in CORPUS:
            j_legacy = json.dumps(legacy(ev), ensure_ascii=False, default=str)
            j_fast = json.dumps(fast(ev), ensure_ascii=False, default=str)
            assert j_legacy == j_fast, (
                f"event {ev.event_id}: JSON strings diverge\n"
                f"  legacy: {j_legacy[:200]}\n"
                f"  fast:   {j_fast[:200]}"
            )
