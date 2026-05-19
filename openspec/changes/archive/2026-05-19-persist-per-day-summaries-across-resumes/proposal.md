## Why

2026-05-20 项目扫发现**这是 thesis-blocking bug**：worker 14-day
publishable run 完成时写的 `seed_<N>.json` 里 `per_day_summaries`
**只包含最后一次 resume 的天数**，不是完整 14 天。其它天的 per-day
metrics 全部丢失。

精确机制：
- `MultiDayRunner.run_multi_day` 第 435 行 `per_day: list[DayRunSummary]
  = []` 初始化空
- Resume 时设 `effective_start_day = snap.day_index`（line 509）or
  `self._resume_from`
- 循环 `for day_index in range(effective_start_day, num_days)` 只跑
  这次 spawn 的天数，per_day 只追加这些
- `MultiDayResult(per_day_summaries=tuple(per_day), ...)` 序列化只有这些
- `total_encounters` / `total_ticks` 也只是 this-run 累计

实测证据：
- `data/experiments/.../variant_baseline/seed_42.json`:
  `day_indices=[10, 11, 12, 13]` (4 days of 14)
- `data/experiments/.../variant_global_distraction/seed_42.json`:
  `day_indices=[9, 10, 11, 12, 13]` (5 days of 14)
- `total_encounters` 数值匹配 4-day / 5-day 不是 14-day

产品冲击：thesis 核心论证依赖 **phase comparison**：
- baseline phase (day 0-3): 没干预的 encounter density
- intervention phase (day 4-9): 推送干预期
- post phase (day 10-13): 撤干预后

只剩 post phase data → 没法做 phase 对比 → 论文核心结论拿不出来。

## What Changes

实现"day-summary persistent across resumes"：

- **新加 `DayCheckpointWriter.write_day_summary(day_index,
  day_run_summary, output_dir, seed)` 方法**：把 DayRunSummary
  序列化为 `seed_<N>_day<D>.summary.json` 一次性 commit 落盘
  （atomic via temp file + rename）。
- **`MultiDayRunner.run_multi_day` 在每个 day_end 调用** write_day_summary
  即把这天的 summary 写盘（独立于 cleanup_partials —— 这个文件不被
  cleanup）。
- **`MultiDayRunner.run_multi_day` 开始时（在 effective_start_day
  分支前）调用** `_load_existing_day_summaries(output_dir, seed,
  num_days)` 读所有已有 `seed_<N>_day<D>.summary.json` 文件 → 把
  这些 DayRunSummary 注入 `per_day` 初始 list（按 day_index 排序）。
- **`MultiDayResult.total_encounters` / `total_ticks` 由 per_day 累计**
  （目前已经是这样，只要 per_day 完整就对了）。
- **`seed_<N>.json` 写完后 NOT 清除 day summaries**（保留作为 audit
  trail；下次 resume 还能用）。
- **新加 e2e integration test**: 跑 3 day dev smoke 然后 simulate
  resume from day 1，verify 最终 seed_N.json 含 day 0/1/2 全部
  per_day_summaries。

NOT in scope:
- 不改 `seed_<N>_day<D>.partial.json` 的 schema 或行为
- 不动 `total_encounters` 计算公式（依赖 per_day 即可）
- 不重建已损坏的旧 D2 数据（无法）

## Capabilities

### Modified Capabilities

- `tick-level-resume`: 每个 day_end SHALL 持久化 DayRunSummary 到
  `seed_<N>_day<D>.summary.json`（独立 file）；resume 时 SHALL 从这
  些文件 hydrate `per_day` 列表，确保最终 seed_N.json 含全部 14 day
  per_day_summaries（不只是 last-resume's days）。

## Impact

**Affected code**:
- `synthetic_socio_wind_tunnel/run_resilience/checkpoint.py`
  (`DayCheckpointWriter` 加 write/read summary 方法)
- `synthetic_socio_wind_tunnel/orchestrator/multi_day.py`
  (`run_multi_day` 起始 hydrate + 每 day_end write)

**Affected behavior (positive)**:
- 所有 publishable 14-day cell 完成后 seed_N.json 含完整 14 day data
- thesis phase comparison (baseline vs intervention vs post) 可做
- total_encounters / total_ticks 是真 14-day 总数

**Affected behavior (negative)**:
- 每个 cell 多 14 个 summary.json 小文件（每个 < 1KB），可忽略
- 第一次 day_end 多 1 个 atomic write，<10ms overhead

**Test impact**: 1 subprocess e2e test verifies cross-resume merge.
既有 multi_day tests 不动（per_day still populated correctly within
single-run scope）。

**Migration**:
- 新代码部署后下次 spawn 开始累积 day summaries
- 旧 cells 没法回溯重建（partial 已 cleanup）
- 影响的旧 cell：seed42 baseline / seed42 global_distraction /
  seed43 baseline / seed43 global_distraction — 数据已部分丢失，
  研究上只能用 post-phase data 做有限分析或重跑
