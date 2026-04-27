# Tasks — agent-profile-enrich

把 13 张 thesis-relevant ABS 表挖进 AgentProfile，让 sim 能切片 *rooted* vs
*floating* agent，支持新一类 rival hypothesis。

**Chain-Position**: `infrastructure`
**前置**: `agent-calibration`（已 implemented，未 archive；本 change 复用其
DataPack 数据源）
**预计周期**: 3-5 day

## 1. Schema 扩展（阶段 1，0.5 day）

### 1.1 AgentProfile 新字段
- [x] 1.1.1 加 13 个 Literal 类型定义到 `synthetic_socio_wind_tunnel/agent/profile.py`
  - Tier 1（5）：community_tenure_5yr, unpaid_child_care_hours,
    unpaid_domestic_hours, unpaid_disability_care_hours, volunteer_status
  - Tier 2（5）：english_proficiency, family_composition,
    dwelling_structure, vehicles_at_dwelling, year_of_arrival_bucket
  - Tier 3（3）：indigenous_status, disability_status, education_level
- [x] 1.1.2 13 字段都 Optional，default None
- [x] 1.1.3 export 新 Literal types 到 `synthetic_socio_wind_tunnel/agent/__init__.py`

### 1.2 PopulationProfile 新 distribution
- [x] 1.2.1 加 13 个 distribution 字段到 PopulationProfile，每个对应 AgentProfile
  字段
- [x] 1.2.2 default 用 reasonable fallback（最常见值占主导，其它平均分）
- [x] 1.2.3 添加到现有 `_dist_sum_to_one` field_validator 列表

### 1.3 household ↔ family_composition 映射
- [x] 1.3.1 加 helper `_household_from_family_composition(fc) -> Household`
- [x] 1.3.2 sample_population 内部：先采 family_composition，再 derive household
- [x] 1.3.3 fallback：family_composition_distribution 缺时退回 household_distribution

## 2. ABS Converter 扩展（阶段 2，1 day）

### 2.1 加 13 个 extractor 函数到 `tools/convert_abs_census.py`
- [x] 2.1.1 `_indigenous_status_distribution(g07)` —— G07 Tot 数据
- [x] 2.1.2 `_year_of_arrival_distribution(g10)` —— G10，含 australian_born 计算
  （从 G09 总人口 - G10 海外出生总和）
- [x] 2.1.3 `_language_at_home_distribution(g13)` —— G13 主要语言 top-10
- [x] 2.1.4 `_english_proficiency_distribution(g13)` —— G13，整合 english-only
  为单独桶
- [x] 2.1.5 `_education_level_distribution(g16, g49)` —— 合并 G16 + G49
- [x] 2.1.6 `_disability_status_distribution(g18)`
- [x] 2.1.7 `_volunteer_status_distribution(g23)`
- [x] 2.1.8 `_unpaid_domestic_hours_distribution(g24)`
- [x] 2.1.9 `_unpaid_disability_care_distribution(g25)` —— 二元 yes/no
- [x] 2.1.10 `_unpaid_child_care_distribution(g26)`
- [x] 2.1.11 `_family_composition_distribution(g27, g29)` —— 优先 G29，G27
  备用
- [x] 2.1.12 `_vehicles_distribution(g34)`
- [x] 2.1.13 `_dwelling_structure_distribution(g36)`
- [x] 2.1.14 `_community_tenure_distribution(g45)` —— 5-year residence

### 2.2 `--full` flag
- [x] 2.2.1 argparse 加 `--full` action="store_true"
- [x] 2.2.2 `convert()` 接收 `full` 参数；不带只输出原 6 维
- [x] 2.2.3 带 flag 时所有 13 张表读 + 新 distribution 加到 JSON

### 2.3 跑一次更新 JSON
- [x] 2.3.1 `python3 tools/convert_abs_census.py --full`
- [x] 2.3.2 验证输出含 19 维（6 + 13），每个 sum 接近 1.0
- [x] 2.3.3 commit `data/calibration/abs_census_lanecove_2021.json`

### 2.4 文档更新
- [x] 2.4.1 `docs/calibration/01-data-sources.md` 加 13 张新表的桶映射规则

## 3. Profile values 接入（阶段 3，0.5 day）

### 3.1 LANE_COVE_PROFILE 13 个新 distribution
- [x] 3.1.1 从 `data/calibration/abs_census_lanecove_2021.json` 读 13 维值
- [x] 3.1.2 hardcode 进 LANE_COVE_PROFILE（不动态读取以保持 import 时确定性）
- [x] 3.1.3 数值精度同当前格式（4 位小数）

### 3.2 sample_population 采样
- [x] 3.2.1 13 个 `_weighted_pick` 调用
- [x] 3.2.2 采样结果赋值到 AgentProfile（Optional 字段，distribution 缺时 None）
- [x] 3.2.3 family_composition → household 映射在采样后立即执行

## 4. Calibration 扩展（阶段 4，0.5 day）

### 4.1 自动覆盖新维度
- [x] 4.1.1 `compute_population_distance` 不限定 dim 列表，遍历 abs_data
  ["distributions"] keys
- [x] 4.1.2 `_sample_attribute` 加 13 个新 dim 的 case
- [x] 4.1.3 验证：跑 run_calibration --mode population 输出含 19 维

### 4.2 递进式 acceptance
- [x] 4.2.1 改 `assess_population_calibration` 签名加 `tier1_dims` /
  `tier2_dims` / `tier3_dims` 参数（kwargs）
- [x] 4.2.2 默认 tier 列表 hardcode 在 calibration.py 顶部常量
- [x] 4.2.3 strict 阈值：Tier 1 全过 + Tier 2 ≥ 3
- [x] 4.2.4 best-effort 阈值：Tier 1 核心 6 维 ≥ 4 过 **AND** 新 5 维 ≥ 3 过

### 4.3 报告分组
- [x] 4.3.1 `tools/run_calibration.py` 输出按 Tier 分组
- [x] 4.3.2 disclosure 段列出 Tier 3 状态（不阻塞）

## 5. 测试（阶段 5，1 day）

### 5.1 现有测试扩展
- [x] 5.1.1 `tests/test_agent_population.py`：
  - test_every_distribution_value_appears 扩展到 13 新字段
  - 新 test：family_composition → household 映射正确
  - 新 test：缺 distribution 字段 → 字段保持 None
- [x] 5.1.2 `tests/test_calibration.py`：
  - test_compute_population_distance 用扩展 abs_data（19 维）
  - test_assess_population_calibration_tiered 验证递进逻辑
- [x] 5.1.3 `tests/test_scripted_plan.py`：
  - 验证 vehicles_at_dwelling 影响通勤模式（高车辆 → drive；0 车 → transit
    proxy）—— 留 TODO，本 change 不实施 day-shape 分支变化（独立 change
    再做）

### 5.2 新测试 — thesis-direct dims
- [x] 5.2.1 新建 `tests/test_profile_enrich_thesis_dims.py`：
  - test_high_care_hours_vs_low_care_hours 切片：1000-sample 中能找到 ≥
    100 个高 care + 100 个低 care agent
  - test_new_vs_established_community_tenure 切片：≥ 100 个 new + 100 个
    established
  - test_volunteer_subset_size：≥ 80 个 volunteer agent
  - 这些是 downstream rival-hypothesis 切片的"前提存在"测试

## 6. 验证（阶段 6，0.5 day）

- [x] 6.1 全 pytest 通过（594+ tests + 新增 ~25 个）
- [x] 6.2 `tools/convert_abs_census.py --full` 跑通
- [x] 6.3 `tools/run_calibration.py --mode population` 输出含 19 维评估
- [x] 6.4 `python3 tools/run_variant_suite.py --variants baseline,hyperlocal_push
  --seeds 1 --num-days 3 --agents 20 --mode dev --phase-days 1,1,1` 端到端不破
- [x] 6.5 `openspec validate agent-profile-enrich --strict` 通过

## 7. 文档

- [x] 7.1 `docs/calibration/01-data-sources.md`：13 张新表 + 映射规则
- [x] 7.2 `docs/agent_system/19-system-snapshot.md` 历史决策点表
- [x] 7.3 README 加一段 "Agent profile dimensions" 简述（可选）

## 8. archive sync

- [x] 8.1 archive 时把 delta spec 合入 `openspec/specs/agent/spec.md`
- [x] 8.2 commit
