# Metrics — 观察报告层

> Rival Hypothesis Contest 的**打分机**。把 `policy-hack` + `multi-day-run`
> 跑出的原始数据 → thesis-层 effect size → cross-variant contest → 五幕
> Markdown 报告。
>
> 正式 spec: `openspec/specs/metrics/spec.md`
> 由 `openspec/changes/metrics/` 实现（2026-04-23）。

---

## 架构

```
orchestrator + multi-day-run + policy-hack
         │
         ▼  (on_tick_end hook)
┌────────────────────────────┐
│  TickMetricsRecorder       │
│  - per-agent per-tick       │
│  - per-day rollup           │
└────────────┬───────────────┘
             │ snapshot()
             ▼
      DayMetricsSummary × N days
             │
             ▼  build_run_metrics(recorder, result, atlas, variant_metadata)
        RunMetrics (per seed)
             │
             │ × N seeds same variant
             ▼  build_suite_aggregate(list[RunMetrics])
        SuiteAggregate (per variant: median / IQR / 95% CI / time series)
             │
             │ × M variants
             ▼  build_contest_report(dict[variant, SuiteAggregate])
        ContestReport (rival hypothesis scoring)
             │
             ▼  write_markdown(contest, aggregates, suite_dir)
        report.md (五幕 scaffold)
```

**零依赖**：numpy / pandas / scipy 都不引入。percentile 复用
`orchestrator.multi_day._series_stats`。

---

## 四层指标（对应 thesis chain）

| 层 | 指标 | 来源 | 本 change 覆盖 |
|---|---|---|---|
| `algorithmic-input` | feed delivered / suppressed per source | `AttentionService.export_feed_log()` | ✅ `RunMetrics.feed_stats` |
| `attention-main` | phone_feed_proxy（delivered notifs 归一化） | feed log 聚合 | ⚠️ proxy only；full `AttentionState` 四元组需 perception 扩展 |
| `spatial-output` | trajectory_deviation / encounter_stats / space_activation | recorder + atlas centroid | ✅ 全部 |
| `social-downstream` | encounter_density / distinct_pairs | recorder | ✅ 部分（weak_tie / info_hops 留 None，待 `social-graph` / `conversation` 填） |

### 未来挂载点（`social-graph` / `conversation` 用）

```python
class RunMetrics:
    ...
    weak_tie_formation_count: int | None = None       # social-graph 填
    info_propagation_hops: dict[str, int] | None = None  # conversation 填
    extensions: dict[str, Any] = {}                    # 任意字段

# social-graph 的 recorder 可调：
run_metrics = run_metrics.with_extensions(weak_tie_formation_count=12)
```

---

## Contest 判据（Evidence Alignment）

```
variant 的 primary_effect CI    ╶╶╮
                                  │  →  不重叠 baseline CI 且方向匹配 success_criterion
                                  │      → "consistent"
baseline 的 primary_effect CI   ╶╶╯  →  不重叠但反方向
                                         → "not_consistent"
                                     →  重叠
                                         → "inconclusive"
```

**禁用词门禁**（`experimental-design` spec 要求）：
- ✓ 允许：`evidence consistent with H_X` / `evidence not consistent with H_X`
- ✗ 禁止：`proved / falsified / confirmed / refuted`

Contest + Report 两层 assert 无禁用词；测试覆盖。

### Primary metric dispatch

| variant | primary metric | direction |
|---|---|---|
| `hyperlocal_push` | `trajectory_deviation_m` | lower（离 target 越近越 consistent） |
| `global_distraction` | `trajectory_deviation_m` | higher（mirror: 离 target 越远越 consistent） |
| `phone_friction` | `attention.phone_feed_proxy` | lower |
| `shared_anchor` | `encounter.per_day_median` | higher |
| `catalyst_seeding` | `encounter.per_day_median` | higher |
| `baseline` | `encounter.per_day_median` | —（reference） |

---

## Suite CLI

```bash
# 完整 6-variant publishable contest（14 天 × 30 seed × 100 agent）
python3 tools/run_variant_suite.py \
    --variants baseline,hyperlocal_push,global_distraction,phone_friction,shared_anchor,catalyst_seeding \
    --seeds 30 --num-days 14 --agents 100 \
    --mode publishable --phase-days 4,6,4 \
    --suite-name thesis_v1

# Dev smoke（2 variant × 2 seed × 3 天）
python3 tools/run_variant_suite.py \
    --variants baseline,hyperlocal_push \
    --seeds 2 --num-days 3 --agents 15 \
    --mode dev --phase-days 1,1,1 \
    --suite-name smoke_v1
```

### 产出目录

```
data/experiments/<timestamp>_<suite_name>/
├── variant_baseline/
│   ├── seed_42.json        (MultiDayResult + RunMetrics)
│   ├── ...
│   └── aggregate.json      (SuiteAggregate with median/IQR/CI)
├── variant_hyperlocal_push/
├── variant_global_distraction/
├── variant_phone_friction/
├── variant_shared_anchor/
├── variant_catalyst_seeding/
├── contest.json            (ContestReport)
└── report.md               (五幕 Markdown scaffold)
```

---

## 五幕报告结构

```markdown
# <suite_name> — Rival Hypothesis Contest Report

## Act 1 — Baseline
  Diagnosis | Outcome (auto) | Interpretation (作者填)

## Act 2 — Four Doctors
  ### Variant: hyperlocal_push (H_info)
    Diagnosis | Cure | Outcome (auto) | Interpretation
  ### Variant: phone_friction (H_pull)
    ...
  ### Variant: shared_anchor (H_meaning)
    ...
  ### Variant: catalyst_seeding (H_structure)
    ...

## Act 3 — The Contest
  | variant | hypothesis | primary | effect size | 95% CI | alignment | mirror Δ |
  |---|---|---|---|---|---|---|
  ...

## Act 4 — Decay
  table: intervention-end vs post-end encounter medians + decay ratio

## Act 5 — The Mirror
  paired mirror Δ 对称性检查
```

每个 auto-filled Outcome 段带 HTML trace 注释：
```
<!-- auto-generated from variant_hyperlocal_push/aggregate.json; seeds=30 -->
```

---

## 与 experimental-design spec 的对应

| spec 条款 | metrics 实现 |
|---|---|
| Primary experiments SHALL adopt Rival Hypothesis structure | `ContestReport` 按 variant/hypothesis 分行 |
| 14-day Baseline/Intervention/Post | `PhaseController` 从 policy-hack 引入；metrics 读 `phase_config` 定边界 |
| β rigor 30 seed + CI | `build_suite_aggregate` 输出 median/IQR/95%CI；<30 标 `degraded_preliminary_not_publishable` |
| Research posture: exploratory Hybrid | 禁用词门禁 + Outcome-数字 + Interpretation-作者两段分离 |
| Paired mirror 4+1 | `ContestRow.mirror_delta` 计算对称差 |
| Diagnosis-Cure-Outcome-Interpretation | `write_markdown` 的每 variant 段结构严格按此 |

---

## 已知限制（metrics change 不解决）

1. **`attention_allocation_ratio` 仅 `phone_feed_proxy` 一个维度**：
   `physical_world / task / conversation` 三项需 perception 层暴露
   `AttentionState` 的时序——超出本 change
2. **`weak_tie_formation_count` / `info_propagation_hops` 留 None**：
   等 `social-graph` / `conversation` change 完成后由对应 recorder 填入
3. **真实 LLM 下 cost 不纳入 metrics**：参与 `model-budget` change
4. **Real-world 校准（Google Popular Times / ABS）不在范围**：留给未来
   `validation-strategy` change

> **2026-04-25 update**：metrics archive 当日 smoke 发现 variants 在
> scripted-plan 下无法改变 agent 行为（因果链在 `run_variant_suite.py`
> 处断开）。已由 follow-up change `suite-wiring` 修复——接入 MemoryService
> + Planner + StubReplanLLM，让 variants 真正能通过 attention → memory
> → replan 通路影响 agent trajectory。详见
> [`17-suite-wiring.md`](17-suite-wiring.md)。
