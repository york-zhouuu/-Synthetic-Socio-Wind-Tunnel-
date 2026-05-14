## 1. AgentProfile 字段扩展

- [x] 1.1 加 `household_id: str` + `household_role: Literal[...]` 字段，默认值兼容（household_id 默认空字符串，household_role 默认 "lone"；HouseholdRegistry.from_profiles 把空 household_id 当 solo 处理）
- [x] 1.2 字段加进去，回归 1238 → 1246 passed 通过

## 2. HouseholdRegistry service

- [x] 2.1 新建 `agent/household.py::HouseholdRegistry`：from_profiles classmethod
- [x] 2.2 实现 `members_of` / `home_location_for` / `siblings_of` / `household_of` / `household_count`
- [x] 2.3 `tests/test_household_registry.py` 9 tests 覆盖 3 接口 + edge cases

## 3. sample_population 改采样为 household-first

- [x] 3.1 实现 `_cluster_into_households` 后处理：按 family_composition 聚类
- [x] 3.2 每 household 单元 unique household_id (`hh_{seed}_{NNNNN}`) + shared home_location（chunk first member 的 home）
- [x] 3.3 角色分配：age < 18 → child；couple_no_kids 第一个 → partner；其它 family-with-kids → parent
- [x] 3.4 test_lanecove_archetypes 已更新（home_location 不再唯一）+ test_social_priors_audit 更新（household_kin 现在 fire 1130 ties）

## 4. scripted_plan household coordination（仍待做）

- [ ] 4.1 `build_scripted_plan` 加 `household_context: dict | None` kwarg
- [ ] 4.2 morning drop-off：parent 的 leave_time 对齐 child wake_time
- [ ] 4.3 weekend co-trip：30% 概率同 household 同 destination
- [ ] 4.4 contract tests for both coordination points

> **Why deferred (2026-05-10)**：autonomous overnight session 完成了
> §1+§2+§3（field + Registry + clustering）这三块 minimum-viable
> infrastructure，足够让 household_kin priors 从 0 → 1130 ties。
> §4 scripted_plan 协调（morning drop-off / weekend co-trip）需要在
> scripted_plan time-of-day 模板里加跨 agent 协调逻辑，估计 3-4 天，
> 需要再开一次专门 session。

## 5. 集成 + smoke（仍待做，依赖 §4）

- [ ] 5.1 修改 multi_day_run 注入 HouseholdRegistry / household_context
- [ ] 5.2 跑 1 seed × 1 day × 100 agent smoke：household_kin tie count > 50
- [ ] 5.3 全量 regression ≥ 1238 passed（minimum viable 已证：1257 passed）

## 6. Sync + archive（待 §4-§5 完成后）

- [ ] 6.1 sync agent spec delta
- [ ] 6.2 strict validate
- [ ] 6.3 archive 到 2026-MM-DD-realism-household-coupling

## ▶ Minimum-viable shipped 2026-05-10

§1-§3 已 ship 进 main：
- AgentProfile 加 household_id + household_role
- HouseholdRegistry service
- sample_population 后处理 _cluster_into_households
- 1000 agent → 344 households (329 shared homes)
- household_kin social_prior 从 0 → 1130 ties
- 1238 → 1257 passed (+19 tests, 0 regression)
