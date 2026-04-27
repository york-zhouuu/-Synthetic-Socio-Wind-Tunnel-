## Why

`agent-calibration` 用了 ABS DataPack 5 张表（G01/G09/G17/G37/G62）做 6 维校准。
但 DataPack 是 60+ 张表的完整 community profile——还有大量与 thesis 直接相关
的字段没挖。

**Thesis 主问题**：什么让人在物理社区里 *rooted* 还是 *floating*？这决定了
hyperlocal push 的人群效果差异（rival hypothesis 的核心切口）。ABS 给了几张
表精准对应这个分轴：

- **照护时长**（G24/G25/G26）—— "被绑在 local 物理空间的强度"
- **社区资历**（G45）—— "你在 Lane Cove 住了多久"
- **志愿工作**（G23）—— "你已经有 weak-tie 网络吗"
- **语言能力**（G13）—— "你能不能听懂 English-only 的推送"
- **家庭结构**（G27）—— "你日常被 dependents 绑住的程度"

把这些纳入 AgentProfile 会让 sim 能跑出 **新一类 rival hypothesis**：
> H_care_isolation: 高 care 责任的 agent 物理 anchored 但 attention 已被瓜分 —— hyperlocal push 影响小
> H_newcomer_lure: 新搬来的 agent attention 自由但 community ties 浅 —— hyperlocal push 影响大
> H_baseline: 没有差异

如果实测出 dose-dependent 差异（按 care_hours 或 community_tenure 分组），是
**论文级别**的发现，比纯 hyperlocal-vs-baseline 强一个量级。

**Chain-Position**: `infrastructure`（agent profile schema 扩展；不动 attention
主链 / planner / runtime 行为契约）

**前置**：`agent-calibration`（已 implemented，未 archive；本 change 复用其
LANE_COVE_PROFILE + ABS DataPack 数据源）

## What Changes

### 1. `AgentProfile` 新增 13 个字段（全 Optional，向后兼容）

#### Tier 1 — Thesis 核心（5 字段）
- `community_tenure_5yr: Literal["new_<1yr", "recent_1_5yr", "established_5plus"] | None` (G45)
- `unpaid_child_care_hours: Literal["none", "1_14", "15_29", "30plus"] | None` (G26)
- `unpaid_domestic_hours: Literal["none", "1_14", "15_29", "30plus"] | None` (G24)
- `unpaid_disability_care_hours: Literal["none", "yes"] | None` (G25)
- `volunteer_status: Literal["volunteer", "non_volunteer"] | None` (G23)

#### Tier 2 — 现有字段精化（5 字段）
- `english_proficiency: Literal["very_well", "well", "not_well", "not_at_all", "english_only"] | None` (G13)
- `family_composition: Literal[7-bucket]` (G27/G29)：lone_person / couple_no_kids /
  couple_kids_under_15 / couple_kids_15plus / one_parent_family / group_household / other
  → **替代**当前 3-bucket `Household` 字段（household 字段保留作 alias 不破契约）
- `dwelling_structure: Literal["separate_house", "semi_detached", "flat_apartment", "other_dwelling"] | None` (G36)
- `vehicles_at_dwelling: Literal["0", "1", "2", "3plus"] | None` (G34)
- `year_of_arrival_bucket: Literal["pre_2000", "2000_2010", "2011_2015", "2016_2021", "australian_born"] | None` (G10)
  → 替代当前 ad-hoc `migration_tenure_years` gauss 采样

#### Tier 3 — 完整性 / sub-thesis（3 字段）
- `indigenous_status: Literal["indigenous", "non_indigenous"] | None` (G07)
- `disability_status: Literal["needs_assistance", "no_assistance"] | None` (G18)
- `education_level: Literal["postgrad", "bachelor", "diploma", "year_12", "year_11_or_below", "no_qualification"] | None` (G16+G49)

### 2. `PopulationProfile` 同步新增 13 个 distribution 字段

每个对应 AgentProfile 字段，所有 default 用 ABS 派生值；保留 `Optional` 边
界，缺数据时不强制采样。

### 3. `LANE_COVE_PROFILE` 全字段更新

从 ABS DataPack 13 张新表抽取分布值（一次性运行 `tools/convert_abs_census.py
--full`）；commit 进 git。

### 4. `tools/convert_abs_census.py` 扩展

加 `--full` flag 触发新表抽取。每张表对应一个 `_xxx_distribution` extractor：

- G07 → indigenous_status
- G10 → year_of_arrival_bucket
- G13 → language_at_home + english_proficiency（双输出）
- G16+G49 → education_level（合并）
- G18 → disability_status
- G23 → volunteer_status
- G24 → unpaid_domestic_hours
- G25 → unpaid_disability_care_hours
- G26 → unpaid_child_care_hours
- G27 → family_composition（与 G29 交叉验证）
- G34 → vehicles_at_dwelling
- G36 → dwelling_structure
- G45 → community_tenure_5yr

输出仍是 `data/calibration/abs_census_lanecove_2021.json`，schema 增 13 个新
distribution。向后兼容（旧 6 维 distribution 不动）。

### 5. `sample_population` 采样新字段

每个新字段一行 `_weighted_pick`；结果赋值到 AgentProfile。当 PopulationProfile
缺对应 distribution 时，字段保持 `None`。

### 6. `calibration.py` 把新字段纳入校准评估

`compute_population_distance` 自动覆盖所有有 distribution 的维度（不限于原 6
维）。`assess_population_calibration` 更新阈值：

- best-effort: ≥ 4/6 原维度 通过 + ≥ 6/13 新维度 通过 + 总通过率 ≥ 60%
- strict: 原 6 维全过 + 新 13 维 ≥ 10 个通过

新维度阈值 calibration 不阻塞 archive（参照 best-effort 政策）。

### 7. 测试

- `tests/test_agent_population.py` 扩展：13 个新字段在 1000-sample 都出现
  （或允许稀有值不出现）
- `tests/test_calibration.py` 扩展：能读 13 维 ABS 数据 + 计算 chi²
- 新 `tests/test_profile_enrich_thesis_dims.py`：rival hypothesis 切片验证
  （高 care_hours agent 子集行为差异可观察）

## Non-goals

- **不**改 attention chain / Planner / AgentRuntime 行为契约
- **不**做 stereotype audit / face validity（独立 change）
- **不**让 LLM prompt 引用所有 13 个新字段（信息过载会降低 LLM 输出质量；
  prompt 设计走单独 `agent-profile-prompt-aware` change）
- **不**把每个新字段都强制 best-effort 通过—— Tier 3 字段允许 failing 状态
- **不**做 G14（religion）/ G19（health condition）/ G54（industry）/ G60
  （occupation）—— 离 thesis 远，scope creep
- **不**做 G44（1-year-ago residence）—— G45（5-year）已够 thesis 切片

## Capabilities

### Modified Capabilities

- `agent`: AgentProfile / PopulationProfile schema 扩展（13 新字段 + 13 新
  distribution）

### New Capabilities

（无）

## Impact

- **修改文件**：
  - `synthetic_socio_wind_tunnel/agent/profile.py`（13 字段 + 13 Literal 类型）
  - `synthetic_socio_wind_tunnel/agent/population.py`（13 distribution + sampling）
  - `synthetic_socio_wind_tunnel/agent/calibration.py`（自动覆盖新维度）
  - `tools/convert_abs_census.py`（13 个新 extractor）
- **修改数据**：
  - `data/calibration/abs_census_lanecove_2021.json`（13 新 distribution；旧 6 维不动）
- **新增测试**：
  - `tests/test_profile_enrich_thesis_dims.py`（rival hypothesis 切片验证）
  - 现有 test_agent_population / test_calibration 扩展
- **不改**：
  - PlanStep / DailyPlan / Planner / AgentRuntime 公共契约
  - attention / orchestrator / metrics
  - Atlas / cartography
- **下游影响**：
  - `agent-calibration` 的 LANE_COVE_PROFILE 6 维仍 best-effort（不会倒退）
  - 新字段的 distribution match 得越好，downstream `stereotype-audit` 切片
    分析越细
  - 后续 `face-validity-protocol` 用真人评估时，profile 维度越多，face
    validity 越易过（"这看起来像真社区"）
- **预计周期**：3-5 day（13 个新字段 schema + 13 个 ABS extractor + 测试）
- **回滚**：所有新字段 Optional with default None；git revert + 删
  data/calibration JSON 新字段即可
