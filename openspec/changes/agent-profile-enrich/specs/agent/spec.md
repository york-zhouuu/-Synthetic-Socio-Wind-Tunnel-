## ADDED Requirements

### Requirement: AgentProfile 含 thesis-direct 维度字段

`AgentProfile` SHALL 含以下 13 个 `Literal[...] | None = None` 字段，对应
ABS Census 2021 的 thesis-relevant 维度。所有字段 default `None`，向后兼容
存量代码。

**Tier 1（thesis 核心，5 字段）**：
- `community_tenure_5yr` — `Literal["new_<1yr","recent_1_5yr","established_5plus"]` (G45)
- `unpaid_child_care_hours` — `Literal["none","1_14","15_29","30plus"]` (G26)
- `unpaid_domestic_hours` — `Literal["none","1_14","15_29","30plus"]` (G24)
- `unpaid_disability_care_hours` — `Literal["none","yes"]` (G25)
- `volunteer_status` — `Literal["volunteer","non_volunteer"]` (G23)

**Tier 2（精化现有，5 字段）**：
- `english_proficiency` — `Literal["very_well","well","not_well","not_at_all","english_only"]` (G13)
- `family_composition` — `Literal["lone_person","couple_no_kids","couple_kids_under_15","couple_kids_15plus","one_parent_family","group_household","other"]` (G27/G29)
- `dwelling_structure` — `Literal["separate_house","semi_detached","flat_apartment","other_dwelling"]` (G36)
- `vehicles_at_dwelling` — `Literal["0","1","2","3plus"]` (G34)
- `year_of_arrival_bucket` — `Literal["pre_2000","2000_2010","2011_2015","2016_2021","australian_born"]` (G10)

**Tier 3（完整性，3 字段）**：
- `indigenous_status` — `Literal["indigenous","non_indigenous"]` (G07)
- `disability_status` — `Literal["needs_assistance","no_assistance"]` (G18)
- `education_level` — `Literal["postgrad","bachelor","diploma","year_12","year_11_or_below","no_qualification"]` (G16+G49)

设计意图（见 `agent-profile-enrich` change design D1-D7）：让 sim 区分
*rooted* vs *floating* agent，支持 hyperlocal-push 在不同人群上效果差异
的 rival hypothesis。

#### Scenario: 存量代码无新字段不报错
- **WHEN** 既有 `AgentProfile(agent_id=..., name=..., age=..., occupation=...,
  household=..., home_location=...)` 调用
- **THEN** SHALL 不抛；新字段全为 None；公共 API 兼容

#### Scenario: 字段类型严格
- **WHEN** 构造 `AgentProfile(community_tenure_5yr="brand_new")`（非 Literal 值）
- **THEN** Pydantic SHALL 抛 ValidationError


### Requirement: PopulationProfile 含 13 个新 distribution

`PopulationProfile` SHALL 含 13 个 distribution 字段对应 AgentProfile 新字段，
default 为 ABS-derived 值或合理 fallback；MUST 通过现有 `_dist_sum_to_one`
validator。

`sample_population` SHALL 给每个 agent 用 `_weighted_pick` 从对应 distribution
采样新字段；分布为空（默认空 dict）时字段保持 `None`。

#### Scenario: sample_population 写新字段
- **WHEN** 调用 `sample_population(LANE_COVE_PROFILE, seed=42)`
- **THEN** 返回的所有 AgentProfile SHALL 含 13 新字段的非 None 值（前提
  LANE_COVE_PROFILE 已配置所有 13 distribution）

#### Scenario: 缺 distribution 字段保持 None
- **WHEN** PopulationProfile 不配置 `disability_status_distribution`
- **THEN** 采样产生的 agent.disability_status SHALL == None；其它已配置
  字段不受影响


### Requirement: family_composition 与 household 自动映射

`sample_population` SHALL 优先按 `family_composition_distribution` 采样
agent.family_composition，再用以下映射回填 agent.household：
- `lone_person` → `single`
- `couple_no_kids` / `couple_kids_15plus` → `couple`
- `couple_kids_under_15` / `one_parent_family` → `family_with_kids`
- `group_household` / `other` → `single`

household 字段公共类型 MUST NOT 改变（保持 3-bucket Literal）；现有依赖
`agent.household` 的代码 MUST 继续工作。

#### Scenario: family_composition → household 映射一致
- **WHEN** sample_population 给 agent.family_composition 写入
  `couple_kids_under_15`
- **THEN** 同一 agent.household SHALL == `family_with_kids`

#### Scenario: 缺 family_composition_distribution 的回退
- **WHEN** PopulationProfile 没配置 `family_composition_distribution` 但有
  `household_distribution`
- **THEN** sample_population SHALL 用 household_distribution 采样；
  agent.family_composition 保持 None；agent.household 仍按当前逻辑赋值


### Requirement: calibration 评估新维度递进式

`assess_population_calibration` SHALL 按 Tier 评估：
- **Tier 1（核心 6 维 + 新 5 维）**：现有 6 维 ≥ 4 通过 **AND** Tier 1 新 5 维
  ≥ 3 通过 → best-effort
- **Strict**：现有 6 维全过 **AND** Tier 1 新 5 维全过 **AND** Tier 2 新 5 维
  ≥ 3 通过

Tier 3 字段（indigenous / disability / education）状态 SHALL 出现在 disclosure
段，但 MUST NOT 阻塞 acceptance_level 升级。

`compute_population_distance` SHALL 自动覆盖 abs_data["distributions"] 里所有
key，不限于原 6 维。

#### Scenario: 新 Tier 1 5 维全过升级 strict
- **WHEN** 现有 6 维全 p > 0.10 + Tier 1 新 5 维全 p > 0.10 + Tier 2 5 维有
  3 个 p > 0.10
- **THEN** acceptance_level SHALL == "strict"

#### Scenario: Tier 3 失败不阻塞 best-effort
- **WHEN** 现有 6 维 4 过 + Tier 1 5 维 3 过 + Tier 3 全失败
- **THEN** acceptance_level SHALL == "best-effort"；report SHALL 在
  disclosure 段列出 Tier 3 failed dims


### Requirement: convert_abs_census.py 含 `--full` flag

`tools/convert_abs_census.py` SHALL 接受 `--full` flag：
- 不带：输出原 6 维 distribution（agent-calibration 行为）
- 带：输出原 6 维 + 13 新维度 distribution；JSON 顶层 `distributions` 字段
  不删 6 维原 key，只新增

#### Scenario: --full 输出 19 维
- **WHEN** 跑 `python3 tools/convert_abs_census.py --full`
- **THEN** 输出 JSON 的 `distributions` SHALL 含 19 个 key（age, gender,
  housing_tenure, income_tier, ethnicity_group, work_mode + 13 new）

#### Scenario: 不带 --full 输出 6 维
- **WHEN** 跑 `python3 tools/convert_abs_census.py`（无 flag）
- **THEN** 输出 JSON 的 `distributions` SHALL 仅含原 6 个 key（向后兼容）
