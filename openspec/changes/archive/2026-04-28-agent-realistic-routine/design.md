## Context

`docs/agent_system/20-realism-roadmap.md` 拆出 6 个 fidelity 维度。F1+F2+F3
是"baseline 真实感"地基——少一个 sim 就一眼假。三者改的都是
`scripted_plan.py`（990 个 Haiku 档 agent 的 plan 生成路径），合一次改。

## Goals / Non-Goals

**Goals**：
- F1：rush hour 双峰 / weekday vs weekend / Popular Times 加权
- F2：scripted_plan 读 8 个新维度做 plan conditioning
- F3：per-agent LifePattern 锚，14 天 sticky；routine_adherence 调强弱
- 加 verification CLI 衡量"拟真度"
- baseline 跑出来视觉立刻变化

**Non-Goals**：
- 不改 LLM 路径（Stage 2-3 才动）
- 不实现 group emergence（Stage 4-5）
- 不强依赖外部数据（graceful fallback 用 prior）

## Decisions

### D1：LifePattern 是 AgentProfile 的字段，不是独立表

**选择**：加 `life_pattern: LifePattern | None = None` 到 AgentProfile。

**Why**：
- LifePattern 是 agent 静态身份的延展（采样后不变）
- 跟 13 维 thesis 字段同 lifecycle（sample once, sticky）
- 序列化 / 持久化跟 profile 走，不需新表
- 反例（独立表）会引入 join + lifecycle 不匹配

### D2：LifePattern 字段简练（6 字段）

**选择**：preferred_cafe / preferred_leisure_park / preferred_errand_destination
/ morning_commute_minute / evening_return_minute / weekend_outing_destination

**Why**：
- 6 字段够支撑 14 天 routine 锚定
- 不堆字段——`preferred_school` / `preferred_pharmacy` 等可后续扩展
- 时间字段用整数 minute（0-59）—— offset 在 hour window 内；hour
  逻辑由 day-shape 控制
- 所有 destination 都是 `str | None`（location_id；None 表示该类型 POI 不
  适配该 agent，如 nonworking 不需要 evening_return 锚）

### D3：LifePattern 采样策略

**选择**：sample_population 时给每个 agent 生成；从 `destinations` 池里按
profile 倾向采样：

```python
def _sample_life_pattern(profile, destinations, atlas, rng):
    # 按 atlas 找 nearby cafes（home 附近 1km 内）
    nearby_cafes = _find_pois_near(atlas, profile.home_location, type="cafe", radius=1000)
    preferred_cafe = rng.choice(nearby_cafes) if nearby_cafes else None
    # 类似处理 park / errand / weekend
    morning_commute_minute = int(rng.gauss(30, 12)) % 60   # 高斯锁定 ~7:30am
    evening_return_minute = int(rng.gauss(30, 15)) % 60
    return LifePattern(...)
```

**Why nearby**：现实人偏好附近的 venue；不是全城随机
**Why 高斯偏移**：morning_commute_minute 不是均匀，而是有 mode（多数人 7:30
左右出门）

### D4：scripted_plan 怎么用 LifePattern

**选择**：在 4 个现有 day-shape 内部加 LifePattern 条件分支：

```python
def _commute_day(profile, destinations, rng, life_pattern, weekday):
    # commute time 用 LifePattern offset（不是均匀采样）
    morning_offset = (life_pattern.morning_commute_minute
                     if life_pattern and rng.random() < profile.personality.routine_adherence
                     else rng.randint(0, 59))
    depart_am = f"{8}:{morning_offset:02d}"
    
    # cafe destination：高 routine_adherence → preferred_cafe；否则探索
    if life_pattern and life_pattern.preferred_cafe and rng.random() < routine_adherence:
        leisure_dest = life_pattern.preferred_cafe
    else:
        leisure_dest = _pick_destination(rng, destinations, weighted_by_popular_times=True)
```

`routine_adherence` 概率门控——alignment 与 stickiness 之间平滑过渡。

### D5：weekday/weekend 分支

**选择**：在 `build_scripted_plan` 入口判断 `date.weekday() < 5`：

```python
def build_scripted_plan(profile, destinations, date, rng):
    weekday = date.weekday() < 5
    if weekday:
        # 现有 4-mode dispatch
        ...
    else:
        # 新 _weekend_day_shape：无 commute
        ...
```

**`_weekend_day_shape`**：
- morning_at_home 长（无 commute → 9-10am 才出门）
- 上午 errand（buy groceries / pharmacy）
- 下午 leisure（park / cafe / family outing）
- weekend_outing_destination 锚（高 routine_adherence agent 周末固定去哪）
- 晚 family time @ home

### D6：Popular Times 加权 destination 采样（graceful fallback）

**选择**：`_pick_destination` 加 `current_hour: int` 参数：

```python
def _pick_destination(rng, destinations, *, exclude=None, current_hour=None):
    pop_times = _load_popular_times_if_exists()
    if pop_times is None or current_hour is None:
        return rng.choice([d for d in destinations if d != exclude])
    # 按 pop_times[poi][weekday][current_hour] / 100 当 weight
    weights = [pop_times.get(poi, {}).get(...).get(current_hour, 50) for poi in destinations]
    return rng.choices(destinations, weights=weights, k=1)[0]
```

**Fallback**：JSON 不存在 → 跟当前一样均匀采样。整个 sim 不会因为没数据
crash，只是 alignment 度低。

### D7：morning_commute / evening_return 时间分布

**选择**：用高斯 prior（peaks at 7:30am / 17:30pm，std 30 min），不直接均匀
采样。LifePattern.morning_commute_minute 已经是个体的"我的"offset；day-shape
读它即可。

未来 ABS Travel Survey 数据到了，prior 替换为实测分布——不破任何接口。

### D8：tools/measure_group_alignment.py 输出格式

**选择**：JSON 含三段：

```jsonc
{
  "generated": "...",
  "suite_dir": "...",
  "f1_temporal": {
    "morning_peak_ratio": 1.62,        // 7-9am encs / 12-13pm encs
    "weekday_weekend_diff_pct": 0.18,   // |wd-we|/avg
    "popular_times_emd": null           // null when JSON not shipped
  },
  "f3_routine": {
    "high_adherence_repeat_pct": 0.72,
    "low_adherence_repeat_pct":  0.21,
    "spearman_adherence_repeat": 0.61
  },
  "stage1_passed": true              // 全部阈值通过
}
```

CLI 输出 + 写入 `data/realism/<suite_name>_metrics.json`，下个 stage ship 时
对比看进步。

### D9：测试阈值哪里来

参考 roadmap 给的"应当看到"数字 + 现实 prior：

- morning_peak_ratio > 1.5：现实 Sydney rush hour 大约这个数量级
- weekday/weekend diff > 0.15：澳大利亚劳动力人口 ~75% 工作日 commute
- high_adherence_repeat > 0.60：定义性的——routine 锚就该这么严
- 这些阈值是 Stage 1 acceptance；Stage 2-5 后还会涨

## Risks / Trade-offs

**[R1] LifePattern + 8 维 conditioning 让 scripted_plan 复杂度爆炸**
→ 严守"每维 1-2 行 conditioning"原则；不要 over-engineer state machine。
  保持原 4 day-shape 主干，新维度只是 hint

**[R2] 高斯时间锚抹掉了 stub seed reproducibility**
→ 用 `random.Random(seed + agent_index)` 给每个 agent 独立 sub-rng；
  seed-byte-equal 保留

**[R3] LifePattern.preferred_cafe 取决于 atlas 当前内容**
→ atlas 重 bake → LifePattern 失效（旧 location_id 不存在）；解：在
  load_population 时验证 + 重 sample 失效字段；warning 不抛错

**[R4] Popular Times 没抓时 alignment 度低**
→ Stage 1 不强制有数据；measure_group_alignment 输出 `popular_times_emd: null`
  + 显示"未抓"。每个 stage 之间用户可单独抓数据再重测

**[R5] 旧测试可能因为时间不再均匀挂掉**
→ 必跑 full pytest；预计 `test_scripted_plan.py` 几个时间断言要更新阈值

**[R6] dev mode 测试速度变慢**
→ scripted_plan 多读字段 ~ negligible；LifePattern 采样一次性。CI 应不超
  10% slower

## Migration Plan

阶段 1（schema, 0.5 day）：
1. profile.py 加 LifePattern model + AgentProfile.life_pattern field
2. population.py 加 _sample_life_pattern + sample_population 内调用

阶段 2（scripted_plan 重构, 2-3 day）：
3. 加 weekday/weekend 分支 + `_weekend_day_shape`
4. 8 个 profile dim conditioning
5. LifePattern preferred_* 接入（routine_adherence gated）
6. Popular Times 加权 + graceful fallback

阶段 3（verification CLI, 0.5 day）：
7. tools/measure_group_alignment.py
8. 跑 baseline 出 stage 0 数字（current 状态记录）

阶段 4（测试, 1-2 day）：
9. test_life_pattern.py
10. test_scripted_plan.py 扩展
11. test_realism_emergence.py
12. 修跟着挂的旧测试

阶段 5（验证 + 文档, 0.5 day）：
13. 跑 baseline 看 metrics 进步
14. 全 pytest
15. 更新 roadmap 标 Stage 1 ✓
16. archive sync

**回滚**：3 个文件 git revert + LifePattern 字段保留作 None（向后兼容；
AgentProfile.life_pattern 不传则 None）

## Open Questions

1. **Q1**：LifePattern 的 destination 字段（`preferred_cafe` 等）——在 atlas
   重 bake 后 location_id 失效如何处理？
   倾向：load 时验证 + 重 sample 失效字段；不抛错
2. **Q2**：weekday/weekend 之外要不要加 holiday？
   倾向：先不做（澳洲公共假期数据需外部源）
3. **Q3**：high routine_adherence 时 100% 用 LifePattern 会不会让 agent
   完全死板？
   倾向：用 0.8 上限（最多 80% 锁定，留 20% 探索）保留偶发偏离
4. **Q4**：scripted_plan 旧 4 day-shape 命名要不要重命名？
   倾向：保留 `_commute_day` etc.；只内部加 conditioning，不动签名
5. **Q5**：ABS Travel Survey prior 用什么具体形态？
   倾向：morning N(7:30, 30min) / evening N(17:30, 45min) / leisure
   uniform；ABS 数据到了再换
