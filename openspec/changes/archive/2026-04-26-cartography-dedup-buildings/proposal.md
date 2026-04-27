## Why

打开 Map Explorer 实地核对时发现，Lane Cove atlas 里 **60.8% 的建筑（4595/7552）涉及
AABB 重叠**——其中 ~2800 对来自 OSM × OSM（多源融合时同一栋楼被进了两次，最大
重叠 17370 m²，几乎完全重合），~1045 对来自 `_infill_riverview` 合成屋撞 OSM 楼，
~1428 对 rv × rv（部分是排屋共墙合理，部分是真叠加）。

根因：

1. **conflation.py 的 dedup 太弱**：当前 Overture vs OSM dedup 用"Overture 多边形
   质心是否落在某个 OSM polygon 内"判断，对**形状差异大**或 **OSM 自身重复**的情况
   失效。OSM 内部从未做过 dedup。
2. **`_infill_riverview` 的碰撞检测过于粗糙**：用"中心距离 < 10 m"，遇到长条形的 OSM
   公寓楼时检测不到重叠。
3. **没有任何 audit / test 检查"建筑物是否互相穿插"**：`tests/test_cartography.py`
   只覆盖 pipeline 机械正确性。Map Explorer 用半透明 fill 渲染，重叠区颜色微深但
   肉眼不显眼——这是个典型的"data quality invariant 没被写成 assertion"的盲区。

**Chain-Position**: `infrastructure`（atlas 数据质量；不动 thesis、不动 agent 行为
契约）。

## What Changes

### 1. `cartography` 加 `_dedup_buildings` pass

新增 polygon-IoU 判重逻辑：当两栋建筑的 IoU > 0.5 时合并，保留信息丰富的那栋
（named > generic；osm_tags 字段更多优先；overture-merged 优先）。在 `_infill_riverview`
**之前**调用，避免 rv 屋叠到将被合并的 OSM 重复楼上。

### 2. `_infill_riverview` 碰撞检测升级

把当前 `has_collision(hx, hy, radius=10)`（中心距离）替换为对所有现有建筑的 polygon
**AABB 真实相交**检查；rv 屋互相之间也用同样 AABB 检查避免 lot-vs-lot 重叠。

### 3. 新增 atlas 几何质量回归测试

`tests/test_atlas_quality.py` 断言：
- 大重叠（> 30 m²）pair 数 < 50（当前 ~3000+）
- IoU > 0.5 的 pair 数 == 0（dedup 后应该没有近重复）

### 4. Re-bake atlas cache

删除 `data/lanecove_atlas.json` cache，重新生成（约 2 分钟）。

## Non-goals

- **不**改 `Atlas` / `Building` / `OutdoorArea` 公共 API
- **不**改 `_infill_riverview` 的 lot 生成布局策略（只动碰撞检测）
- **不**改 conflation 的 OSM × Overture 流程（centroid 判断保留作 first pass）
- **不**做 OSM-vs-Overture 几何对齐（属未来 cartography-quality change）
- **不**给 Building 加 `height` 字段（`floors` 仍是高度代理）
- **不**修地图上独立可见的小问题（如 rv-rv 共墙的小重叠 < 5 m²，视为合理）

## Capabilities

### Modified Capabilities

- `cartography`: 新增 dedup pass requirement + 碰撞检测精度 requirement +
  几何质量 invariant requirement。

### New Capabilities

（无）

## Impact

- **修改文件**：
  - `synthetic_socio_wind_tunnel/cartography/lanecove.py`（dedup 调用 + 改 collision）
  - `synthetic_socio_wind_tunnel/cartography/dedup.py`（新文件，纯函数 IoU 工具）
- **新增测试**：`tests/test_atlas_quality.py`
- **删除并重建**：`data/lanecove_atlas.json`（cache）
- **不改**：Atlas / Building / OutdoorArea 模型；任何 agent / engine / perception 代码；
  任何 spec 契约的 SHALL 字段
- **下游影响**：
  - 新 atlas 楼数从 7552 略降（合并掉 ~1500 重复楼后预计 ~6000）
  - building_id 集合变化；experiment archives 中保存的具体 ID 引用可能失效
    （已归档 sim 不重跑，影响可控）
  - 作品集网站等下游需要从新 atlas 重新 export（属 data refresh，非 break）
- **前置依赖**：无（独立 fix）
- **性能**：dedup pass 用空间索引 ~O(n log n)，预计加 <30 s 到首次 cartography
  耗时；cache 命中时无影响
