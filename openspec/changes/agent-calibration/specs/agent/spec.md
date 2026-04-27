## ADDED Requirements

### Requirement: AgentProfile 含 gender 字段

`AgentProfile` SHALL 含 `gender: Literal["male","female","non_binary"] | None = None`
字段；`PopulationProfile` SHALL 含 `gender_distribution: Mapping[Gender, float]`
（默认 `{"male":0.487,"female":0.513,"non_binary":0.0}`）；
`sample_population` SHALL 按分布给每个 agent 采样 gender。

设计意图：ABS Census 2021 6 维校准要求 gender 为可观察字段；缺它无法做
strict 6/6 acceptance，且 stereotype-audit 的 gender-swap 协议依赖此字段。

本 change MUST NOT 级联修改 name generator 与 Planner prompt（name-gender
一致性 / 代词使用）—— defer 到 stereotype-audit 或独立 gender-aware-naming
change（见 design Open Q5）。

#### Scenario: sample_population 给每个 agent 写 gender
- **WHEN** 调用 `sample_population(LANE_COVE_PROFILE, seed=42)`
- **THEN** 返回的所有 AgentProfile SHALL 含非 None 的 `gender` 值，
  ∈ {"male","female","non_binary"}

#### Scenario: gender_distribution 验证和=1
- **WHEN** PopulationProfile 构造时 `gender_distribution={"male":0.5,"female":0.4}`
  （和=0.9）
- **THEN** Pydantic SHALL 抛 ValidationError（与现有其它 distribution
  validator 一致）


### Requirement: LANE_COVE_PROFILE 校准至 ABS Census 2021

LANE_COVE_PROFILE 6 维分布 SHALL 校准至 ABS Census 2021 Lane Cove SA2
数据；从 `sample_population(LANE_COVE_PROFILE, n=1000)` 采样的统计分布与
真实人口距离 SHALL 通过 best-effort acceptance（≥ 4/6 维度 p > 0.10）。

校准维度：
1. age（5 岁分组）
2. gender（male/female）
3. housing_tenure（own / mortgage / rent / public）
4. income_tier（low / mid / high）
5. ethnicity_group（按 ancestry 聚合）
6. work_mode（commute / remote / shift / not_working）

距离指标：
- 离散字段：`scipy.stats.chi2_contingency`
- 连续字段：`scipy.stats.kstest`

#### Scenario: 6 维分布对照 ABS Census
- **WHEN** 调用 `sample_population(LANE_COVE_PROFILE, seed=42, n=1000)` 后
  通过 `compute_population_distance(samples, abs_data)` 计算
- **THEN** 返回 dict 含 6 个 dimension key，每个 value 是 p 值；至少 4 个
  p > 0.10

#### Scenario: 报告显式 disclose 未通过维度
- **WHEN** best-effort 通过（4/6 或 5/6）、有维度未达 strict
- **THEN** `assess_population_calibration` 返回 dict 含 `passed: True`、
  `acceptance_level: "best-effort"`、`failed_dimensions: list[str]`；
  publishable suite report SHALL 在 calibration section 列出未通过维度

#### Scenario: strict 通过状态可探测
- **WHEN** 6 个维度全部 p > 0.10
- **THEN** `assess_population_calibration` 返回 `acceptance_level: "strict"`


### Requirement: scripted_plan 三模式（commute / errand / leisure）

非主角 agent（Haiku tier）的脚本化日程 SHALL 按 `profile.work_mode` 分派
为四类 day-shape（commute / remote / shift / not_working），每类内部
SHALL 至少含三类活动 step：commute、errand、leisure。

时间锚点 SHALL 来自 ABS Travel Survey 2021 Sydney（journey-to-work
departure-time 分布）；errand 与 leisure 目的地 SHALL 按 Popular Times
hourly 热度做加权采样。

`build_scripted_plan(profile, destinations, date, rng)` 公共签名 MUST NOT
改变；位置 SHALL 在 `synthetic_socio_wind_tunnel.agent.scripted_plan` 模块
（不再在 `tools/smoke_experiment_demo.py`）。

#### Scenario: commute work_mode 含通勤往返 + errand
- **WHEN** profile.work_mode == "commute"
- **THEN** 返回的 DailyPlan SHALL 含至少 2 个 commute step（home →
  workplace 与 workplace → home）+ ≥ 1 个 errand step（去超市 / 接娃 /
  办事）+ ≥ 1 个 leisure step

#### Scenario: not_working work_mode 无通勤
- **WHEN** profile.work_mode == "not_working"
- **THEN** 返回的 DailyPlan SHALL 不含 commute step；errand / leisure
  step 占满白天

#### Scenario: 公共签名向后兼容
- **WHEN** 既有调用 `build_scripted_plan(profile, destinations, date, rng)`
- **THEN** 调用 SHALL 不抛；返回有效 DailyPlan；`tools/run_variant_suite.py`、
  `tools/run_multi_day_experiment.py`、`tools/replan_trace.py` import
  路径 SHALL 全部指向 `synthetic_socio_wind_tunnel.agent.scripted_plan`


### Requirement: 行为校准至 ABS Travel Survey + Popular Times

baseline 14d × 1000 agent sim 的行为分布 SHALL 通过 best-effort 行为
acceptance：
- OD 矩阵 chi² p > 0.05（对照 ABS Travel Survey Sydney 2021 SA2 → SA2）
- ≥ 70% top-20 POI 的 hourly visit EMD < 0.25（对照 Popular Times 数据）

距离指标：
- OD：`scipy.stats.chi2_contingency`（2D 矩阵）
- Popular Times：`scipy.stats.wasserstein_distance`（per-POI 24h × 7d）

#### Scenario: OD 矩阵对照
- **WHEN** baseline sim 跑完后通过 `compute_od_chi_squared(sim_OD, abs_OD)`
- **THEN** 返回 p 值；best-effort 通过要求 p > 0.05

#### Scenario: Popular Times EMD per POI
- **WHEN** baseline sim 14d 跑完，对每个 top-20 POI 调
  `compute_popular_times_emd(sim_visits, popular_times_data)`
- **THEN** 返回 `dict[poi_id, float]`；best-effort 通过要求 ≥ 70%
  POI 的 EMD < 0.25


### Requirement: calibration 模块独立于 hot path

`synthetic_socio_wind_tunnel.agent.calibration` 模块 SHALL 独立提供
calibration helpers，不被 sim runtime / Planner / AgentRuntime 调用；
sim hot path MUST NOT 包含 calibration 计算（chi² / KS / EMD）。

`tools/run_calibration.py` SHALL 是唯一的 CLI 入口；它跑出的报告（JSON）
SHALL 持久化到 `data/calibration/calibration_report.json`，由 publishable
suite report 链接而非重算。

#### Scenario: hot path 无 calibration import
- **WHEN** 检查 `synthetic_socio_wind_tunnel/agent/runtime.py`、
  `synthetic_socio_wind_tunnel/agent/planner.py` 的 import 列表
- **THEN** 都 SHALL NOT 含 `from .calibration import` 或 `import scipy`

#### Scenario: calibration report 是 sim suite 的输入而非输出
- **WHEN** `tools/run_variant_suite.py` 写最终 report.md 的 calibration
  section
- **THEN** 它 SHALL 读 `data/calibration/calibration_report.json`，
  MUST NOT 重新计算 chi²/KS/EMD


### Requirement: calibration 数据源 ship 在仓库

`data/calibration/` 目录 SHALL 含三份静态 JSON：

1. `abs_census_lanecove_2021.json` — ABS Census 2021 Lane Cove SA2 6 维分布
2. `abs_travel_survey_sydney_2021.json` — ABS Travel Survey OD + 时间分布
3. `lanecove_popular_times.json` — top-20 POI 24h × 7d schedule（Outscraper
   抓取后的快照）

每份 SHALL 含 source URL、download date、schema 版本字段；变更原始数据
SHALL 通过重跑 fetch / 转换脚本（`tools/fetch_popular_times.py` 或一次性
ABS 转换 helper），MUST NOT 直接手编 JSON。

#### Scenario: 数据来源可追溯
- **WHEN** 任意 calibration JSON 被 load
- **THEN** 顶层 dict SHALL 含 `source: str`、`downloaded: str` (ISO date)
  字段；`docs/calibration/01-data-sources.md` SHALL 含对应的下载 URL
  + 字段映射规则
