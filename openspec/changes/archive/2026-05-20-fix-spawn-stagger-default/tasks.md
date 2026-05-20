## 1. TDD red — write CLAUDE.md grep regression test

- [x] 1.1 `tests/test_claude_md_invariants.py::test_publishable_spawn_template_uses_300s_stagger`:
  parse CLAUDE.md, locate the `### 1. Worker 主进程` shell template's
  `for V in baseline ...` loop, find any `sleep <N>` lines inside that
  loop, assert N >= 300
- [x] 1.2 Run test → RED (because current `sleep 60` if it exists)

## 2. Fix CLAUDE.md spawn template

- [x] 2.1 Search CLAUDE.md publishable spawn section for any `sleep 60`
  / `sleep <N<300>` in the variant loop context
- [x] 2.2 Replace with `sleep 300` + add inline comment referencing
  `snapshot-resume-ram-peak + spawn-burst-self-DDoS` invariant
- [x] 2.3 Re-run test → GREEN

## 3. Verify

- [x] 3.1 `openspec validate fix-spawn-stagger-default --strict`
- [x] 3.2 archive + commit + push
