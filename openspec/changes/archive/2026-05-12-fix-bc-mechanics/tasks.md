## 1. B1 · work_mode 反 COVID anomaly

- [x] 1.1 `agent/population.py::LANE_COVE_PROFILE.work_mode_distribution` 替换 ABS 2021 raw 值为 steady-state (commute 0.594 / remote 0.18 / shift 0.127 / nonworking 0.099)
- [x] 1.2 docstring 注明 de-anomaly 选择

## 2. B4 · 推送量等量 + radius 校正

- [x] 2.1 `policy_hack/variants/hyperlocal_push.py::daily_push_count` 默认改 5
- [x] 2.2 `policy_hack/variants/hyperlocal_push.py::hyperlocal_radius_m` 默认改 1000m
- [x] 2.3 `policy_hack/variants/global_distraction.py::daily_push_count` 默认改 5

## 3. B5 · Attention fatigue

- [x] 3.1 `attention/noticing.py::compute_notification_delta` 加 `notifications_received_today: int = 0` 参数 + FATIGUE_HALFLIFE_N = 8 常量
- [x] 3.2 delta × exp(-ln(2) × n / 8)
- [x] 3.3 `attention/service.py::AttentionService` 加 `_notifications_today: dict` field + __slots__
- [x] 3.4 `_accumulate_phone_attention` 读 + 递增 daily counter；传给 delta function
- [x] 3.5 `reset_daily_counters()` 方法

## 4. B6 · Transit drive-by 折扣

- [x] 4.1 `memory/service.py::_is_encounter_noticed` 加 `a_movement_count` + `b_movement_count` 参数
- [x] 4.2 transit_factor = 1/(1 + max/5); effective_attn += (1-factor) × 0.5
- [x] 4.3 caller in process_tick: 从 tick_result.movement_traces 构 moves_this_tick dict 传入

## 5. C2 · 儿童 movement restriction

- [x] 5.1 `agent/scripted_plan.py` 加 `_restrict_to_child_destinations(steps, profile, atlas, pools)` helper
- [x] 5.2 age < 6: 所有 step stay home
- [x] 5.3 age 6-12: commute/school 保留；其他 → home
- [x] 5.4 build_scripted_plan 在 sort 后调

## 6. 验证

- [x] 6.1 全套 regression 262 PASS (scripted_plan / orchestrator / agent / attention / memory / variant_smoke / social_graph_integration)

## 7. 文档 + archive

- [ ] 7.1 更新 `docs/limitations-ethics.md`: 标 B1/B4/B5/B6/C2 为 RESOLVED；B2/B3/C1/C3/C4/C5 仍 disclose
- [ ] 7.2 archive
