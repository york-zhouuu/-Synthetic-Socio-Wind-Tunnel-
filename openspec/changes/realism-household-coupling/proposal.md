## Why

`Chain-Position: spatial-output`（thesis 输出层 — encounter density / 空间激活
信号的真实度）

`docs/agent_system/20-realism-roadmap.md` Stage 4：当前 1000 agent 各自走自己的
scripted_plan，**同 household 的爸妈孩子也是独立**——爸爸 8 点出门、妈妈 9 点
出门、孩子 9 点上学，每个人独立采样 LifePattern，没有家庭协调。

后果：
- baseline encounter density 偏向"独立粒子相遇"模式
- 真实城市里很多偶遇是 household-driven（"我跟孩子去公园"/"夫妻一起买菜"），
  这种**共同 trip 在当前 sim 里完全缺失**
- hp variant 的相对提升被低估——baseline encounter density 比真实低 10-20%，
  让 hp 的 +X% 看起来比现实更显著
- 答辩问"你们的 baseline 没考虑家庭结构"时无法防御

本 change = 拟真度 Stage 4 — 让同 household 的 agent 时间联动。

## What Changes

- **MODIFIED**：`agent::Population` 模型——`AgentProfile.household` 字段从
  当前的"category 字符串"（`family_with_kids` / `couple` / `lone_person`）
  扩展为携带 **household_id**（unique per household）+ `household_role`
  （`parent` / `child` / `partner` / `lone`）。同 household_id 的 agent 共享
  其 LifePattern 的关键 anchor。
- **MODIFIED**：`agent::sample_population`——按 family_composition 分布采样
  household 单元，每个 household 单元内分配 1-5 个 agent，共享 home_location_id。
- **MODIFIED**：`agent::scripted_plan::build_scripted_plan`——读 household
  context（其它成员的 plan）做 weak coordination：父母接送孩子上下学时间点
  对齐；夫妻偶尔同行 errands；household 成员 weekend 30% 概率同 venue。
- **ADDED**：`agent::HouseholdRegistry` —— sim-level service 暴露
  `members_of(household_id)` / `home_location_for(household_id)` —— 让 plan
  生成 + perception / encounter 能查 household 关系。
- **NON-GOAL**：不实现完整家庭日历同步（每天每分钟联动）—— 只做 morning
  drop-off / weekend co-trip 两个粗粒度联动点。
- **NON-GOAL**：不重写 LifePattern——只在生成时 inject household-shared anchor
  字段。

## Capabilities

### New Capabilities
无。

### Modified Capabilities

- `agent`: AgentProfile 加 household_id + household_role；sample_population
  按 household 单元采样；scripted_plan 读 household context；新增
  HouseholdRegistry service。

## Impact

**代码**：
- `agent/profile.py::AgentProfile`：加 `household_id: str`（unique per household）+
  `household_role: Literal["parent", "child", "partner", "lone"]`
- `agent/population.py::sample_population`：先按 family_composition 分布采样
  household 单元（couple_kids → 4 agents；couple_no_kids → 2；lone_person → 1
  等），再赋 household_id + 同 home_location_id
- `agent/scripted_plan.py::build_scripted_plan`：增加 `household_context` kwarg
  接收 same-household-members 的 plan；做 morning drop-off 时间对齐 + weekend
  30% 概率 co-trip
- `agent/__init__.py`：re-export `HouseholdRegistry`
- 新建 `agent/household.py::HouseholdRegistry`：sim-level service

**测试**：
- `tests/test_household_sampling.py`：sample 1000 → distinct household_id 数
  在 [350, 600] 区间（合理 household size 分布）
- `tests/test_household_kin_priors_now_fire.py`：B3 audit 中 household_kin
  rule 应能 fire（之前因为 home_location 各自独立而 0 ties，本 change 修了）
- `tests/test_household_morning_dropoff.py`：parent + child 同 household →
  parent 的 plan 在 child wake_time 后 X 分钟 leave home（接送对齐）
- `tests/test_household_weekend_cotrip.py`：couple_no_kids 同 household 在
  weekend 30% tick 同 location

**API / 契约**：
- `AgentProfile` 新字段默认值兼容现有 1238 测试基线（household_id =
  agent_id 自身 / household_role = "lone"）
- LANE_COVE_PROFILE.distribution 不动；sampling 内部分发 household_id

**外部影响**：
- B3 audit 的 `household_kin` rule 从 0 ties → 真产 ties（修了之前 audit
  发现的限制）
- baseline encounter density 略上升（家人共同 trip 制造的 co-presence）
- hp / gd / pf variant 的相对效应大小可能变化——真跑后看
- 工作量：~7-10 天 implement + 1 天 smoke 验证
