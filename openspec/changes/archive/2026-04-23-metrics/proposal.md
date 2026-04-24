## Why

`policy-hack` 已经产出 4 + 1 variants 的 `MultiDayResult` JSON dump（含
`variant_metadata`），`research-design` 规定了 Diagnosis-Cure-Outcome-
Interpretation 的五幕报告结构 + β 严谨度（30 seed × median+IQR/CI）。
但是：

1. **没人读 JSON**：每 seed 一份 `MultiDayResult` + aggregate，数字都在——
   没有脚本把它们拼成**thesis-层 effect size**。`experimental-design` spec
   要求的 "in-sim effect size with CI" 目前只能靠 adhoc 分析，无复现保证。
2. **没有 rival contest 的机器**：4 条 variant 各自跑出数字，但"哪条
   hypothesis 得到最强 support"要人工算。跨 variant 的 delta / IQR
   overlap 没有统一打分函数——reviewer 看到的会是 4 个 dump 而不是一个
   contest 表。
3. **没有报告 scaffold**：研究者要按 Act 1-5 写报告，但每 variant 的
   Outcome 段（数字）得手写。自动化这一步能节省大量时间、也强制
   标准化。
4. **Thesis 链条 4 层没有对应指标算子**：
   - `algorithmic-input`：feed delivered / suppressed 比例、per-source 分布
   - `attention-main`：AttentionState.allocation 的 "physical_world" 占比、
     notification 到达率
   - `spatial-output`：trajectory 偏离 median、空间激活热力、dwell time
   - `social-downstream`：encounter density、encounter diversity；tie
     formation / info hops 是 `social-graph` / `conversation` 未来的事
5. **Fitness-report 锚点**：`data/fitness-report.json` 中
   `phase2-gaps.metrics` 状态 **FAIL**，`mitigation_change="metrics"` 指向
   本 change（探针路径 `synthetic_socio_wind_tunnel.metrics`）。

本 change 实现**观察报告层**：一套把跑完的 `MultiDayResult` + 运行时
tick 数据 → thesis-层指标 → 跨 variant contest → 五幕报告的 pipeline。
代码层不再跑 simulation，只消费 policy-hack / multi-day-run / orchestrator
的数据。

**Chain-Position**: `observability`（跨层采集；不引入新边界；为 rival
contest 打分）

## What Changes

### 1. 新增 `metrics` capability（NEW）

新模块 `synthetic_socio_wind_tunnel/metrics/`，按 4 层对应提供：

- **`TickMetricsRecorder`**：`on_tick_end` hook 订阅者。每 tick 采集：
  - per-agent AttentionState snapshot（`attention_service` 有则读）
  - per-agent current_location（Ledger.get_entity）
  - tick_result.encounter_candidates 统计
  - tick_result.commits 的 move success 统计
- **`DayMetricsSummary`**：每日 rollup — per-agent 轨迹总位移、空间熵、
  encounter 次数、attention 分布
- **`RunMetrics`**：单 seed × 14 天的全 run 指标汇总，含：
  - `trajectory_deviation`: baseline vs intervention phase 的 trajectory
    median delta（与 smoke demo 的 "+302m" 一致语义）
  - `encounter_stats`: per-day encounter count + diversity（独立 pair 数）
  - `space_activation`: per-location dwell-time 总和
  - `feed_stats`: per-source delivered / suppressed 总数
  - `attention_allocation_time_series`: 14 天 × agent × physical_world ratio
- **`RunMetrics.from_artifacts(run_dir)`**：post-hoc——从 JSON dump 目录重建

### 2. 跨 seed 聚合器（NEW）

`SuiteAggregate.from_run_metrics(list[RunMetrics])` 产出：
- 每指标的 median / IQR [25, 75] / 95% CI（对齐 β 严谨度）
- per-day time series 的跨 seed 均值
- baseline vs intervention-phase 的 delta 分布

### 3. Rival Hypothesis Contest（NEW）

`ContestReport.from_suite(dict[variant_name, SuiteAggregate])` 产出：

| 列 | 内容 |
|---|---|
| variant_name | 如 "hyperlocal_push" |
| hypothesis | H_info / H_pull / H_meaning / H_structure |
| **primary_effect_size** | trajectory median delta（与 variant 的 success_criterion 对齐）|
| effect_size_ci | 95% CI |
| evidence_alignment | `"consistent"` / `"not_consistent"` / `"inconclusive"` |
| mirror_delta | 若有 paired mirror，反向 effect size |

措辞门禁（`experimental-design` spec）：仅使用 "consistent with H_X" /
"not consistent with"；禁用 "proved / falsified"。

### 4. 五幕报告生成器（NEW）

`ReportWriter.write_markdown(contest, suite_dir)` 产出
`data/experiments/<suite>/report.md`，按 Act 1-5 + Diagnosis-Cure-Outcome-
Interpretation 四段框架；**Outcome 段自动填数字**，其它段留作者填。

### 5. Suite CLI（NEW）

`tools/run_variant_suite.py`：
- 接收 `--variants A,B,C,D,A_mirror,baseline` 与 `--seeds 30 --num-days 14`
- 顺序跑每 variant × N seed（复用 `policy-hack` 与 `multi-day-run`）
- 每 run 挂 `TickMetricsRecorder` 采集数据
- 产 `data/experiments/<timestamp>_<suite_name>/` 含：
  - `variant_<name>/seed_<N>.json`（MultiDayResult + 内嵌 RunMetrics）
  - `variant_<name>/aggregate.json`（SuiteAggregate）
  - `contest.json`（ContestReport）
  - `report.md`（五幕 scaffold）

### 6. Social / Conversation 层的 stub

本 change 不实现 weak tie 形成 / info hop 度量（那是 `social-graph` /
`conversation`）。但在 `RunMetrics` 中**预留字段**：
- `weak_tie_formation_count: int | None = None`（social-graph 填）
- `info_propagation_hops: dict[str, int] | None = None`（conversation 填）

以 `None` 表示 "not yet measured"；未来 change 实现后在 recorder 里挂接。

### 7. Fitness-audit

`phase2-gaps.metrics` probe 自动 PASS（module 可 import）

## Non-goals

- **不**实现 weak tie / tie_strength 的计算（`social-graph` 的事）
- **不**实现 conversation-level 指标（`conversation` 的事）
- **不**做 LLM 打分的"叙事质量"（exploratory posture 下的 primary deliverable
  已由 Outcome 数字 + 作者手写 Narrative 段覆盖；LLM 叙事打分是未来扩展）
- **不**做 GUI / dashboard 可视化（thesis-focus 明文归为产品外溢）
- **不**做 real-time streaming（14 天 < 30s，post-hoc JSON 读取够用）
- **不**改 `orchestrator` / `memory` / `multi-day-run` / `policy-hack` /
  `attention-channel` 能力契约——只挂现有 hook + 读现有数据
- **不**向 `MultiDayResult.metadata` 新增必填字段（只读；recorder 的数据
  独立存 `RunMetrics` JSON）
- **不**引入 numpy / pandas 重依赖（所有统计用 Python stdlib + 已引入的
  pydantic；与项目 lean 原则一致）

## Capabilities

### New Capabilities

- `metrics`: 观察报告层。TickMetricsRecorder + RunMetrics + SuiteAggregate
  + ContestReport + ReportWriter + Suite CLI。与 orchestrator / memory /
  attention-channel / policy-hack / multi-day-run 是**纯消费者关系**
  （只订阅 hook、读 JSON dump）。

### Modified Capabilities

（无——本 change 不改 existing spec 契约；现有 capability 不需要知道
metrics 的存在即可工作）

## Impact

- **新代码**：
  - `synthetic_socio_wind_tunnel/metrics/__init__.py`
  - `metrics/models.py`（`RunMetrics` / `DayMetricsSummary` / `SuiteAggregate`
    / `ContestReport` / `EvidenceAlignment` Literal）
  - `metrics/recorder.py`（`TickMetricsRecorder` / `DayMetricsCollector`）
  - `metrics/aggregator.py`（cross-seed stats — 复用 `MultiDayResult.combine`
    的 percentile 辅助）
  - `metrics/contest.py`（rival hypothesis scoring）
  - `metrics/report.py`（markdown writer）
  - `tools/run_variant_suite.py`（Suite CLI）
- **修改**：
  - `synthetic_socio_wind_tunnel/__init__.py`（re-export）
  - `synthetic_socio_wind_tunnel/fitness/audits/phase2_gaps.py`（probe 已存在；
    module 创建后 auto PASS）
- **新增测试**：
  - `tests/test_metrics_models.py`
  - `tests/test_metrics_recorder.py`
  - `tests/test_metrics_aggregator.py`
  - `tests/test_metrics_contest.py`
  - `tests/test_metrics_report.py`
  - `tests/test_run_variant_suite.py`（CLI + E2E）
- **前置依赖**：
  - `experimental-design` spec（已归档，引用即可）
  - `multi-day-simulation` capability（`MultiDayResult.metadata`）
  - `policy-hack` capability（variant 元数据）
  - `orchestrator` / `memory` / `attention-channel`（数据源）
- **下游依赖**：未来 `social-graph` / `conversation` 会挂入 recorder 填
  占位字段
- **fitness-report 影响**：`phase2-gaps.metrics` FAIL → PASS
- **性能**：TickMetricsRecorder 每 tick 轻量采样（N agent × O(1)）；
  14 天 × 100 agent × 30 seed suite 的 metrics 开销估计 < 10% wall time
