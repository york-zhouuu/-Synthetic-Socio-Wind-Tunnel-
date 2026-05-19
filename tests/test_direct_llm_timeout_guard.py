"""Regression guard: every direct (non-OperationPool) LLM call site is
wrapped in `asyncio.wait_for` with a fallback path.

This test does NOT execute the LLM call paths end-to-end; it scans the
source files (read-only) and asserts that every `await ...generate(...)`
in the listed files appears inside an `asyncio.wait_for(...)` call.

When this fails, a new direct LLM call point was added without timeout
protection — see backlog 1.9 / CLAUDE.md `monitor-as-control-plane`
related invariants. Add `await asyncio.wait_for(client.generate(...),
timeout=<X>)` + `try/except asyncio.TimeoutError → fallback`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TARGETS = [
    REPO / "synthetic_socio_wind_tunnel/memory/reflection.py",
    REPO / "synthetic_socio_wind_tunnel/memory/importance.py",
    REPO / "synthetic_socio_wind_tunnel/agent/planner.py",
    REPO / "synthetic_socio_wind_tunnel/data_loader/lanecove.py",
]


@pytest.mark.parametrize("source_path", TARGETS, ids=lambda p: p.name)
def test_direct_generate_calls_have_wait_for(source_path: Path) -> None:
    text = source_path.read_text(encoding="utf-8")
    # find every `.generate(` call (broad net)
    generate_matches = list(re.finditer(r"\.generate\(", text))
    assert generate_matches, (
        f"No `.generate(` found in {source_path.name} — either the file "
        f"changed scope or the regex needs updating."
    )

    for m in generate_matches:
        # look backward 200 chars for an asyncio.wait_for opener;
        # generous window because indentation + arg formatting varies
        window = text[max(0, m.start() - 200):m.start()]
        assert "wait_for(" in window, (
            f"{source_path.name}: `.generate(` at char {m.start()} is "
            f"NOT preceded by `wait_for(` within 200 chars. Every direct "
            f"LLM call must be hard-timeout-protected (backlog 1.9 / "
            f"harden-worker-resilience). Window=\n{window!r}"
        )


@pytest.mark.parametrize("source_path", TARGETS, ids=lambda p: p.name)
def test_timeout_error_has_fallback(source_path: Path) -> None:
    """Every wait_for must be followed (within ~30 lines) by an
    `except asyncio.TimeoutError` (or its alias) that yields a fallback,
    not just re-raises."""
    text = source_path.read_text(encoding="utf-8")
    wait_for_matches = list(re.finditer(r"wait_for\(", text))
    if not wait_for_matches:
        pytest.skip(f"no wait_for in {source_path.name}")
    for m in wait_for_matches:
        # look ahead ~1500 chars for the matching except clause
        window = text[m.start():m.start() + 1500]
        assert (
            "TimeoutError" in window
        ), (
            f"{source_path.name}: wait_for at char {m.start()} has no "
            f"TimeoutError handler within 1500 chars."
        )
