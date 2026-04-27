# Tasks — cartography-fix-water-geometry

修 OSM water 数据导入 bug：multipolygon relation 的 open outer way 被丢弃 →
Lane Cove River 等大水域不可见；并修 Map Explorer 渲染地下涵洞水线穿街问题。

**Chain-Position**: `infrastructure`
**前置**: `cartography-dedup-buildings`（已 implemented，未 archive；本 change
重 bake 时 dedup pass 自动跑）

## 1. multipolygon ring assembly

- [x] 1.1 在 `tools/fetch_lanecove.py` 加 helper：
  - `_assemble_outer_rings(outer_way_node_ids: list[list[int]]) -> list[list[int]]`
  - 输入：每条 outer way 的 node id 序列
  - 输出：闭合环列表（每环是 node id 序列，首末相同）
  - 算法：贪心端点匹配（design D1）
  - 不闭合的 chain → drop + logger.warning

- [x] 1.2 在 `_assemble_outer_rings` 上加 unit test 覆盖：
  - 4 条 way 构成矩形 → 1 环
  - 已闭合的单 way → 1 环
  - 缺一段的 chain → 0 环 + warning
  - 多个独立闭合环（如 2 个分隔水域）→ 2 环

- [x] 1.3 重构 fetch_lanecove.py 第 ~248 行 relation 处理：
  - 保留现有"收集 outer ways"逻辑
  - 调 `_assemble_outer_rings` 拿到环列表
  - 每个环输出一个 Polygon feature；properties 沿用 relation tags
  - 不再要求"每条 outer way 自闭合"

## 2. fetch + 重生成 atlas

- [x] 2.1 跑 `python3 tools/fetch_lanecove.py` 重新拉 OSM 数据
- [x] 2.2 跑 `python3 tools/enrich_map.py` 重 enrich（buildings 复用 cache，水
  部分自动级联）
- [x] 2.3 删 `data/lanecove_atlas.json` + 让 lanecove.py 重新生成 atlas（自动
  跑 dedup pass）
- [x] 2.4 验证日志：fetch 输出含 "Lane Cove River" 多边形；atlas bake 含
  area_type="water" 的 outdoor_areas（包含大河）

## 3. Map Explorer 过滤地下水道

- [x] 3.1 改 `tools/map_explorer/server.py`：在加载 water LineString 时过滤
  `tunnel ∈ {yes, culvert, building_passage}` / `layer<0` / `covered=yes`
- [x] 3.2 print 加载日志含 "filtered N underground waterways"
- [x] 3.3 加 `_RENDER_BBOX` 常量 + `_clip_polygon_to_bbox`（Sutherland-Hodgman
  rect clip）；水多边形加载时裁到 bbox，完全在外的丢弃

## 4. 测试

- [x] 4.1 新建 `tests/test_fetch_lanecove.py`（如不存在）：
  - `test_assemble_simple_rectangle`: 4 条 way 装成 1 环
  - `test_assemble_already_closed_way`: 单已闭合 way → 1 环
  - `test_assemble_broken_chain`: 缺一段 → drop + warning
  - `test_assemble_multiple_independent_rings`: 多环
- [x] 4.2 加 atlas water 集成测试到 `tests/test_atlas_quality.py`：
  - load cache，断言至少 1 个 area_type="water" 的 outdoor_area area > 50000 m²
  - 若 cache 不存在则 skip

## 5. 验证

- [x] 5.1 全 pytest 通过（548+ tests）
- [x] 5.2 `openspec validate cartography-fix-water-geometry --strict` 通过
- [x] 5.3 手工开 Map Explorer (`python3 tools/map_explorer/server.py`) 肉眼
  验证：
  - Lane Cove River 大水道在地图上可见（社区南/西边的大蓝色区域）
  - Stringybark Creek 等小溪不再穿街（地下涵洞段被过滤）

## 6. 文档

- [x] 6.1 更新 `docs/agent_system/19-system-snapshot.md` 历史决策点表加本 change
- [x] 6.2 更新 `docs/map_pipeline/04-reading-the-atlas.md` 提一下 water 处理
  policy（multipolygon outer-only；无 inner hole）
