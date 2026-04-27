# Reading the Atlas — quick guide for downstream agents

面向"想读这个项目导出的地图数据，但不打算重跑 cartography pipeline"的下游
agent / 工具（作品集网站、可视化、审计脚本等）。

---

## 1. 数据在哪

| 文件 | 内容 | 大小 |
|---|---|---|
| `data/lanecove_atlas.json` | 完整 Lane Cove atlas（cache，cartography 产出）| ~80 MB |
| `data/lanecove_proj_center.json` | 投影中心 lat/lon（反投影时要用）| <1 KB |
| `data/lanecove_enriched.geojson` | 多源融合后的原始 GeoJSON | ~50 MB |
| `data/lanecove_osm.geojson` | 纯 OSM 原始数据 | ~10 MB |

**首选**：直接读 `lanecove_atlas.json`。其它两份是构建中间产物。

---

## 2. 三种读法（按"侵入度"从低到高）

### A. 纯 JSON（外部项目最方便，不需要 install 本项目）

```python
import json
data = json.loads(open("data/lanecove_atlas.json").read())
# data["buildings"]: dict[id → Building dict]
# data["outdoor_areas"]: dict[id → OutdoorArea dict]
# data["connections"]: list[Connection dict]
# data["bounds_min"]/["bounds_max"]: {"x": float, "y": float}
```

```js
// JavaScript / Node：
const data = require("./data/lanecove_atlas.json");
const buildings = Object.values(data.buildings);
```

### B. 通过 Atlas service（项目内推荐）

```python
from synthetic_socio_wind_tunnel.cartography.lanecove import create_atlas_from_osm
atlas = create_atlas_from_osm()  # 自动用 cache，~1 秒
b = atlas.get_building("building_4036")        # → Building
nearby = atlas.list_buildings_in_region(...)   # 各种查询方法
```

### C. 通过 Map Explorer Flask server（浏览器/HTTP 客户端）

```bash
python3 tools/map_explorer/server.py
# → http://localhost:5000/api/map  返回完整地图 GeoJSON-like
```

---

## 3. 关键 schema（精简版）

### Building

```jsonc
{
  "id": "building_4036",
  "name": "Sydney Speech Clinic",
  "polygon": {
    "vertices": [{"x": 93.0, "y": -44.4}, ...]    // 投影 meters，闭合多边形
  },
  "building_type": "residential",                  // residential|commercial|...
  "osm_tags": {"building": "yes", "addr:street": ...},
  "description": "...",
  "floors": 1,                                     // ★ 楼层数，1-14
  "exterior_material": "BRICK",
  "entrance_coord": {"x": 95.0, "y": -50.0} | null,
  "rooms": {},                                     // 默认空，按需 collapse
  "active_hours": [7, 22] | null,
  "typical_sounds": [...],
  "typical_smells": [...],
  "affordances": [...],
  "entry_signals": {...}
}
```

**没有 `height` 字段**（OSM 该地区没有 height tag）。**用 `floors` 当高度代理**：

```python
height_meters = building["floors"] * 3.0  # 3m/层 是住宅常用近似
# 或：商业/工业建筑用 4-5m/层
```

Lane Cove 的 floors 分布（dedup 后约 6176 栋）：
- 1 层：~5100 栋（独立屋 + Riverview 合成屋为主）
- 2 层：~870 栋
- 3-5 层：~170 栋（小公寓 / 商铺）
- 6-14 层：~30 栋（CBD 高层，集中在 Longueville Rd 商业带）

> 2026-04-26 `cartography-dedup-buildings` change：合并掉 OSM × OSM 近重复
> 楼（IoU > 0.5），并修了 Riverview 合成屋撞 OSM 真楼的碰撞检测。建筑数从
> 7552 → ~6176。被合并的来源 ID 记录在 `osm_tags["merged_from_ids"]`。

### Water (visual context, not in atlas outdoor_areas)

水多边形（Lane Cove River、Sydney Harbour 等大水域 + 池塘）以 Polygon /
LineString 形式存在 `lanecove_osm.geojson`，**不进入 atlas.outdoor_areas**——
水不是 agent 可步行的位置，只是渲染层视觉 context。

OSM multipolygon relation 的 outer way 在 fetch 时通过端点拼接装成闭合环
（`tools/fetch_lanecove.py::_assemble_outer_rings`，2026-04-26
cartography-fix-water-geometry change）。Map Explorer 加载时过滤地下涵洞
（`tunnel=yes` / `layer<0` / `covered=yes`）避免水线穿街视觉。

下游可视化要画水：直接读 `lanecove_osm.geojson`，按 `properties.natural==water`
或 `properties.waterway` 过滤。

### OutdoorArea

```jsonc
{
  "id": "park_xxx" | "road_xxx_seg_N",
  "name": "...",
  "polygon": { "vertices": [...] },
  "area_type": "park" | "road" | "plaza" | "square" | "water" | ...,
  "surface": "grass" | "asphalt" | ...,
  "vegetation_density": 0.0 - 1.0,
  "road_name": "Longueville Road" | null,        // 仅 road
  "segment_index": 3 | null,                      // 同一路被切成段
  ...
}
```

道路被切成短段（`road_xxx_seg_N`），每段是一个 OutdoorArea —— 这是为
agent navigation 服务的设计。

### Connection（建筑/区域之间的可步行连接）

```jsonc
{ "from_id": "...", "to_id": "...", "distance_m": 12.4 }
```

---

## 4. 坐标系（重要）

- 投影：**equirectangular（等距矩形），原点在 atlas 中心**
- 单位：**米**（不是经纬度，不是像素）
- Y 轴：**向下为正**（SVG 风格；北 = y 减小）
- 中心 lat/lon：见 `data/lanecove_proj_center.json`，目前是 `(-33.81441, 151.16270)`

反投影回经纬度：

```python
import math, json
center = json.load(open("data/lanecove_proj_center.json"))
clat, clon = center["center_lat"], center["center_lon"]
m_per_deg_lat = 111320.0
m_per_deg_lon = 111320.0 * math.cos(math.radians(clat))

def unproject(x, y):
    lat = clat - y / m_per_deg_lat   # y 向下为正 → 减
    lon = clon + x / m_per_deg_lon
    return lat, lon
```

---

## 5. ⚠️ 两个常见踩坑

### 5.1 `bounds_min/max` 是"完整 atlas"的，不是你手头数据的

`bounds_min/max` 是按 **buildings + outdoor_areas（含水域、大块绿地、
道路边缘）** 的 union 算出来的，比只看 buildings 大很多：

| 范围 | x 跨度 | y 跨度 |
|---|---|---|
| 声明 bounds | ~3590 m | ~4433 m |
| 仅 buildings footprint | ~2900 m | ~3988 m |
| 仅 outdoor_areas | ~3590 m | ~4433 m |

**如果你下采样了 buildings**（如取最近中心的 N 栋）**，必须从子集重算
bounds**，不要复用顶层 bounds，否则渲染时建筑会被压成中间一小块（参见
2026-04-26 作品集网站事故）：

```python
sampled = pickNearest(buildings, center, 320)
xs = [v["x"] for b in sampled for v in b["polygon"]["vertices"]]
ys = [v["y"] for b in sampled for v in b["polygon"]["vertices"]]
bounds = {"minX": min(xs), "minY": min(ys), "maxX": max(xs), "maxY": max(ys)}
```

### 5.2 道路是被切碎的

`outdoor_areas` 里的 road 都按 `segment_length`（默认 ~50m）切成小段。
要拿一条完整路：

```python
segments_by_road = {}
for a in data["outdoor_areas"].values():
    if a["area_type"] == "road" and a.get("road_name"):
        segments_by_road.setdefault(a["road_name"], []).append(a)
# 然后按 segment_index 排序
```

---

## 6. 给可视化下游的最小 export 示例

```python
import json
data = json.loads(open("data/lanecove_atlas.json").read())

def export_minimal_geometry(out_path):
    buildings = []
    for b in data["buildings"].values():
        buildings.append({
            "id": b["id"],
            "type": b.get("building_type", "generic"),
            "footprint": [(v["x"], v["y"]) for v in b["polygon"]["vertices"]],
            "floors": b.get("floors", 1),
            "height_m": b.get("floors", 1) * 3.0,
        })

    # 从子集重算 bounds（避免 5.1 踩坑）
    xs = [x for b in buildings for x, _ in b["footprint"]]
    ys = [y for b in buildings for _, y in b["footprint"]]
    bounds = {"minX": min(xs), "minY": min(ys),
              "maxX": max(xs), "maxY": max(ys)}

    json.dump({"version": 1, "bounds": bounds, "buildings": buildings},
              open(out_path, "w"))
```

---

## 7. 进一步阅读

- `docs/map_pipeline/01-Pipeline总览.md` —— 数据是怎么生成的
- `docs/map_pipeline/02-数据模型与代码改动.md` —— 完整 Pydantic 模型定义
- `synthetic_socio_wind_tunnel/atlas/models.py` —— 源头 schema（Building / OutdoorArea / Polygon / Coord）
- `synthetic_socio_wind_tunnel/atlas/service.py` —— Atlas 查询 API
