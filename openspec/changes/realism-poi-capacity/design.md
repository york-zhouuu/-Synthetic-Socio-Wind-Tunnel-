## Context

当前 cafe 装无限人是 thesis 实验装置最大的 ecological validity 缺口。

约束：
- 不重抓 OSM 数据加 capacity 字段
- capacity 默认按 area_type 推（cafe ~ 15，shop ~ 10，park / street ∞）
- POIHeatModel 是 sim-level service，每 tick 增减
- 不破坏 1238 测试基线

## Goals / Non-Goals

**Goals**:

1. OutdoorArea / Building 有 capacity 字段
2. move_entity 抵达时检查 capacity；满员触发 overflow 三分支
3. POIHeatModel 跟踪 occupancy；hp variant 可选规避已满 location
4. metrics.extensions.poi_overflow_count 跟踪行为

**Non-Goals**:

- 不动 OSM data
- 不实现复杂排队（先用简单概率）
- 不动 perception（capacity 不直接影响 SubjectiveView ——但 occupancy 已经
  被 visible_entities 间接反映）

## Decisions

### Decision 1: capacity 默认 by area_type

```python
DEFAULT_CAPACITY_BY_TYPE = {
    "cafe": 15, "restaurant": 20, "shop": 10,
    "park": None, "street": None, "square": None,
    "school": None,  # schools have capacity but in our sim are home_loc anchors
    ...
}
```

### Decision 2: overflow 三分支概率（30/30/40）

可调；smoke 后看是否合理。

### Decision 3: POIHeatModel 是独立 service

不塞进 Ledger（避免 Ledger 膨胀）。orchestrator 注入。

## Risks / Trade-offs

- [Risk] 已有的 perception_gated_destination_swap (A1) 现在还做"看到 cafe 排
  队 > 5 → 换" —— 和 A3 的 capacity overflow 行为重叠。Mitigation：A1 是
  perception 端 swap（agent 主动），A3 是 simulation 端 forced overflow（被动）；
  二者并存合理。
- [Risk] hp 推 100 个 agent 现在大量 overflow，hp 信号被稀释 → 这是 thesis
  carrying capacity 想要研究的 — 不算缺陷而是发现。

## Migration Plan

1. atlas 加 capacity 字段（默认 None）
2. POIHeatModel + capacity 注 default
3. move_entity overflow 行为
4. metrics extension
5. smoke + tests
6. archive

## Open Questions

1. cafe 默认 15 是否合理？—— 凭经验值，smoke 后看
2. hp variant 是否应该 skip 已满 location？—— 默认是；可关掉做 baseline 对照
