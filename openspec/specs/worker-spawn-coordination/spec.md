# worker-spawn-coordination Specification

## Purpose
TBD - created by archiving change stagger-worker-spawn. Update Purpose after archive.
## Requirements
### Requirement: 最小 spawn 间隔强制 (in-code)

`tools/resume_publishable.py` 和 `tools/run_variant_suite.py` 的 spawn 路径 SHALL 强制最小 spawn 间隔（默认 300 秒，可配置）。

同一 process / LaunchAgent 周期内连续 spawn 多个 worker 时，必须按
spacing 串行；跨 LaunchAgent 周期通过持久化 timestamp 文件协调。

读取 spacing 配置优先级：argparse `--min-spawn-spacing-secs` >
env `RESILIENCE_MIN_SPAWN_SPACING_SECS` > 默认 300。配置值 `0` SHALL
完全关闭 spacing guard（恢复立刻 spawn 行为，用于 ad-hoc 测试场景）。

#### Scenario: 5 分钟内连续 2 次 spawn 第 2 次被拒

- **WHEN** `_spawn_resume_worker` 第 1 次调用成功，立刻写 timestamp；
  3 分钟后第 2 次调用尝试 spawn
- **THEN** 第 2 次 SHALL 返回 sentinel "deferred"（不实际 fork
  subprocess）；log SHALL 包含 "deferred_due_to_stagger" + 下次可
  spawn 的 ISO 时间

#### Scenario: 满 5 分钟后第 2 次 spawn 允许

- **WHEN** 第 1 次 spawn 成功后 6 分钟，第 2 次调用 `_spawn_resume_worker`
- **THEN** 第 2 次 SHALL 实际 spawn；timestamp 被更新为本次 spawn 时间

#### Scenario: env override 关闭 spacing

- **WHEN** 设置 `RESILIENCE_MIN_SPAWN_SPACING_SECS=0` 后连续 2 次调用
  `_spawn_resume_worker`（间隔 < 1 秒）
- **THEN** 两次都 SHALL 实际 spawn；timestamp 仍被更新但 guard
  逻辑跳过比较

### Requirement: spawn timestamp 持久化协议

last-spawn timestamp SHALL 持久化到
`~/Library/Logs/swt-resume-watchdog-last-spawn.json` 文件，使用 epoch
seconds（`time.time()`）作为可跨进程比较的时间戳。文件格式必须包含：

- `last_spawn_epoch: float` (epoch seconds, primary comparison field)
- `last_spawn_iso: str` (ISO-8601 with timezone, informational)
- `last_spawn_cell: {seed: int, variant: str}` (informational, 用于
  审计 "上次 spawn 是哪个 cell")
- `version: int = 1` (schema 演进保留字段)

读取 timestamp 时若文件不存在 → 视为 "无 last spawn" → 允许 spawn。
读取时若格式错误 / JSON 损坏 / 字段缺失 → log warning + 允许 spawn
（**保守模式**：宁可允许 spawn 也不锁死）。

写入 timestamp SHALL 使用 atomic write 模式（temp file + rename），
避免读端读到部分写入。

#### Scenario: timestamp 文件不存在第一次 spawn 允许

- **WHEN** `~/Library/Logs/swt-resume-watchdog-last-spawn.json` 不存在，
  调 `_spawn_resume_worker`
- **THEN** spawn SHALL 被允许；timestamp 文件被创建，包含 4 个字段

#### Scenario: timestamp 文件损坏 fallback 允许 spawn

- **WHEN** timestamp 文件存在但内容是 `"not valid json {{"`，调
  `_spawn_resume_worker`
- **THEN** SHALL log warning（"corrupted timestamp file"）+ 允许
  spawn + 用新数据覆盖文件

#### Scenario: 系统时钟回拨保守处理

- **WHEN** timestamp 文件存的 epoch > 当前 `time.time()` 返回值
  （时钟回拨）
- **THEN** SHALL log warning（"clock went backward, resetting
  spacing"）+ 重置 timestamp = now + 允许 spawn

### Requirement: 多 INTERRUPTED cell 串行处理顺序

`resume_publishable.py` 主循环在单次 LaunchAgent fire 内遇到多个 INTERRUPTED cell 时，SHALL 按 `(seed, variant)` 字典序处理；本轮最多 spawn 1 个 cell，剩余 cell SHALL 标 `action="deferred_due_to_stagger"` 并 log + report 但不实际 spawn。

下个 LaunchAgent 周期（5 min 后）SHALL 重新评估，仍 INTERRUPTED 的
cell 按同样规则处理。

#### Scenario: 4 INTERRUPTED cell 本轮只 spawn 1 个

- **WHEN** `resume_publishable.py` 启动，发现 4 个 INTERRUPTED cell
  (seeds=42 variants={baseline, hyperlocal_push, phone_friction,
  global_distraction})，timestamp 文件不存在
- **THEN** 字典序第 1 个 (`seed=42 variant=baseline`) SHALL 实际
  spawn；剩余 3 个 SHALL 在 report 里标 `deferred_due_to_stagger`
  并 log 同样原因；exit code SHALL 是 1（"incomplete"，因为还有
  cell 未 DONE）

#### Scenario: 串行处理在 spawn 第 1 个后立刻更新 timestamp

- **WHEN** 4 cell 处理过程中第 1 个 spawn 成功
- **THEN** timestamp 文件 SHALL 在第 2/3/4 cell 检查前已被更新；
  即使主循环不显式 sleep，第 2 个 cell 的 spacing check 已经能看到
  新 timestamp 并 defer

### Requirement: run_variant_suite ThreadPool 内部 stagger

`tools/run_variant_suite.py` 的 `--workers N > 1` 模式下，ThreadPoolExecutor submit N 个 worker subprocess 时 SHALL 按 spacing 串行 submit：第 i 个 submit (i > 0) 之前 coordinator thread SHALL sleep `min_spawn_spacing_secs` 秒。

spacing 配置共享 resume_publishable.py 的同一 env / 默认值
（`RESILIENCE_MIN_SPAWN_SPACING_SECS` / 300s）。

设置 `RESILIENCE_MIN_SPAWN_SPACING_SECS=0` 时 SHALL 跳过 sleep，
所有 worker 立刻 submit（恢复旧行为）。

#### Scenario: 4 variants × workers=4 staggered submit

- **WHEN** `run_variant_suite.py --variants
  baseline,hyperlocal_push,phone_friction,global_distraction
  --workers 4` 调用，env spacing=2 (短于默认便于测试)
- **THEN** subprocess.Popen 调用时间 SHALL 大致是
  t=0s, t=2s, t=4s, t=6s（误差 < 0.5s）；最后 1 个 Popen 时间
  ≥ 6s after first

#### Scenario: env spacing=0 ThreadPool 不 sleep

- **WHEN** `RESILIENCE_MIN_SPAWN_SPACING_SECS=0` 设置，4 variants
  × workers=4
- **THEN** 4 个 subprocess.Popen 时间差 SHALL < 0.5s（基本同时
  submit，恢复旧 behavior）

### Requirement: deferred 行为可观测性

每次 spawn 决策（无论 actual spawn 还是 deferred）SHALL log 包含：

- 决策类型（spawned / deferred_due_to_stagger / spawn_failed）
- 目标 cell `(seed, variant)`
- 当前 epoch 时间
- last_spawn_epoch 和距上次 spawn 秒数
- spacing 配置当前值
- 下次可 spawn 时间（ISO 格式）

`resume_publishable.py` 的 JSON report 字段 `action` SHALL 在 deferred
情况下使用值 `"deferred_due_to_stagger"`（既有 `"spawn_resume"` 值
不变）。

#### Scenario: deferred 的 cell 在 report 中可识别

- **WHEN** 4 cell 评估，第 1 个 spawn，剩 3 个 deferred
- **THEN** JSON report 中 4 entry：第 1 个 `action="spawn_resume"`
  + `new_pid=<int>`；剩 3 个 `action="deferred_due_to_stagger"` +
  `next_eligible_iso=<ISO 时间>`

#### Scenario: deferred log line 格式

- **WHEN** 任一 cell 被 deferred
- **THEN** logger.info SHALL 包含 substring "deferred_due_to_stagger"
  + cell 标识 + "next eligible at" + ISO 时间字符串

