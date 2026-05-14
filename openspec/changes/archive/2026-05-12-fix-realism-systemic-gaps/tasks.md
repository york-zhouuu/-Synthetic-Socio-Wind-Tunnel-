## 1. Cartography importer fix（cafe/restaurant 缺料）

- [x] 1.1 在 `cartography/importer.py` 新增 `_OVERTURE_CATEGORY_TO_TYPE` 完整 mapping（cafe/restaurant/bar/shop/school/hospital/worship/community/office/entertainment 各类直接 category 名，~90 条）
- [x] 1.2 修改 `_infer_building_type`：优先级 direct Overture category → prefix split fallback → amenity → shop → building → default
- [x] 1.3 新增 `_maybe_reclassify_from_affordances(building_type, raw_affordances)`：扫 affordance category 字段，把 utility/industrial/residential/shop/commercial building 升级到 cafe/restaurant/bar 若其 affordance 指向食饮
- [x] 1.4 `_extract_affordances` 不动；reclassification 直接读 raw_affordances 的 `category` 字段（来自 enriched geojson）
- [x] 1.5 在 `_extract_building` 中：初分类后调 `_maybe_reclassify_from_affordances`
- [x] 1.6 新增 `tests/test_cartography_overture_categories.py`：13 scenario（cafe direct mapping、restaurant warehouse 反查、kindergarten → school、affordance 升级、unknown fallback、Lane Cove POI density 4 个）
- [x] 1.7 重建 atlas：`rm data/lanecove_atlas.json && create_atlas_from_osm()`；cafe 2→24、restaurant 2→26、bar 1→3、office 8→34、worship 9→17
- [x] 1.8 跑 `tests/test_cartography.py` 全套；43 PASS 不 regress

## 2. Population sampling cross-constraints

- [x] 2.1 在 `agent/population.py` 新增 `_work_mode_distribution_for_age(age, base_dist)` helper：按 age bracket clamp work_mode
- [x] 2.2 sample_population 内 work_mode 抽前用 `_work_mode_distribution_for_age(age, profile.work_mode_distribution)`
- [x] 2.3 修改 `_occupation_for(work_mode, rng)` → `_occupation_for(age, work_mode, rng)`，按 (age_bracket, work_mode) 选 candidates
- [x] 2.4 定义 `_OCCUPATION_BY_AGE_MODE` lookup（age_bracket × work_mode → list[occupation]，limited to valid WorkMode literals）
- [x] 2.5 新增 `_OCCUPATION_TO_WORKPLACE_TYPES` mapping（teacher → school；nurse → hospital；engineer/writer/manager → office 等）
- [x] 2.6 新增 `_pick_workplace_near(home_id, work_pool, occupation, atlas, max_m, rng)` 函数：按 commute radius + occupation 类型 filter；fallback chain：matched-near → matched-any → closest-in-pool
- [x] 2.7 sample_population pools-path 改用 `_pick_workplace_near` 替代 `rng.choice(pools.work_pool)`；同时接 atlas 参数（增到 sample_population 签名）
- [x] 2.8 现有 `tests/test_agent_population.py` 仍 PASS（旧 deprecation test 保留）；新 cross-constraint 行为通过 systemic audit acceptance 验证

## 3. Household age-gap clamp

- [x] 3.1 在 `agent/population.py::_cluster_into_households` 加 chunk 拆分逻辑：sub-chunk by age-gap ≤ 70；超 70 split 成多个 household
- [x] 3.2 新增 `_assign_household` helper 减少重复代码
- [x] 3.3 新增 `_resolve_home_age_gaps`：post-cluster 处理"独立 household 偶然撞同 home_location"——把 age outlier bump 到 home_pool 中空房或最少人房
- [x] 3.4 验证：60+ 岁年龄差 household 6 → 0；100% validate_against_atlas pass

## 4. LocationPools quotas + scale

- [x] 4.1 在 `agent/location_pools.py` 新增 `PoolQuotas` frozen dataclass + 默认值（work: office=4, school=6, commercial=4, community=2, hospital=1; poi: food_drink=8, shop=6, leisure_building=4, leisure_outdoor=12）
- [x] 4.2 修改 `build_location_pools` 签名增 `quotas: PoolQuotas | None = None, n_agents: int | None = None` 两个参数（max_commute_m 在 sample_population 里）
- [x] 4.3 实现 quotas-aware 采样 `_sample_with_quotas`：per-category 各抽配额；top-off 按 per-cat cap = max(2×quota, target_count // n_categories)
- [x] 4.4 实现 n_agents-scale：work_count = max(quotas.total, n_agents // 5)；poi_count 同；atlas 不足时 cap (不 raise)
- [x] 4.5 修改 `tests/test_location_pools.py`：新增 4 scenario（food_drink ≥ 8、school ≤ 7、n_agents 缩放、quota undersupply 不 raise）；17 PASS

## 5. scripted_plan time-sort + meal + school_dest

- [x] 5.1 在 `agent/scripted_plan.py::build_scripted_plan` 新增 `atlas` 参数（kwargs，default None）
- [x] 5.2 新增 `_meal_steps(profile, atlas, pools, rng, weekday_idx) -> list[PlanStep]`：返回 3 个 meal step（breakfast/lunch/dinner）；commute/shift agent lunch 40% workplace-邻近 cafe；remote 20%；dinner 15% restaurant
- [x] 5.3 build_scripted_plan 在 day_shape 返回后调用 `_meal_steps` 注入 meals
- [x] 5.4 新增 `_pick_school_destination(atlas, pools, fallback, rng)` 从 work_pool school 子集选；新增 `_reroute_school_pickup` post-process 把 kid step destination 改成真 school
- [x] 5.5 build_scripted_plan 返回 DailyPlan 前 `steps.sort(key=_time_to_minutes)`
- [x] 5.6 修改 `tests/test_scripted_plan.py`：现有 26 test 全 PASS；audit verify 时间单调 100% / meals 平均 3.0 / school_pickup 100% school

## 6. Suite & tool wiring（atlas + pools 透传）

- [x] 6.1 修改 `tools/run_variant_suite.py`：build_location_pools 改用 quotas 默认 + n_agents=n_agents；sample_population 加 `atlas=atlas`
- [x] 6.2 修改 `tools/run_variant_suite.py`：build_scripted_plan 加 `atlas=atlas`（2 处 callsite）
- [x] 6.3 修改 `tools/run_multi_day_experiment.py`、`tools/replan_trace.py`、`tools/measure_group_alignment.py`：sample_population 加 atlas（sed batch）
- [x] 6.4 `tools/suite_stub_llm.py::make_llm_client` 已透传 pools，无需改

## 7. Systemic realism audit 工具

- [x] 7.1 新建 `tools/audit_realism_systemic.py`：跑 1 个 baseline seed 后 audit 10 个维度
- [x] 7.2 exit code 0 全过 / 2 任一不过
- [x] 7.3 新增 `tests/test_audit_realism_systemic.py`：3 scenario（合规 fixture PASS、伪造高 street FAIL、audit 维度完整）；3 PASS

## 8. 验证 + smoke 跑

- [x] 8.1 `python -m pytest tests/` 全套通过：**1311 passed, 3 skipped, 0 failed**（含新增 28 test）
- [x] 8.2 跑 1-day baseline smoke：`typed_smoke_unit` + `systemic_smoke_unit` 完成
- [x] 8.3 跑 `tools/audit_realism_systemic.py`：**全 10 维 ACCEPTANCE: PASS**（residential 66.6% / food_drink 26.7% / school_share 37.5% / school_pickup 100% / 童工 0 / occupation mismatch 0 / commute median 1499m / meals 3.0/day / age_gap 0）
- [x] 8.4 跑 `tools/audit_dwell_distribution.py`：residential 66.6% / street 0% PASS（旧 acceptance 不 regress）
- [ ] 8.5 跑 14-day × 100 agent × DeepSeek smoke：`d1pp_systemic_verify`（等用户确认 ~4hr）
- [ ] 8.6 D1' 重跑后 audit 全过 → 写对比报告 `docs/2026-05-12-d1pp-systemic-vs-old.md`

## 9. 文档 + archive

- [ ] 9.1 更新 `docs/audit/2026-05-12-realism-audit.md`：增加"修复结果"段落
- [ ] 9.2 更新 `docs/limitations-ethics.md`：在"旧实验数据局限"段补 cartography POI miscategorization
- [ ] 9.3 更新 `docs/agent_system/20-realism-roadmap.md`：把 systemic-gaps fix 列入 Stage 0.5 续
- [ ] 9.4 archive 该 change：`openspec archive fix-realism-systemic-gaps`（等 §8.5-8.6 完成后）
