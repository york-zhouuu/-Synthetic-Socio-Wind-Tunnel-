## ADDED Requirements

### Requirement: 操作员手动 spawn 模板强制 300s 错峰

The `CLAUDE.md` publishable spawn template's shell `for V` loop SHALL
contain a `sleep <N>` statement with `N >= 300` between variant spawns.
2026-05-20 教训：操作员（包括 AI agent）按 CLAUDE.md 模板用 `sleep 60`
spawn 4 worker，1.5 小时后 4 worker 全 hang ——burst self-DDoS。

代码路径 (`run_variant_suite._staggered_submit`) 已有 300s 默认，但**手动
`nohup &` spawn 循环不走该代码路径**，只能靠 shell `sleep` 实现错峰。
若 sleep 值 < 300，spacing 保护就形同虚设，与 `snapshot-resume-ram-peak +
spawn-burst-self-DDoS` 不变量冲突。

#### Scenario: CLAUDE.md spawn 模板的 for 循环 sleep ≥ 300

- **WHEN** an operator reads `CLAUDE.md` "正式 publishable cell spawn 步骤"
  section 1 "Worker 主进程（detached）"
- **THEN** the shell `for V in baseline ...; do ... done` template SHALL
  contain a `sleep <N>` statement with `N >= 300` inside the loop body
  (or equivalent error-prevention mechanism)

#### Scenario: 60s stagger 在模板里被视为 regression

- **GIVEN** a regression test parses `CLAUDE.md` looking for the publishable
  spawn `for V` loop
- **WHEN** any `sleep <N>` line inside that loop has `N < 300`
- **THEN** the test SHALL fail with explicit error message referencing
  this requirement
