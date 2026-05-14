## 1. A1 · ABS Lane Cove family_composition 校准

- [x] 1.1 `agent/population.py::LANE_COVE_PROFILE.family_composition_distribution` 用 ABS 2021 SAL12275 实际值替换占位符 (lone=19% / group=5% / under_15 22%)
- [x] 1.2 验证: sample 100 agent 时 couple_kids_under_15 from 49 → 23 (target ABS 22%)

## 2. A2 · --num-protagonists CLI flag

- [x] 2.1 `tools/run_variant_suite.py::parse_args` 加 `--num-protagonists` flag (默认 agents // 10)
- [x] 2.2 main loop 把值透传 `run_seed_with_metrics(num_protagonists=...)`

## 3. A3 · Polygon-size noticing 折扣

- [x] 3.1 `attention/noticing.py::noticing_prob` 加 `polygon_extent_m: float | None = None` 参数 + VISUAL_RANGE_M = 50.0 常量
- [x] 3.2 spatial_factor = min(1, VISUAL_RANGE_M / polygon_extent_m)
- [x] 3.3 `noticed_pair` 透传 polygon_extent_m
- [x] 3.4 `memory/service.py::_is_encounter_noticed` 接 shared_location_id 参数；查 polygon 算 extent；传给 noticed_pair
- [x] 3.5 caller 在 process_tick encounter loop 用 enc.shared_locations[0]

## 4. A4 · Tie 30-day half-life decay

- [x] 4.1 `social_graph/service.py` 加 `_TIE_DECAY_HALFLIFE_DAYS = 30.0` + `_TICKS_PER_DAY = 288` 常量
- [x] 4.2 `effective_strength(tie, now_tick) -> float` 实现 (raw strength × exp decay)
- [x] 4.3 `weak_ties_decayed(agent_id, now_tick)` / `strong_ties_decayed(...)` 助手
- [x] 4.4 raw `tie.strength` 不变 (backward compat)

## 5. A5 · Joint smoke 验证

- [x] 5.1 跑 `--seeds 1 --num-days 1 --agents 20 --variants baseline,phone_friction --use-aitown --aitown-provider stub` ✓ PASS (eff=2412 baseline / 2412 pf)
- [x] 5.2 walking_budget × ai-town path 不冲突

## 6. B/C disclose

- [x] 6.1 `docs/limitations-ethics.md` 加第九节 A/B/C 系统局限
- [x] 6.2 A 类 5 项 (RESOLVED 状态)
- [x] 6.3 B 类 8 项 (disclose only)
- [x] 6.4 C 类 5 项 (accept)
- [x] 6.5 "不应声称" 禁词清单

## 7. Regression

- [x] 7.1 `pytest tests/test_social_graph_integration.py tests/test_memory_*.py tests/test_attention_*.py tests/test_agent_population.py tests/test_orchestrator_*.py tests/test_variant_smoke_e2e.py tests/test_cartography_overture_categories.py -q` → 90 PASS

## 8. 后续

- [ ] 8.1 OpenSpec change 写 (本文档)
- [ ] 8.2 archive (与其它 5 个 change 一起按依赖顺序 archive)
