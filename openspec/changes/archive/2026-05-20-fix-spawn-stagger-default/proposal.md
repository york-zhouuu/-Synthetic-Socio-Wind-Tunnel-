## Why

2026-05-20 β=1 publishable scout cascaded into 4-worker hang within 1.5h
because the spawn template in `CLAUDE.md` 正式 publishable cell spawn 步骤
used `sleep 60` between variant spawns. The documented invariant
`snapshot-resume-ram-peak + spawn-burst-self-DDoS` (2026-05-19) explicitly
requires `min_spacing_secs=300` (5 min) between worker spawns to prevent
LLM-burst-induced self-DDoS — but the CLAUDE.md spawn template was 60s
and I followed it.

The actual code default in `run_variant_suite.py` IS 300s
(`RESILIENCE_MIN_SPAWN_SPACING_SECS` env default = "300") for the
`_staggered_submit` ThreadPool path. **But manual nohup spawn loops in
the CLAUDE.md template bypass this code path** and rely solely on the
shell `sleep` between spawn lines.

Net result: documented invariant is 300s, code enforces it for one path,
but CLAUDE.md operator template undercuts it with `sleep 60`. Operator
following the template (me, this evening) triggers the exact failure
mode the invariant is supposed to prevent.

## What Changes

- **CLAUDE.md** 正式 publishable cell spawn 步骤: shell `for V` loop SHALL
  use `sleep 300` not `sleep 60` between variants
- **CLAUDE.md** add explicit invariant cross-reference + the rationale 
  (300s spacing prevents burst self-DDoS at LLM-provider edge)
- **Regression test** in `tests/test_claude_md_invariants.py` — parse
  CLAUDE.md, find the publishable spawn `for V` loop, assert any `sleep`
  inside the loop ≥ 300
- **No code-path changes** — `run_variant_suite._staggered_submit` already
  defaults to 300s; this change covers the operator-template path

## Capabilities

### New Capabilities

(none — this is a doc + test addition)

### Modified Capabilities

(none — no spec-level behavior changes)

## Impact

**Affected files**:
- `CLAUDE.md` (the 正式 publishable cell spawn 步骤 section)
- `tests/test_claude_md_invariants.py` (new regression test file)

**Affected behavior**:
- Future operators following CLAUDE.md SHALL spawn with 300s stagger
- Existing code paths unchanged (`_staggered_submit` already correct)
- This evening's hang root cause likely included undersized stagger;
  300s in template prevents recurrence

**Non-goals**:
- Not changing `RESILIENCE_MIN_SPAWN_SPACING_SECS` env default (already 300)
- Not adding new code semaphores beyond commit 2560200 (OperationPool
  semaphore already shipped)
- Not coordinating cross-cell stagger (that's a separate concern handled
  by `resume_publishable.py`'s spacing guard)
