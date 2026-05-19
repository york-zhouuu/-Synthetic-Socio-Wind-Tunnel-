## ADDED Requirements

### Requirement: MemoryService.to_snapshot_state 必须满足性能预算

`MemoryService.to_snapshot_state()` SHALL 在 N=10_000 MemoryEvent 输入
规模下完成时间 ≤ legacy baseline 的 1/5 (5× speedup floor)。

baseline 定义：commit-`<this change's parent SHA>` 时的
`synthetic_socio_wind_tunnel/memory/service.py::_event_to_json` 实现
（per-event Python loop with isinstance + getattr + datetime/tuple coerce）。

测试位置：`tests/test_event_to_json_performance.py`，marker
`@pytest.mark.slow`（benchmark 跑 N=10_000 event 至少 3 trials median，
单次约 0.5–2 秒）。

输出 byte-equivalence：fast path 与 legacy 对同一 MemoryEvent 输入
SHALL 产生**相等**的 dict（字段顺序也一致——下游 `json.dumps` 字段顺序
保留性依赖该序）。

#### Scenario: N=10000 event serialize 5× speedup
- **WHEN** 构造 10_000 个 MemoryEvent，跑 baseline 与 fast path 各 3 trial
- **THEN** median(fast) / median(baseline) SHALL ≤ 0.2 (5× speedup);
  失败时 error 信息 SHALL 包含两端绝对时间 + ratio + 选择的实现（A or B）

#### Scenario: byte-equivalent output for every kind
- **WHEN** 加载 `tests/fixtures/memory_event_round_trip_corpus.json`
  含 6 种 kind × 至少 5 个 event each
- **THEN** 对每个 event，fast_path(ev) == legacy_path(ev) SHALL True
  （dict 相等 + key 顺序相等）；失败时 error 指出哪个 event 哪个字段不等

#### Scenario: fallback env switches to legacy
- **WHEN** 设置 `MEMORY_SNAPSHOT_USE_FAST=0` 跑 `to_snapshot_state`
- **THEN** SHALL 走 legacy path（可通过 import-mock 或 module-level
  flag 检测调用了哪个分支）

### Requirement: 优化后 py-spy cumulative percent 必须显著下降

优化后 `_event_to_json` SHALL 在 py-spy 火焰图上 cumulative % < 10%
（从 78% baseline 降下来），即 dev smoke (100 agent × 1 day) 跑 30s
py-spy 采样验证。

如果新的热点 > 20% cumulative 出现，SHALL 记入下一个 openspec change
proposal（"hot path 转移"是迭代结果，不阻塞本 change）。

#### Scenario: 二次火焰图采样验证
- **WHEN** 优化 merge 后跑 `sudo py-spy record -o /tmp/post.svg
  --pid <smoke_pid> -d 30` 在 dev smoke 跑到 day_end 附近时采样
- **THEN** 从 `/tmp/post.svg` 提取 cumulative %：`_event_to_json` SHALL
  < 10%；本次采样结果 SHALL 写进 `docs/post-optimization-flamegraph-
  2026-05-19.md` 留作 baseline 比较档
