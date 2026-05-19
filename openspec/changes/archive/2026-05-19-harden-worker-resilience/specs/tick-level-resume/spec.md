## MODIFIED Requirements

### Requirement: 原子写盘与读取

`SimulationCheckpoint.write_atomic(path: Path) -> Path` SHALL 通过 tmp 文件
+ `os.replace` 模式原子写盘 JSON（与 `DayCheckpointWriter` 同模式）。SIGKILL
期间目标路径 SHALL 要么不存在、要么是合法 JSON——不允许写到一半的破损文件。

**多进程安全**：tmp 文件名 SHALL **不使用固定后缀**（既有
`path.with_suffix(path.suffix + ".tmp")` 已知会被并发 worker 互相覆盖
损坏 snapshot——见 2026-05-19 雪崩事故）。取而代之 SHALL 用以下方式
之一：

- `tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".",
  suffix=".tmp", delete=False)`（推荐——OS 保证唯一）
- 或显式 `f"{path}.{uuid.uuid4().hex}.tmp"`

任何启动 cleanup SHALL 只清扫**自己**这一轮产生的 tmp（按 PID 或 uuid
匹配），SHALL NOT 删除其它进程的 in-flight tmp（这正是当前固定后缀
方案踩雷的核心点）。

`SimulationCheckpoint.read(path: Path) -> SimulationCheckpoint` SHALL
反序列化 + 校验 `schema_version`；不兼容版本 SHALL raise
`IncompatibleCheckpointError`。

#### Scenario: 原子写无破损残留
- **WHEN** `write_atomic(path)` 期间进程被 SIGKILL
- **THEN** 目标路径 SHALL 要么不存在、要么是合法 SimulationCheckpoint
  JSON；不允许出现非法 JSON 残留

#### Scenario: 多进程并发 write_atomic 不互相损坏（新增）
- **WHEN** 进程 A 和进程 B 几乎同时调用 `write_atomic(p)` 到同一 path
  p（双胞胎 spawn 场景）
- **THEN** 最终 p 的内容 SHALL 是 A 或 B 之一的完整 JSON（取决于 os.replace
  顺序），**SHALL NOT** 是 A 与 B 部分内容混合或半截；A 和 B 的 tmp 文件
  名 SHALL 不冲突

#### Scenario: 不兼容 schema 抛
- **WHEN** `read(path)` 读到 `schema_version == "99"` 的文件
- **THEN** SHALL raise `IncompatibleCheckpointError`，含可读的版本号信息

#### Scenario: 序列化 round-trip 等价
- **WHEN** 构造 snap → `write_atomic(p)` → `read(p)` → 得到 snap2
- **THEN** `snap2.model_dump() == snap.model_dump()`

## ADDED Requirements

### Requirement: SimulationCheckpoint 必须包含 run_metrics_state

`SimulationCheckpoint` SHALL 在 schema_version 升级（"1" → "2"）后新增字段：

- `run_metrics_state: dict[str, Any]`（`TickMetricsRecorder` 的可序列化
  状态：per_day_summaries 累积、tick-level encounter / commit / position
  delta 累积、phase 切换历史）

`TickMetricsRecorder` SHALL 实现 `to_snapshot_state() -> dict[str, Any]`
返回 JSON-safe 累积状态（含所有已完成 day 的 `DayRunSummary`、累积
encounter count、phase 当前指针等），以及 `from_snapshot_state(state:
dict)` 把状态灌回（fresh recorder + restore）。两个函数 SHALL 严格
round-trip（`from_snapshot_state(to_snapshot_state())` 后 recorder 行为
等价于序列化前）。

`MultiDayRunner` 在 `restore_into` 之后 SHALL 调
`tick_metrics_recorder.from_snapshot_state(snap.run_metrics_state)`，
让 resume 后的 worker 在 final `MultiDayResult` 里能看到**resume 之前**
那些 day 的 metric 累积。

#### Scenario: snapshot 包含 run_metrics_state 字段
- **WHEN** 在 day 8 触发 snapshot write，TickMetricsRecorder 已累积
  day 0-7 的 DayRunSummary
- **THEN** 写出来的 SimulationCheckpoint JSON SHALL 含
  `run_metrics_state` key；reload 后 `snap.run_metrics_state["per_day_summaries"]`
  SHALL 含 8 个条目

#### Scenario: resume 后 round-trip metrics 等价
- **WHEN** worker A 跑 day 0-7 后写 snapshot 死掉，worker B 从该 snapshot
  resume 跑 day 8-13 自然完成
- **THEN** worker B 写出的 `seed_N.json` 的 `multi_day_result.per_day_summaries`
  SHALL 含 **14 个**条目（day 0-13 全部）；total_ticks / total_encounters
  SHALL 是 worker A 与 worker B 累积之和；SHALL NOT 仅反映 worker B 跑的
  6 天

#### Scenario: schema_version "1" 旧 snapshot 兼容读取
- **WHEN** `read(path)` 读到 schema_version "1" 的旧 snapshot（无
  `run_metrics_state` 字段）
- **THEN** SHALL 自动设 `run_metrics_state={}`（空 recorder），让
  resume 仍可启动；SHALL log warning "loaded legacy snapshot without
  run_metrics_state — earlier day metrics will be lost; consider
  re-running from scratch for clean publishable metrics"
