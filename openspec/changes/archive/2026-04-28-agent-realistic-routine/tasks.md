# Tasks — agent-realistic-routine

Realism roadmap Stage 1：F1+F2+F3 合一。让 baseline sim 看起来像真 Lane Cove。

**预计周期**: 5-7 day

## 1. Schema：LifePattern + AgentProfile field

- [x] 1.1 加 `LifePattern` Pydantic model 到
  `synthetic_socio_wind_tunnel/agent/profile.py`
  - 6 字段：preferred_cafe / preferred_leisure_park /
    preferred_errand_destination / morning_commute_minute /
    evening_return_minute / weekend_outing_destination
- [x] 1.2 加 `life_pattern: LifePattern | None = None` 到 AgentProfile
- [x] 1.3 export LifePattern 到 `synthetic_socio_wind_tunnel/agent/__init__.py`

## 2. LifePattern 采样

- [x] 2.1 加 `_sample_life_pattern(profile, destinations, atlas, rng)` 到
  `synthetic_socio_wind_tunnel/agent/population.py`
  - 优先选 home_location 1km 内的 cafe / park / shop 等 POI
  - morning_commute_minute / evening_return_minute 用高斯（mean 30, std 12）
- [x] 2.2 `sample_population` 内调用，给每 agent 写 LifePattern
- [x] 2.3 注意：destinations / atlas 缺时优雅 fallback（None 字段）

## 3. scripted_plan 重构

### 3.1 weekday/weekend 分支
- [x] 3.1.1 `build_scripted_plan` 加 `weekday = date.weekday() < 5`
- [x] 3.1.2 加 `_weekend_day_shape` 函数（无 commute；errand + leisure +
  family time）
- [x] 3.1.3 weekend 锚 `life_pattern.weekend_outing_destination`

### 3.2 8 个新维度 conditioning
- [x] 3.2.1 `family_composition == couple_kids_under_15` → 加 3pm school
  pickup step（if weekday）
- [x] 3.2.2 `unpaid_child_care_hours ∈ {15_29, 30plus}` → errand 时段集中
  9-15pm
- [x] 3.2.3 `vehicles_at_dwelling == "0"` → commute step 含 transit
  via-point（找 atlas 的 station 类型 POI）
- [x] 3.2.4 `community_tenure_5yr == new_<1yr` → leisure venue 多样性
  ≥ 70% LifePattern bypass
- [x] 3.2.5 `community_tenure_5yr == established_5plus` → LifePattern 用率
  upper bound 80%
- [x] 3.2.6 `english_proficiency ∈ {not_well, not_at_all}` → leisure POI
  bias（这个先简化为 +1 toward leisure_park 不动 cafe；ABS 数据更全后再细）
- [x] 3.2.7 `personality.openness > 0.7` → leisure venue 多样化

### 3.3 LifePattern routine_adherence gating
- [x] 3.3.1 加 `_use_lifepattern(rng, routine_adherence) -> bool` helper
  - > 0.7 → 80% 用
  - 0.4-0.7 → 50% 用
  - < 0.4 → 20% 用
- [x] 3.3.2 4 个 day-shape 内部，凡选 cafe / leisure / errand 的地方都
  call `_use_lifepattern` gated 看用 LifePattern preferred_* 还是 fresh sample

### 3.4 时间分布 (morning_commute, evening_return) 高斯
- [x] 3.4.1 commute time 用 `life_pattern.morning_commute_minute` 当 offset
- [x] 3.4.2 evening_return 同上

### 3.5 Popular Times 加权采样
- [x] 3.5.1 加 `_load_popular_times_if_exists() -> dict | None` helper
  - 读 `data/calibration/lanecove_popular_times.json`；不存在返 None
- [x] 3.5.2 改 `_pick_destination` 签名加 `current_hour: int | None`
  参数；当数据 + hour 都有时按热度加权；否则均匀
- [x] 3.5.3 4 day-shape 调用时传 `current_hour` from step 时间

## 4. Realism CLI

- [x] 4.1 新建 `tools/measure_group_alignment.py`：
  - argparse `--suite-dir`（必填）
  - 读 suite 的 trajectory data
  - 计算 F1 temporal 三个数（peak ratio, weekday/weekend diff, popular times EMD）
  - 计算 F3 routine 三个数（high/low adherence repeat pct, Spearman corr）
  - 输出 `data/realism/<suite>_metrics.json` + print summary
  - `stage1_passed` 三阈值判定

## 5. 测试

### 5.1 LifePattern + 采样
- [x] 5.1.1 新建 `tests/test_life_pattern.py`：
  - test_life_pattern_reproducibility (same seed → same LifePattern)
  - test_life_pattern_uses_nearby_pois (preferred_cafe 在 home 附近)
  - test_morning_commute_gaussian_centered (mean 在 30 左右)

### 5.2 scripted_plan 维度 conditioning
- [x] 5.2.1 扩展 `tests/test_scripted_plan.py`：
  - test_couple_kids_under_15_includes_school_pickup
  - test_zero_car_commute_via_transit
  - test_high_routine_adherence_uses_lifepattern_majority
  - test_low_routine_adherence_explores
  - test_weekend_no_commute_step
  - test_weekend_includes_outing

### 5.3 群体涌现验证
- [x] 5.3.1 新建 `tests/test_realism_emergence.py`：
  - test_morning_peak_ratio_above_threshold (跑 100 agent × 7 day → ratio > 1.5)
  - test_weekday_weekend_total_differ
  - test_high_adherence_agents_repeat_cafe (>50% 高坚持者 cafe 重复 >= 8 天)

### 5.4 修跟着挂的旧测试
- [x] 5.4.1 跑 full pytest，预计部分 test_scripted_plan 阈值要更新

## 6. 验证

- [x] 6.1 跑 stage 0 baseline measurement（动 scripted_plan 之前先记录）
  - `python3 tools/measure_group_alignment.py --suite-dir <prev_suite>`
  - 记 baseline 数字到 `data/realism/stage0_baseline.json`
- [x] 6.2 ship 完后跑 stage 1 measurement → 数字应改善
- [x] 6.3 全 pytest 通过（674+ 加 ~20 新 test）
- [x] 6.4 跑 6-variant smoke 端到端（确认不破 sim）
- [x] 6.5 `openspec validate agent-realistic-routine --strict` 通过

## 7. 文档

- [x] 7.1 更新 `docs/agent_system/19-system-snapshot.md` 历史决策点表
- [x] 7.2 更新 `docs/agent_system/20-realism-roadmap.md` 标 Stage 1 ✓ +
  实测数字

## 8. archive sync

- [x] 8.1 archive 时合 delta spec 入 `openspec/specs/agent/spec.md`
- [x] 8.2 commit
