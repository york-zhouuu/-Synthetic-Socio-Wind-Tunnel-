## Why

`validation-strategy` (2026-04-25) 把 8 项 publishable checklist 上锁，其中前 3 项
是硬 ✗：

```
1. Calibration passed                      ✗ (population + behavioral 都未做)
2. Stereotype audit passed                 ✗ (三协议都未跑)
3. Face validity passed                    ✗ (未做 Prolific)
```

任一 ✗ 即 `[unpublishable preview]`，suite 跑出来的报告都打这个标签。
Calibration 是其中 publishable 路径的**第 1 个瓶颈**——后续 stereotype audit /
face validity 都依赖一个"分布像样的 LANE_COVE_PROFILE"。

当前现状：

- `LANE_COVE_PROFILE` 在 `synthetic_socio_wind_tunnel/agent/population.py:308`
  是手工估测的占位（age / gender / occupation 分布作者直接拍脑袋写的；
  fitness-audit `phase1-baseline.profile-preset-ground-truthed` 因此 FAIL）
- `build_scripted_plan` 在 `tools/smoke_experiment_demo.py:74`——给 990 个
  Haiku tier agent 用的"脚本化日程"——只有"4-6 个 random move slot"，没有
  通勤 / 办事 / 休闲之分；行为分布不可能 match 任何真实出行调查
- 没有 ABS Census / Travel Survey / Popular Times 数据接入

本 change 实现 `validation-strategy` Part IV + Part V 规定的两套 calibration：
**人口校准**（match ABS Census 6 维分布）+ **行为校准**（match ABS Travel
Survey OD + Popular Times 时段热度）。

**Chain-Position**: `infrastructure`（不动 thesis 也不动 attention 主链；服务
publishable 路径门禁）。

**Fitness-report 锚点**：
- 解 `phase1-baseline.profile-preset-ground-truthed` FAIL
- 解 publishable checklist #1（calibration）✗ → ✓
- 不动 #2/#3（独立 change：`stereotype-audit` / `face-validity-protocol`）

## What Changes

### 1. 人口数据 ground truth（ABS Census 静态快照）

新建 `data/calibration/abs_census_lanecove_2021.json`——手工从 ABS DataLab
Lane Cove SA2 表格下载后转为 JSON，含 6 维分布：

- `age`：5 岁分组
- `gender`：male / female 比例
- `housing_tenure`：own / mortgage / rent / public housing
- `income_tier`：low / mid / high（按 Lane Cove 中位数定义）
- `ethnicity_group`：按 ancestry 字段聚合
- `work_mode`：commute / remote / shift / not-working

文档 `docs/calibration/01-data-sources.md` 记录数据源 URL + 下载日期 + 字段
映射规则。

### 2. Popular Times ground truth（Outscraper 自动抓 + ship JSON）

新增 `tools/fetch_popular_times.py`：用 Outscraper free tier API（免费额度
500 businesses，我们只用 ~20）抓 Lane Cove top-20 POI 的 24h × 7d schedule，
存成 `data/calibration/lanecove_popular_times.json`。

需要 `OUTSCRAPER_API_KEY` env；fetch 脚本可重跑（数据更新时），sim 跑校准
只读 cached JSON。

### 3. ABS Travel Survey OD 矩阵（静态快照）

`data/calibration/abs_travel_survey_sydney_2021.json`——手工从 BTS NSW
Household Travel Survey 下载，含 journey-to-work OD 矩阵 + departure-time
分布。

### 4. `LANE_COVE_PROFILE` 重新校准

修改 `synthetic_socio_wind_tunnel/agent/population.py::LANE_COVE_PROFILE` 的
分布数值，让 `sample_population(LANE_COVE_PROFILE, n=1000)` 的 6 维分布
match ABS Census 数据。

新增 calibration helper `synthetic_socio_wind_tunnel/agent/calibration.py`：

- `compute_population_distance(samples, abs_data) -> dict[dim, p_value]`
- `assess_population_calibration(...)`：返回 strict/best-effort 状态

### 5. `build_scripted_plan` 重写为 commute / errand / leisure 三类

把 `build_scripted_plan` 从 `tools/smoke_experiment_demo.py` 提升到生产代码
`synthetic_socio_wind_tunnel/agent/scripted_plan.py`，重写为按 `work_mode`
分配三类活动：

- **commute**：home → workplace → home（按 ABS Travel Survey OD + 时间分布）
- **errand**：去超市 / 接娃 / 看医生（按 work_mode 给概率；errand 时段
  Match Popular Times 中相应类别 POI 的热度）
- **leisure**：咖啡馆 / 公园（按 personality.openness + Popular Times）

`tools/*` 里所有 `build_scripted_plan` import 路径同步迁移。

### 6. Behavioral calibration helper

`synthetic_socio_wind_tunnel/agent/calibration.py` 加：

- `compute_od_chi_squared(sim_OD, abs_OD) -> p_value`
- `compute_popular_times_emd(sim_visits, popular_times) -> dict[poi_id, emd]`
- `assess_behavioral_calibration(...)`

### 7. CLI: `tools/run_calibration.py`

跑全套 calibration assessment：

- 采样 1000 agent → 检查 6 维分布
- 跑 baseline 14d sim → 检查 OD + Popular Times
- 输出 `data/calibration/calibration_report.json` 含 strict/best-effort 通过状态

报告写入 publishable suite report 的 calibration 段落（接入
`run_variant_suite.py` 的 contest scorer）。

### 8. Acceptance（best-effort 优先）

- **Best-effort 通过**（本 change 目标）：
  - 人口：≥ 4/6 维度 p > 0.10 + report 显式 disclose 缺哪几维
  - 行为：OD chi² p > 0.05 OR ≥ 70% POI EMD < 0.25（半档放宽）
- **Strict 通过**（stretch goal，本 change 不 block）：
  - 人口：6/6 维度 p > 0.10
  - 行为：OD p > 0.10 AND ≥ 80% POI EMD < 0.20

### 9. 测试

- `tests/test_calibration.py`：
  - chi-squared / KS / EMD helpers 数值正确性
  - `compute_population_distance` 在 mock 数据上的回归
  - `assess_*_calibration` 决策逻辑（threshold 边界）
- `tests/test_scripted_plan.py`：
  - 三类活动比例符合 work_mode 配置
  - commute step 起终点用 home_location + workplace
  - 时间分布按 ABS departure-time

## Non-goals

- **不**做 Prolific face validity（独立 `face-validity-protocol` change）
- **不**做 stereotype audit 三协议（独立 `stereotype-audit` change）
- **不**改 PlanStep / DailyPlan / Planner 公共契约
- **不**改 attention chain / replan 逻辑
- **不**用 ML / 自动调参——LANE_COVE_PROFILE 数值靠"人工查 ABS 表 + 手填"
  足够（6 维 × ~10 桶 = 60 个数）；过度自动化是 scope creep
- **不**实现 Strict acceptance——best-effort 是本 change 目标；strict 不达
  标不阻塞 archive
- **不**接入 ABS TableBuilder live API（用 static snapshot；重现性 > 新鲜度）

## Capabilities

### Modified Capabilities

- `agent`: 加人口校准要求 + scripted_plan 三类化 + 公共 API（`calibration.py`）
- `validation-strategy`: 把 Part IV/V 的"实施"细节从 doc 提升到 spec scenario

### New Capabilities

（无）

## Impact

- **修改文件**：
  - `synthetic_socio_wind_tunnel/agent/population.py`（LANE_COVE_PROFILE 数值校准）
  - `synthetic_socio_wind_tunnel/agent/calibration.py`（新文件）
  - `synthetic_socio_wind_tunnel/agent/scripted_plan.py`（新文件，从 smoke_experiment_demo 提升）
  - `tools/smoke_experiment_demo.py`（删除 `build_scripted_plan`，改 import）
  - `tools/run_multi_day_experiment.py`、`tools/run_variant_suite.py`、
    `tools/replan_trace.py`（更新 import 路径）
- **新增文件**：
  - `tools/fetch_popular_times.py`（Outscraper API）
  - `tools/run_calibration.py`（CLI）
  - `data/calibration/abs_census_lanecove_2021.json`
  - `data/calibration/abs_travel_survey_sydney_2021.json`
  - `data/calibration/lanecove_popular_times.json`
  - `docs/calibration/01-data-sources.md`
- **新增依赖**：
  - `scipy`（用于 chi² / KS test；EMD 可手写或用 `scipy.stats.wasserstein_distance`）
  - `requests`（已有）
- **下游影响**：
  - `phase1-baseline.profile-preset-ground-truthed` fitness-audit FAIL → PASS
  - publishable checklist #1 ✗ → ✓
  - 后续 `stereotype-audit` / `face-validity-protocol` 解锁
- **预计周期**：1-2 周（含数据下载 + 校准迭代 + Outscraper 抓取）
- **前置依赖**：无（独立 change）
- **回滚**：data/calibration 目录可删 + git revert population.py + scripted_plan.py
