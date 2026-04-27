## Why

打开 Map Explorer 看 Lane Cove 时发现两个水面渲染问题：

1. **大水域完全缺失**——Lane Cove River 主水道（社区南/西边的大水道）在地图上
   不存在，理论上应是大片蓝色区域。Sydney Harbour、Parramatta River、Tarban
   Creek 全部一样消失。仅 13 个小水池（Lane Cove Lake、Dawn Fraser Baths、
   The Concourse 反射池等）能正确渲染。
2. **小溪（stream LineString）穿街**——`Tambourine Creek`、`Stringybark Creek`
   等支流以 LineString 形式画在地图上，**穿过街道**（实际地下涵洞 / 桥下不
   应可见的部分被画成连续水线）。

**根因 1（多边形组装 bug）**：OSM 的大水域以 **multipolygon relations** 形式
存储，每个 relation 含多条**未自闭合**的 outer way（按端点拼接成环）。
`tools/fetch_lanecove.py` 第 ~270 行处理 relation 时**要求每个 outer way 自身
已闭合**（`if not way_is_closed(coords): continue`），否则跳过。Lane Cove
River relation 含 74 条 outer way，**全部不自闭合** → 全部被丢弃 → river
polygon 完全消失。

**根因 2（隧道 / 涵洞标签未过滤）**：OSM 用 `tunnel=yes` / `layer<0` 标记地
下水道；当前 Map Explorer `server.py` 渲染水线时不区分地上 / 地下，所有
LineString 都画。

**Chain-Position**: `infrastructure`（atlas 数据 + 渲染层；不动 thesis、agent
契约、sim 行为）。

## What Changes

### 1. `fetch_lanecove.py` 实现 multipolygon ring assembly

新增 `_assemble_multipolygon(rel, way_index, node_index) -> list[Polygon]`：
- 收集 relation 的所有 outer way 端点
- 用 OSM 标准 ring 拼接算法（按起点 / 终点匹配，逐段链接）
- 每个闭合环输出一个 Polygon
- inner way（孔洞，如河中岛屿）作为 polygon hole 处理

替换当前"必须自闭合才输出"的简单分支。

### 2. 重新 fetch + 重生成 enriched

- 跑 `tools/fetch_lanecove.py` 重新拉 OSM water relations
- 跑 `tools/enrich_map.py` 重新融合（Overture buildings 不重 fetch，复用 cache）
- 删 `data/lanecove_atlas.json` cache 让 cartography 重 bake

### 3. Map Explorer 过滤地下水道

`tools/map_explorer/server.py` 渲染水 LineString 时跳过：
- `tunnel=yes`
- `layer` 标签 < 0
- `covered=yes`

### 4. 测试

- 单元测试 multipolygon 组装：手造 4 段构成矩形的 outer ways → 装出 1 个闭合
  多边形
- 验收测试：fetch 后断言 Lane Cove River 至少含 1 个 area > 50000 m² 的 water
  polygon

## Non-goals

- **不**改 Atlas / Building / OutdoorArea 公共 API
- **不**重 fetch buildings（只重 water 部分）
- **不**调整 stream LineString 的视觉样式（颜色 / 粗细 —— 那是渲染美术决策）
- **不**实现 OSM 通用 multipolygon 全功能解析（仅覆盖本 atlas 用到的水域；
  非 water 类型的 multipolygon 不在范围）
- **不**给 Atlas 加新的几何类型（Polygon with holes 仍存为单 polygon，inner
  ring 暂时丢弃；河中小岛影响可接受）

## Capabilities

### Modified Capabilities

- `cartography`: 新增 multipolygon outer-ring 拼接 requirement + 水道隧道
  过滤 requirement。

### New Capabilities

（无）

## Impact

- **修改文件**：
  - `tools/fetch_lanecove.py`（multipolygon assembly）
  - `tools/map_explorer/server.py`（tunnel filtering）
  - `tests/test_fetch_lanecove.py`（如不存在则新建；测 ring assembly）
- **重生成数据**：
  - `data/lanecove_osm.geojson`（至少 water 部分）
  - `data/lanecove_enriched.geojson`（级联）
  - `data/lanecove_atlas.json`（cache 重 bake；触发 dedup pass）
- **不改**：cartography importer / dedup / lanecove.py（这些消费 GeoJSON，对水
  数据是透传的）
- **下游影响**：Map Explorer 现在能看到 Lane Cove River 真实形状；下游可视化
  （作品集网站等）从新 atlas 重 export 后水也对齐
- **前置依赖**：`cartography-dedup-buildings`（已 implemented，未 archive；
  本 change 重 bake atlas 时 dedup pass 自动跑）
- **性能**：fetch_lanecove 多一次 Overpass 调用 + ring assembly < 1 s；
  Map Explorer 加载多读几个标签字段 < 100 ms
