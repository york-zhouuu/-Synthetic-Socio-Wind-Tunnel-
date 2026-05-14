## 1. Atlas: OutdoorArea / Building capacity 字段

- [x] 1.1 加 `capacity: int | None = None` 到 OutdoorArea + Building
- [ ] 1.2 cartography/lanecove.py 注 default by area_type（仍待做 — 当前 default = None for all loaded; need to load DEFAULT_CAPACITY_BY_AREA_TYPE map）
- [x] 1.3 单测 capacity 默认值通过

## 2. POIHeatModel service

- [x] 2.1 新建 `atlas/heat.py::POIHeatModel`
- [x] 2.2 实现 register_arrival / register_departure / current_occupancy / is_full + DEFAULT_CAPACITY_BY_AREA_TYPE map
- [x] 2.3 单测覆盖（11 tests）

## 3. simulation::move_entity overflow 行为（仍待做）

- [ ] 3.1 capacity 检查 + 三分支概率（30% defer / 30% redirect / 40% abandon）
- [ ] 3.2 接 POIHeatModel
- [ ] 3.3 contract tests for defer / redirect / abandon

> **Why deferred (2026-05-10)**：move_entity 是 sim hot path，加 capacity
> 检查 + 重路由 + abandon 行为是 ~5 天工作（含 contract tests + 与
> A1 perception_gated_destination_swap 的交互验证）。autonomous session
> 不安全做这种侵入式改动。

## 4. orchestrator 注入 POIHeatModel（仍待做，依赖 §3）

- [ ] 4.1 单测 orchestrator 跑通后 occupancy 与 ledger 一致

## 5. metrics extension（仍待做，依赖 §3）

- [ ] 5.1 加 poi_overflow_count 字段
- [ ] 5.2 跟踪 defer / redirect / abandon 各计数

## 6. hp variant 选 target 时考虑 heat（可选；依赖 §3 + §4）

- [ ] 6.1 加 flag `avoid_full_destinations: bool = True`
- [ ] 6.2 single test scenario

## 7. smoke + archive（待 §3-§5 完成）

- [ ] 7.1 1 seed × 1 day × 100 agent × 4 variant smoke
- [ ] 7.2 全量 regression
- [ ] 7.3 sync atlas + simulation specs
- [ ] 7.4 archive

## ▶ Minimum-viable shipped 2026-05-10

§1（部分）+ §2 已 ship 进 main：
- OutdoorArea / Building 加 capacity 字段（默认 None = unbounded）
- atlas/heat.py::POIHeatModel + DEFAULT_CAPACITY_BY_AREA_TYPE map
- 11 tests 覆盖 register_arrival / departure / is_full / defaults
- 1238 → 1257 passed

§3-§7（move_entity 集成 + metrics + smoke）需要再开一次专门 session 完成。
