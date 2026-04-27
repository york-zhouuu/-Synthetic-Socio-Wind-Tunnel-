## ADDED Requirements

### Requirement: AgentProfile 含 LifePattern 字段

`AgentProfile` SHALL 含 `life_pattern: LifePattern | None = None` 字段。
`LifePattern` 是 Pydantic model，包含 6 个字段记录 agent 14 天 sticky 的
"我的"routine 锚：

- `preferred_cafe: str | None`
- `preferred_leisure_park: str | None`
- `preferred_errand_destination: str | None`
- `morning_commute_minute: int`（0-59，hour window 内偏移）
- `evening_return_minute: int`（0-59）
- `weekend_outing_destination: str | None`

`sample_population` SHALL 给每个 agent 采样一份 LifePattern；同 seed 同输出
（reproducibility 不破）。LifePattern 采样 SHALL 优先选 home 附近的 POI（不
全城随机）。

#### Scenario: 同 seed 同 LifePattern
- **WHEN** 两次调用 `sample_population(LANE_COVE_PROFILE, seed=42)`
- **THEN** 每个 agent 的 `life_pattern.preferred_cafe` /
  `morning_commute_minute` 等字段 SHALL 完全相同

#### Scenario: 旧构造签名仍兼容
- **WHEN** 既有 `AgentProfile(agent_id=..., name=..., age=..., ...)` 调用
- **THEN** SHALL 不抛；`life_pattern` 默认 None；公共 API 兼容


### Requirement: scripted_plan 区分 weekday vs weekend

`build_scripted_plan(profile, destinations, date, rng)` SHALL 按
`date.weekday() < 5` 区分两套 day-shape：

- **Weekday**：现有 4 模式（commute/remote/shift/nonworking）保留 + 强化
- **Weekend**：新 `_weekend_day_shape` —— 无 commute；morning_at_home 长；
  上午 errand；下午 leisure；晚 family time；锚 weekend_outing_destination

#### Scenario: Saturday 不含 commute step
- **WHEN** `build_scripted_plan(profile, ..., date=2026-05-02, ...)`
  （周六），profile.work_mode == "commute"
- **THEN** 返回的 DailyPlan SHALL 不含 reason="commute" 的 step；
  SHALL 含 ≥ 1 个 leisure step

#### Scenario: weekday/weekend 总活跃差
- **WHEN** 跑 100 agent × 7 day baseline（混合 work_mode），weekday 5 天
  + weekend 2 天
- **THEN** weekday 平均每天 encounter ≥ weekend 平均每天 × 1.15


### Requirement: scripted_plan 读 8 个 profile 维度做 conditioning

`build_scripted_plan` SHALL 在 day-shape 生成时 condition 在以下 profile
字段（"每维 1-2 行 conditioning"原则；不重写主干）：

| 字段 | 影响 |
|---|---|
| `family_composition == "couple_kids_under_15"` | 必含 3pm school pickup step + 18:30 home anchor |
| `unpaid_child_care_hours ∈ {"15_29", "30plus"}` | errand 时段集中 9-15pm |
| `vehicles_at_dwelling == "0"` | commute step 加 transit via-point（lightweight） |
| `community_tenure_5yr == "new_<1yr"` | leisure venue 多样性 ↑（不锁 LifePattern） |
| `community_tenure_5yr == "established_5plus"` | LifePattern 锚强 |
| `english_proficiency ∈ {"not_well", "not_at_all"}` | leisure POI 偏好 own-language community POI（mild bias） |
| `personality.routine_adherence > 0.7` | LifePattern 用率 ≥ 80% |
| `personality.openness > 0.7` | leisure venue 多样化（不死锁单一 venue） |

#### Scenario: couple_kids_under_15 含 school pickup
- **WHEN** profile.family_composition == "couple_kids_under_15" 且 day 是
  weekday，build_scripted_plan 跑
- **THEN** DailyPlan SHALL 含一个 time ∈ ["14:30", "15:30"] 的 step；
  reason 或 activity 含 "school" / "pickup" / "kids"

#### Scenario: 0-car 通勤不含 driving
- **WHEN** profile.vehicles_at_dwelling == "0" 且 work_mode == "commute"
- **THEN** commute step SHALL 通过一个 transit via-point 或显示 "transit"
  reason；MUST NOT 直接 home → workplace（无 via）


### Requirement: LifePattern 通过 routine_adherence gated 锁定

scripted_plan 用 LifePattern.preferred_* 字段时 SHALL 由
`profile.personality.routine_adherence` 概率门控：

- routine_adherence > 0.7 → 80% 概率用 preferred_*
- routine_adherence 0.4-0.7 → 50% 概率
- routine_adherence < 0.4 → 20% 概率

agent 14 天保持 LifePattern 的"sticky"通过这门控随机性涌现：高坚持者大
多数天用同一 cafe；低坚持者每天换。

#### Scenario: 高 routine_adherence 14 天 cafe 重复
- **WHEN** 跑 100 agent × 14 day baseline，筛 routine_adherence > 0.7 的
  agents
- **THEN** ≥ 50% 的高坚持 agent 14 天里访问 LifePattern.preferred_cafe
  的次数 ≥ 8 天

#### Scenario: 低 routine_adherence 探索多
- **WHEN** 同样筛 routine_adherence < 0.4 的 agents
- **THEN** 14 天 unique leisure venue 数中位数 ≥ 4 个


### Requirement: Popular Times 加权采样（graceful fallback）

`scripted_plan._pick_destination` SHALL 接受 `current_hour: int | None`
参数。当 `data/calibration/lanecove_popular_times.json` 存在且 current_hour
非 None 时，destination 采样权重 SHALL 用 Popular Times 的当前小时热度。

JSON 不存在 / current_hour 为 None / POI 在 popular_times 里没记录 → fallback
均匀采样（不抛错）。

#### Scenario: 没数据时 fallback 均匀
- **WHEN** Popular Times JSON 不存在 / 不含某 POI
- **THEN** _pick_destination SHALL 均匀采样剩余 POI，跟当前行为完全一致

#### Scenario: 有数据时按热度加权
- **WHEN** lanecove_popular_times.json 已 ship，cafe_main 的周一 8am 热度
  90、cafe_secondary 周一 8am 热度 30
- **THEN** 在 current_hour=8 的多次 _pick_destination 调用中，cafe_main
  采样比例 SHOULD 显著高于 cafe_secondary（卡方 p < 0.05）


### Requirement: Realism CLI 输出量化指标

`tools/measure_group_alignment.py` SHALL 是衡量"agent 拟真度"的离线 CLI。
输入：suite directory（已跑过的 sim 输出）。输出：
`data/realism/<suite>_metrics.json` 含 F1 时空 + F3 routine 三组数字。

JSON 结构：
```jsonc
{
  "f1_temporal": {
    "morning_peak_ratio": float,
    "weekday_weekend_diff_pct": float,
    "popular_times_emd": float | null
  },
  "f3_routine": {
    "high_adherence_repeat_pct": float,
    "low_adherence_repeat_pct": float,
    "spearman_adherence_repeat": float
  },
  "stage1_passed": bool
}
```

`stage1_passed` 当全部以下成立时为 true：
- morning_peak_ratio > 1.5
- weekday_weekend_diff_pct > 0.15
- spearman_adherence_repeat > 0.5

#### Scenario: stage1 passed
- **WHEN** sim 数据满足三阈值
- **THEN** measure_group_alignment.py SHALL 输出 stage1_passed = true

#### Scenario: 没 Popular Times 数据
- **WHEN** lanecove_popular_times.json 不存在
- **THEN** popular_times_emd SHALL == null；stage1_passed 评估时不依赖
  此字段
