"""CLAUDE.md invariant regression tests (2026-05-21).

CLAUDE.md is the operator-facing source of truth for spawn / monitor /
ops procedures. Multiple invariants documented there exist as plain
prose and shell templates that can silently drift from the canonical
specs. These regression tests parse CLAUDE.md and assert key
constraints.

Each test maps 1:1 to a documented invariant.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLAUDE_MD = _REPO_ROOT / "CLAUDE.md"


@pytest.fixture(scope="module")
def claude_md_text() -> str:
    return _CLAUDE_MD.read_text(encoding="utf-8")


def test_publishable_spawn_template_uses_300s_stagger(claude_md_text: str):
    """fix-spawn-stagger-default (2026-05-21).

    `CLAUDE.md` 正式 publishable cell spawn 步骤's shell `for V` loop
    SHALL `sleep` ≥ 300s between variant spawns. 60s stagger
    triggered the 2026-05-20 burst self-DDoS hang cascade.

    Spec: openspec/specs/worker-spawn-coordination/spec.md
    Reference invariant: snapshot-resume-ram-peak + spawn-burst-self-DDoS
    """
    # Find the publishable spawn shell template — section "正式
    # publishable cell spawn 步骤" with "### 1. Worker 主进程"
    spawn_block_re = re.compile(
        r"### 1\. Worker 主进程.*?(?=^### |^## )",
        re.MULTILINE | re.DOTALL,
    )
    m = spawn_block_re.search(claude_md_text)
    assert m, "spawn block 找不到 — CLAUDE.md section heading changed?"
    block = m.group(0)

    # Find `for V in ... do ... done` loops within this block
    for_loop_re = re.compile(
        r"for V in [^\n]*?do(.*?)done",
        re.MULTILINE | re.DOTALL,
    )
    loops = list(for_loop_re.finditer(block))
    assert loops, "Expected at least one `for V` loop in spawn template"

    # For each loop, find any `sleep <N>` statements
    sleep_re = re.compile(r"\bsleep\s+(\d+)\b")
    violations: list[str] = []
    for i, loop_match in enumerate(loops):
        loop_body = loop_match.group(1)
        for sleep_match in sleep_re.finditer(loop_body):
            n = int(sleep_match.group(1))
            if n < 300:
                violations.append(
                    f"loop {i}: sleep {n} (need ≥ 300 per "
                    f"worker-spawn-coordination spec; 60s caused 2026-05-20 "
                    f"hang cascade)"
                )
    assert not violations, (
        "CLAUDE.md publishable spawn template has under-staggered sleep:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_publishable_spawn_has_at_least_one_sleep(claude_md_text: str):
    """Sanity: the spawn template SHOULD have some sleep
    (zero-stagger = burst = guaranteed hang)."""
    spawn_block_re = re.compile(
        r"### 1\. Worker 主进程.*?(?=^### |^## )",
        re.MULTILINE | re.DOTALL,
    )
    m = spawn_block_re.search(claude_md_text)
    assert m
    block = m.group(0)
    for_loop_re = re.compile(
        r"for V in [^\n]*?do(.*?)done",
        re.MULTILINE | re.DOTALL,
    )
    for loop_match in for_loop_re.finditer(block):
        body = loop_match.group(1)
        if re.search(r"\bsleep\s+\d+\b", body):
            return
    pytest.fail(
        "publishable spawn template has NO sleep — burst would trigger hang"
    )
