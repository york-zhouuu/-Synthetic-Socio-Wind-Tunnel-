## ADDED Requirements

### Requirement: Atlas 几何质量不变量

cartography pipeline 产出的 Region SHALL 满足以下几何质量不变量：

1. **不存在 IoU > 0.5 的建筑物对**——同一栋楼不能在 atlas 里出现两次
   （或几何上几乎相同的两栋）
2. **大面积重叠（footprint 交叉 > 30 m²）的建筑对数量** SHALL < 50
   （为排屋共墙 / OSM 标注误差留余量；当前 baseline ~3000）

设计意图（见 `cartography-dedup-buildings` change design D2-D6）：
- 多源融合（OSM + Overture）会引入重复建筑；合成 infill 屋会撞上 OSM 真楼
- 这些 invariant 写成可测试断言后，未来 cartography 改动不再倒退
- IoU 0.5 阈值在排屋共墙（IoU < 0.05）与近重复楼（IoU > 0.6）之间
  足够分辨

具体要求：

1. cartography pipeline 在产出 Region 之前 SHALL 调用 dedup pass，把
   IoU > 0.5 的建筑对合并为一栋；`Region.buildings` 内 MUST NOT 含
   IoU > 0.5 的楼对
2. dedup 合并 SHALL 保留信息更丰富的那栋作主体；丢弃栋的非空 osm_tags /
   affordances / description SHALL 合并到主体
3. 合成 infill 屋的碰撞检测 SHALL 用 polygon AABB 真实相交，MUST NOT
   仅用中心距离阈值
4. 公共 API（Atlas / Building / OutdoorArea / Region）MUST NOT 改变

#### Scenario: 完全重合的两栋楼被合并
- **WHEN** Region 含两栋 footprint 顶点几乎相同的建筑（IoU = 0.98）
- **THEN** dedup 后 SHALL 只剩 1 栋；保留信息丰富那栋（如有 name + osm_tags
  者优先）；丢弃栋的 osm_tags 合并入留下栋

#### Scenario: 排屋共墙不被误合并
- **WHEN** Region 含两栋 footprint 共一面墙的排屋（IoU < 0.1，重叠面积 < 1 m²）
- **THEN** dedup 后 SHALL 仍保留 2 栋

#### Scenario: 合成 infill 屋避开真实建筑
- **WHEN** 在 `_infill_riverview` 区域内有一栋长条 OSM 公寓（footprint 30m × 8m），
  其中心距某 lot 中心 12 m
- **THEN** 该 lot SHALL 被跳过（AABB 真实相交 → 碰撞）；MUST NOT 因中心距离
  > 10 m 误判为可放置

#### Scenario: 几何质量回归测试
- **WHEN** atlas cache 加载后跑 `tests/test_atlas_quality.py`
- **THEN** IoU > 0.5 重复对数量 SHALL == 0；
  > 30 m² 大重叠对数量 SHALL < 50


### Requirement: Dedup 实现独立模块化

dedup 逻辑 SHALL 抽取为独立模块 `synthetic_socio_wind_tunnel/cartography/dedup.py`，
不嵌入 `lanecove.py` 或 `conflation.py`。

设计意图：
- dedup 处理 Pydantic Region 对象（post-import），与 conflation 的 GeoJSON feature
  处理（pre-Region）层级不同
- 独立模块便于单元测试 polygon IoU / 合并策略，不依赖完整 atlas
- 未来其它 region 项目（不只 Lane Cove）也能复用

具体要求：

1. SHALL 提供 `dedup_buildings(region: Region) -> Region` 公共函数
2. SHALL 提供 `polygon_iou(a: Polygon, b: Polygon) -> float` 工具函数
3. MUST NOT 引入 shapely / geopandas 等新依赖；用 stdlib + 已有
   atlas.models.Polygon

#### Scenario: 模块独立可测
- **WHEN** 单元测试构造 4 顶点 Polygon a, b 完全重合
- **THEN** `polygon_iou(a, b)` SHALL 返回接近 1.0 的浮点数（差 < 0.01）

#### Scenario: 不引入新依赖
- **WHEN** 检查 `pyproject.toml` 在本 change 前后差异
- **THEN** SHALL MUST NOT 出现 shapely / geopandas / pyproj 等新依赖
