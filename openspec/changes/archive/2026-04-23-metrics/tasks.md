# Tasks — metrics

实现观察报告层：TickMetricsRecorder + RunMetrics + SuiteAggregate +
ContestReport + ReportWriter + Suite CLI。

**Chain-Position**: `observability`（跨层采集；不引入新边界）
**前置**: `experimental-design` spec + `multi-day-simulation` 基建 +
`policy-hack`（`VariantRunnerAdapter` / `VARIANTS`）+ `attention-channel`
+ `orchestrator` / `memory` 数据源
**Fitness-report 锚点**: `phase2-gaps.metrics` FAIL → PASS

## 1. 模块骨架 + 数据模型

- [x] 1.1 创建 `synthetic_socio_wind_tunnel/metrics/__init__.py`（re-export）
- [x] 1.2 创建 `synthetic_socio_wind_tunnel/metrics/models.py`：
  - `DayMetricsSummary` Pydantic frozen（per-day per-agent rollup）
  - `RunMetrics` Pydantic frozen（完整 spec 字段 + `extensions` dict）
  - `SuiteAggregate` Pydantic frozen（per-metric stats + time series）
  - `EvidenceAlignment` Literal["consistent", "not_consistent", "inconclusive"]
  - `ContestRow` / `ContestReport` Pydantic frozen
  - `RunMetrics.with_extensions` / `SuiteAggregate.metadata_degraded` helpers

## 2. TickMetricsRecorder

- [x] 2.1 创建 `metrics/recorder.py`：
  - `TickMetricsRecorder` class with `__init__(attention_service: ... | None)`
  - `on_tick_end(tick_result)` callback collecting per-agent data
  - internal `DayMetricsCollector`（per-day 缓冲，day_index 变化时 rollup）
  - `snapshot() -> list[DayMetricsSummary]`（rollup 全部）
- [x] 2.2 Recorder 内部缓冲结构（memory footprint 友好）：
  - per-agent per-day running counters（encounter count / moves / dwell ticks）
  - 不存 per-tick trajectory（除非 `--dump-trace` flag）

## 3. RunMetrics 工厂

- [x] 3.1 `RunMetrics.from_recorder(recorder, multi_day_result, variant_metadata,
  phase_config)` classmethod：
  - 合并 recorder.snapshot() + multi_day_result 到 RunMetrics 实例
  - 计算 `trajectory_deviation_m`（对 hyperlocal_push / global_distraction
    使用 target_location 距离；其它 variant 留 None）
  - 从 AttentionService.delivery_log 统计 `feed_stats`
  - 从 DayMetricsSummary 聚合 `encounter_stats`、`space_activation`、
    `attention_allocation_ratio`

## 4. SuiteAggregate 跨 seed

- [x] 4.1 创建 `metrics/aggregator.py`：
  - `SuiteAggregate.from_run_metrics(list[RunMetrics]) -> SuiteAggregate`
  - 复用 `synthetic_socio_wind_tunnel.orchestrator.multi_day._series_stats`
    做 percentile（避免重复）
  - per-day time-series：对每日 median
  - seed_count < 30 → 标记 `degraded_preliminary_not_publishable=True`

## 5. ContestReport rival scoring

- [x] 5.1 创建 `metrics/contest.py`：
  - `ContestReport.from_suite(dict[variant_name, SuiteAggregate]) -> ContestReport`
  - 判据：CI 不重叠 → "consistent" / "not_consistent"；重叠 → "inconclusive"
  - 方向匹配：按 variant 的 success_criterion 文本启发式（或硬编码 variant →
    direction dispatch 表）
  - Mirror delta：若 suite 同时含 paired 正向 + mirror → 计算差
  - 措辞门禁：生成的 `notes` 字符串不含 "proved / falsified / confirmed /
    refuted"；assertion 在单元测试里验证
- [x] 5.1a `primary_effect_size_for(variant_name, run_metrics_or_aggregate)`
  dispatch 函数：
  - hyperlocal_push / global_distraction → `trajectory_deviation_m`
  - phone_friction → `attention_allocation_ratio.physical_world`
  - shared_anchor → 共享 task agents 间 encounter density
  - catalyst_seeding → encounter network density proxy（per-day median encounter）
  - baseline → 同 hyperlocal_push 字段（作对照 reference）

## 6. ReportWriter 五幕 Markdown

- [x] 6.1 创建 `metrics/report.py`：
  - `ReportWriter.write_markdown(contest, suite_dir) -> Path`
  - Jinja-like 模板但用 Python f-string（避免引 jinja 依赖）
  - 五幕 + 每 variant 四段结构
  - HTML comment trace：`<!-- auto-generated from ... -->`
- [x] 6.2 Report 语言：中文（project-wide 基调）；模板里英文标题保留为副标题

## 7. build_single_seed_run recorder hook

- [x] 7.1 修改 `tools/run_multi_day_experiment.py::build_single_seed_run`：
  - 加 kwarg `recorder: TickMetricsRecorder | None = None`
  - 若非 None：`orchestrator.register_on_tick_end(recorder.on_tick_end)`
  - 向后兼容：不传 recorder 行为不变

## 8. Suite CLI

- [x] 8.1 新建 `tools/run_variant_suite.py`：
  - argparse: `--variants` / `--seeds` / `--num-days` / `--agents` /
    `--mode` / `--phase-days` / `--output-dir` / `--suite-name`
  - 循环 variants × seeds；每 run 构造 recorder；调 build_single_seed_run
  - Per-variant 跑完后调 SuiteAggregate + dump
  - 全 suite 跑完调 ContestReport + ReportWriter
  - 产出目录结构：见 proposal

## 9. 公共 API re-export

- [x] 9.1 `synthetic_socio_wind_tunnel/__init__.py` 加：
  - `TickMetricsRecorder` / `DayMetricsSummary` / `RunMetrics`
  - `SuiteAggregate` / `ContestReport` / `ContestRow` / `EvidenceAlignment`
  - `ReportWriter`
- [x] 9.2 `synthetic_socio_wind_tunnel/metrics/__init__.py` 导出同上

## 10. 测试

- [x] 10.1 `tests/test_metrics_models.py`：
  - RunMetrics 构造、JSON 往返
  - extensions dict 默认空
  - with_extensions 创建新实例不 mutate 原实例
  - DayMetricsSummary / SuiteAggregate frozen 语义
- [x] 10.2 `tests/test_metrics_recorder.py`：
  - 小规模 3 agent × 3 tick 模拟 tick_result 喂入；验证 counter
  - attention_service=None 时跳过 AttentionState 不崩
  - 性能：1000 agent × 288 tick 采样 < 100ms
- [x] 10.3 `tests/test_metrics_aggregator.py`：
  - 30 seed 聚合产正确 median/IQR/CI
  - 5 seed 聚合带 degraded 标记
  - 同 seed 重复 → 零方差
- [x] 10.4 `tests/test_metrics_contest.py`：
  - CI 不重叠 → consistent/not_consistent 判定正确
  - CI 重叠 → inconclusive
  - Paired mirror delta 对称
  - 措辞门禁：生成的 notes 无禁用词
  - Suite 无 baseline 时警告（CLI 测试里验）
- [x] 10.5 `tests/test_metrics_report.py`：
  - 五幕结构齐全
  - 每 variant 四段齐全
  - HTML trace 注释存在
  - Suite 无 baseline → Act 1 有警告标记
- [x] 10.6 `tests/test_run_variant_suite.py`（E2E CLI）：
  - 最小 smoke：2 variant × 2 seed × 3 天
  - 产 `data/experiments/*` 目录结构正确
  - 未知 variant 报错非零退出
- [x] 10.7 回归：跑全 pytest 套件零 Phase 1-2 + policy-hack 回归

## 11. Fitness-audit

- [x] 11.1 确认 `synthetic_socio_wind_tunnel.metrics` 可 import
- [x] 11.2 跑 `make fitness-audit` → `phase2-gaps.metrics` 从 FAIL → PASS
- [x] 11.3 更新 `tests/test_fitness_phase1_phase2.py`：
  - `unimplemented_capabilities_still_fail` 集合剔除 "metrics"
  - `test_every_unimplemented_phase2_change_has_fail_anchor` 同步

## 12. 文档

- [x] 12.1 新建 `docs/agent_system/16-metrics.md`：
  - 4 层指标对应（algorithmic-input / attention-main / spatial-output /
    social-downstream）+ 当前覆盖 / 未来由 social-graph/conversation 补）
  - TickMetricsRecorder hook 时序
  - Suite CLI 示例（完整 4+1 variants + baseline suite）
  - Contest 判据（evidence alignment）
  - 与 experimental-design / research-design 的对应
- [x] 12.2 更新 `README.md` Development Status 加 "Metrics" 行

## 13. Suite 完整跑验证

- [x] 13.1 运行 dev-mode 3 天 suite（6 variant × 2 seed）：
  `python3 tools/run_variant_suite.py --variants baseline,hyperlocal_push,
  global_distraction,phone_friction,shared_anchor,catalyst_seeding
  --seeds 2 --num-days 3 --agents 15 --mode dev --phase-days 1,1,1
  --suite-name metrics_smoke`
- [x] 13.2 检查产物：6 个 variant dir / 1 contest.json / 1 report.md
- [x] 13.3 人工 review report.md：五幕齐全、Outcome 段有数字、无禁用词

## 14. 性能

- [x] 14.1 14 天 × 100 agent × 1 seed 带 recorder 时 wall time ≤ 22s
  （baseline ~10s + 10% overhead = 11s + policy-hack variants 适当开销）

## 15. 验证

- [x] 15.1 `openspec validate metrics --strict` 通过
- [x] 15.2 grep 检查：`TickMetricsRecorder` / `RunMetrics` /
  `SuiteAggregate` / `ContestReport` / `ReportWriter` 在 spec / 代码 / 测试
  / 文档四处命名一致
- [x] 15.3 确认 metrics 模块 import 不加载 numpy / pandas / scipy
  （`tests/test_metrics_models.py` 内做 sanity check）
