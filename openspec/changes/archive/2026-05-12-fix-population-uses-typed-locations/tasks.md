## 1. Atlas 便利方法（cartography spec）

- [x] 1.1 在 `synthetic_socio_wind_tunnel/atlas/service.py` 新增 `list_workplaces()` 方法（返回 building_type ∈ {office, school, commercial, community, hospital}），按 id 字母序
- [x] 1.2 在同文件新增 `list_pois() -> dict[str, list]` 方法（4 个 category：food_drink / shop / leisure / civic），按 category 内部 id 字母序
- [x] 1.3 在 `__init__.py` re-export（如需）；不破已有 API
- [x] 1.4 新增 `tests/test_atlas_typed_accessors.py`：3 个 scenario（list_workplaces 类型正确、list_pois 4 类完整、residential 与 workplaces/pois 不重叠）；pytest -v 全过

## 2. LocationPools 数据类 + 构造函数（agent spec）

- [x] 2.1 新建 `synthetic_socio_wind_tunnel/agent/location_pools.py`：定义 `LocationPools` frozen dataclass（home_pool / work_pool / poi_pool / target_location 四字段）+ `LocationPoolError` 异常类
- [x] 2.2 在同文件实现 `LocationPools.validate(atlas: Atlas)` 方法：校验三池 disjoint + target_location ∈ poi_pool（或 None）+ 三池所有 id 在同一连通分量内
- [x] 2.3 在同文件实现 `build_location_pools(atlas, *, home_count, work_count, poi_count, rng) -> LocationPools`：BFS 找连通分量 → 各类候选采样 → 三池 disjoint retry ≤ 5 次 → 返回 LocationPools 并 validate
- [x] 2.4 实现 `LocationPools.pick_target_location(rng, prefer="community")` 帮助函数：按 community → cafe → park → poi_pool[0] 顺序选 variant push target
- [x] 2.5 `synthetic_socio_wind_tunnel/__init__.py` re-export `LocationPools`、`build_location_pools`、`LocationPoolError`
- [x] 2.6 新增 `tests/test_location_pools.py`：8 个 scenario（合法构造、disjoint 校验、target 不在 poi_pool 校验、build 确定性、build 失败 fail-fast、reachability 校验、pick_target preference、retry ≤ 5）；pytest -v 全过

## 3. sample_population 升级（agent spec）

- [x] 3.1 在 `agent/profile.py::AgentProfile` 新增 `workplace: str | None = None` 字段；保持 Pydantic 默认值兼容
- [x] 3.2 在 `agent/population.py::sample_population` 新增 `pools: LocationPools | None = None` 参数（放在 home_locations 前）
- [x] 3.3 实现 pools 路径：每个 agent 按 work_mode 决定 workplace（commute/remote/shift → 抽 work_pool；retired/unemployed/homemaker/not_working → None）；home_location 从 home_pool 抽（容量加权放 §A2 household-coupling 时一起做，先用普通 rng.choice 给一户共享后再均分）
- [x] 3.4 当 pools is None and home_locations is not None：保留旧路径但 emit DeprecationWarning("home_locations parameter is deprecated; pass pools=LocationPools(...)")
- [x] 3.5 当两者都 None：raise（旧逻辑无变化）
- [x] 3.6 新增 `agent/profile.py::validate_against_atlas(profile, atlas)` 函数：校验 home_location 是 residential building；workplace（若非 None）在 work_pool 类型中；违反时 raise ValueError
- [x] 3.7 修改 `tests/test_agent_population.py`：保留旧 home_locations 路径测试（验 DeprecationWarning 发出）；新增 4 个 scenario：pools 路径 home_location 全为 residential、workplace 按 work_mode 分配、validate_against_atlas 拒绝 street home、确定性
- [x] 3.8 修改 `tests/test_life_pattern.py`、`tests/test_realism_emergence.py`：fixture 改用 pools；pytest -v 全过（旧 home_locations 路径仍 work；§8 全套验证时回看）

## 4. scripted_plan 升级（agent spec）

- [x] 4.1 在 `synthetic_socio_wind_tunnel/agent/scripted_plan.py::build_scripted_plan` 新增 `pools: LocationPools | None = None` 参数（保持 destinations: list[str] 向后兼容并 emit DeprecationWarning）
- [x] 4.2 内部 step 类型映射：pools 模式下 destinations = poi_pool；commute step 用 profile.workplace 替代 _pick_destination（_commute_day / _shift_day）；errand/leisure/outing 走 poi_pool
- [x] 4.3 `_commute_day` / `_shift_day` 处理 profile.workplace 非空场景；_remote_day 不需要 workplace（remote 居家）
- [x] 4.4 修改 `tests/test_scripted_plan.py`：新增 TestPoolsPath 4 scenarios：errand step destination 在 poi_pool 中；commute step.destination 是 home_location 或 workplace；pools-path 不 emit warning；旧 destinations 路径 emit warning
- [x] 4.5 package 内无其他调用者；runtime / planner 不直接调 build_scripted_plan（已检 `grep -rn build_scripted_plan synthetic_socio_wind_tunnel/`）

## 5. Suite CLI 切到 typed pools（suite-wiring spec）

- [x] 5.1 在 `tools/suite_stub_llm.py::StubReplanLLM.__init__` 加 `pools: LocationPools | None = None` 参数（旧 destinations 路径保留）
- [x] 5.2 StubReplanLLM 内部：pools 给出时，`_pick_distraction_location` / `_pick_community_location` 从 poi_pool 选 building 类目标；保持旧 outdoor 路径回退
- [x] 5.3 修改 `tests/test_suite_stub_llm.py`：新增 TestStubWithPools 4 scenarios（hp target 在 poi_pool、gd distraction 在 poi_pool 且非 street、pf community_heuristic 是 park/community、reproducibility）；pytest -v 全过（16/16）
- [x] 5.4 在 `tools/run_variant_suite.py` 替换 `destinations = _pick_connected_destinations(...)` 为 `pools = build_location_pools(atlas, home_count=max(40, n_agents//2), work_count=20, poi_count=30, rng=rng)`
- [x] 5.5 在同文件把 `home_locations=tuple(destinations)` 改为 `pools=pools` 传入 sample_population
- [x] 5.6 在同文件构造 `target_location = pools.pick_target_location(atlas, rng, prefer="community")`
- [x] 5.7 在同文件构造 `make_llm_client(..., pools=pools)` 透传到 StubReplanLLM
- [x] 5.8 在同文件给 `build_scripted_plan(p, pools=pools, ...)` 传入 pools
- [x] 5.9 旧 `tools/smoke_experiment_demo.py::_pick_connected_destinations` 保留但加 DeprecationWarning

## 6. 其他 wiring 切换（保 publishable run 接通）

- [x] 6.1 修改 `tools/run_multi_day_experiment.py` 用 build_location_pools
- [x] 6.2 修改 `tools/replan_trace.py` 用 build_location_pools + stub pools
- [x] 6.3 修改 `tools/measure_group_alignment.py` 用 build_location_pools
- [~] 6.4 `tools/run_stereotype_audit.py`：保留旧路径（emit DeprecationWarning），audit 工具不影响 publishable run；下一轮 sweep 时切换
- [~] 6.5 `tools/smoke_experiment_demo.py`：纯 demo 文件，保留旧路径（emit DeprecationWarning），下一轮 sweep 时切换或删除

## 7. dwell distribution acceptance（experimental-design spec 隐含的）

- [x] 7.1 新建 `tools/audit_dwell_distribution.py`：加载 suite seed → 计算 space_activation by category → 输出 residential_share / poi_share / work_share / street_share + ACCEPTANCE flag（residential ≥ 40%, street ≤ 20%）；exit code 0 通过 / 2 不通过
- [x] 7.2 新增 `tests/test_audit_dwell_distribution.py`：4 个 scenario（伪造高 residential dwell 通过、伪造高 street dwell 不通过、空 space_activation fail-fast、零总和 fail-fast）；pytest -v 全过

## 8. 验证 + smoke 跑

- [x] 8.1 运行 `python -m pytest tests/ -v` 全套测试通过（1294 + 6 → 1300）；新发现 trajectory_deviation_m bug（target 改为 building 后 atlas.get_outdoor_area 返 None）已修，6/6 e2e PASS
- [x] 8.2 跑 1 seed × 1 day × 20 agent × baseline smoke：`typed_smoke_unit` 完成 3.8s
- [x] 8.3 dwell audit ACCEPTANCE: PASS — residential 60.1% (≥40%) / street 0% (≤20%)
- [ ] 8.4 跑 1 seed × 14 day × 100 agent × DeepSeek（D1' 重跑）：~4hr DeepSeek wall time，**等用户确认启动**
- [ ] 8.5 D1' 重跑结果在 typed_locations 路径下 dwell residential ≥ 40% / street ≤ 20%；如不通过暂停并审查
- [ ] 8.6 把 D1' 重跑结果与旧 D1' 数据对比，输出对比报告 `docs/2026-05-12-d1pp-typed-locations-vs-old.md`

## 9. 文档更新

- [x] 9.1 更新 `docs/agent_system/20-realism-roadmap.md`：把 typed locations fix 列为 Stage 0.5（在 Stage 1 之前）
- [x] 9.2 更新 `CLAUDE.md`：新增"关键不变量（fix-population-uses-typed-locations 2026-05-12）"段
- [x] 9.3 更新 `docs/limitations-ethics.md`：增加"旧实验数据局限"段说明 home_location bug，对 thesis 因果链的影响
- [ ] 9.4 archive 该 change：等 §8.4-§8.6 D1' 重跑通过后再 archive
