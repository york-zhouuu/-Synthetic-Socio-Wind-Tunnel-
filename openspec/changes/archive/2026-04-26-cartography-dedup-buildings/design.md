## Context

2026-04-26 实地打开 Map Explorer 时用户发现地图上存在大量建筑物重叠。事后量化：
60.8% 的建筑涉及 AABB 重叠，其中 1119 对 OSM × OSM 大重叠（>30 m²），最大 17370 m²。
分类来源：

| 类别 | pair 数 | 主因 |
|---|---|---|
| OSM × OSM | ~2800 | 多源融合（OSM + Overture）centroid-in-polygon 判重对相同建筑两次入库无能为力 |
| rv × OSM | ~1045 | `_infill_riverview` 用中心距离 10 m 判碰撞，遇长条 OSM 楼漏检 |
| rv × rv | ~1428 | rv 屋互相之间无碰撞检测，仅靠 lot grid 间距 |

产生研究风险：建筑密度被高估 ~25%，对未来 publishable run 中"附近建筑数"等
indicator 是 reviewer 抓手。

## Goals / Non-Goals

**Goals**：
- OSM × OSM 重复（IoU > 0.5）合并掉，保留信息丰富的那栋
- rv 合成屋不再叠加 OSM 真楼或叠加其它 rv 屋（>5 m² overlap）
- 加几何质量回归测试，未来不再倒退
- atlas building 数从 ~7552 降到合理范围（预计 ~5800-6200）

**Non-Goals**：
- 不引入 shapely / geopandas 等重型 GIS 依赖（用手写 polygon 工具）
- 不解决 rv-rv 微小共墙重叠（<5 m²）——视为合理排屋共享
- 不修 OSM × OSM **不重合但相邻**的几何（rendering 端可叠透明度）
- 不动 conflation.py 的 Overture-vs-OSM 主流程（只在外面加一层 dedup pass）

## Decisions

### D1：把 dedup 放在 `lanecove.py`，不放在 `conflation.py`

**选择**：在 `cartography/lanecove.py::create_atlas_from_osm` 里 import 一个独立
模块 `cartography/dedup.py` 的 `dedup_buildings(region) -> Region`，在
`_infill_riverview` 之前调用。

**为什么不放在 conflation.py 里**：conflation 处理 GeoJSON feature 列表（pre-Region），
dedup 处理 Pydantic Region 对象（post-import）。语义层级不同。也方便单元测 dedup
本身——给个手造 Region，断言出来的 Region 楼数减少且关键字段保留。

### D2：用 polygon AABB + Sutherland-Hodgman 算 IoU，不引入 shapely

**选择**：手写 `_polygon_aabb` + `_clip_polygon_against_polygon`（Sutherland-Hodgman
算法）+ `_polygon_area`（Shoelace）。

**备选**：`shapely`（成熟、快、但 pip dependency 重 ~10 MB + 需 GEOS 系统库；项目目前 zero
GIS deps）。

**Rationale**：dedup 只需要 IoU 这一个数字，且建筑物多边形通常 4-12 顶点，手写算法
够用且可读。引入 shapely 是个"为单一函数装大锤"的反模式。

```python
def iou(poly_a: Polygon, poly_b: Polygon) -> float:
    if not _aabb_overlap(poly_a, poly_b):
        return 0.0
    intersection = _clip_polygon(poly_a, poly_b)  # Sutherland-Hodgman
    if not intersection:
        return 0.0
    a_area = abs(_shoelace(poly_a))
    b_area = abs(_shoelace(poly_b))
    i_area = abs(_shoelace(intersection))
    return i_area / (a_area + b_area - i_area)
```

### D3：合并策略——保留"信息更丰富"的那栋

**选择**：score 函数排序，高分留：
```
score(b) = 1{name not generic} * 100
        + len(osm_tags)
        + 1{overture:primary_source != None} * 5
        + 1{building_type != "generic"} * 10
        + 1{description != ""} * 5
        + len(affordances) * 2
```

**Rationale**：命名建筑（"lane_cove_community_hub"）几乎必然是手工标注，含真实
business 信息；通用 building_NNNN 是自动批处理产物。Overture-richmerged 比纯 OSM 好。

**保留时**：把被丢弃的那栋的非空 tag / affordance / description 合并到留下的栋
（防丢信息）。

### D4：IoU 阈值 0.5

**选择**：IoU > 0.5 视为"近似同一栋楼"。

**Rationale**：
- IoU 0.5 表示重叠区 ≥ 联合面积一半 → 几何上不可能是两栋独立楼
- 排屋共墙 IoU 通常 < 0.05（共墙线宽几乎零面积）
- 紧邻独立屋 IoU 通常 < 0.1
- 实测 17370 m² 对的 IoU > 0.95；中等重叠对 IoU 也都 > 0.6

**Edge case**：IoU 在 0.3-0.5 之间的中度重叠属"几何错位但都是真楼"，本 change
不动；以后 cartography-quality change 里再处理。

### D5：rv 碰撞检测改成"对每栋已有楼的 AABB 真实相交"

**选择**：保留现有 `existing` 列表的内存格式，但把 `has_collision` 改成：

```python
def has_collision(lot_aabb: tuple[float, float, float, float]) -> bool:
    for ex_aabb in existing_aabbs:
        if _aabb_overlap(lot_aabb, ex_aabb):
            return True
    return False
```

**为什么不直接用 polygon-polygon IoU**：rv 阶段建百千次碰撞检测；AABB 已经够用
（rv 屋是矩形/L 形，footprint 紧贴 AABB），polygon 精算开销大。AABB 略保守
（false-positive 可能漏掉一些位置），但 rv 屋空间充裕，宁愿少建几栋也比叠加好。

**rv-rv 之间**：也加同样的 AABB 检查；新生成的 rv 屋 AABB 加入 existing list。

### D6：geometric quality test 阈值

**选择**：
```python
def test_atlas_overlap_under_threshold():
    region = ...
    pairs_big = count_overlap_pairs(region, area_threshold=30.0)
    assert pairs_big < 50, f"got {pairs_big} significant overlaps"

def test_no_iou_duplicates():
    region = ...
    pairs_dup = count_iou_pairs(region, iou_threshold=0.5)
    assert pairs_dup == 0
```

**Rationale**：
- 当前 ~3000 大重叠 → 目标 < 50 是 60× 改善，留余量
- IoU 0.5 重复必须为 0（dedup 是确定性的）

**测试运行**：用 `data/lanecove_atlas.json` cache（CI 默认存在）；不重跑 importer
（太慢）。

### D7：要不要给 Building 加 raw_id / merged_from 字段

**选择**：不加。

**Rationale**：
- 公共 API 不变（spec 不动）
- 合并信息可在 osm_tags 里加 `merged_from: id1,id2` 字段，通过现有 dict 通道
- 简单，专注 dedup 主逻辑

## Risks / Trade-offs

**[Risk 1] Sutherland-Hodgman 数值稳定性**
→ 用 epsilon = 1e-9 处理共线点；对凸多边形保证正确（OSM/Overture 99% 是凸或近似凸；
  少数凹楼用 IoU 上界估算"AABB IoU"作 fallback）

**[Risk 2] 信息丢失**
→ 合并时把丢弃栋的非空 tag/affordance 合并到留下栋。手工抽样 20 对 dedup 结果验证

**[Risk 3] building_id 变化破下游 archive**
→ 已归档实验不再跑；live experiments 全部从空 atlas 重采。downstream（作品集网站）
  从新 atlas 重新 export

**[Risk 4] dedup 误杀紧邻独立楼**
→ IoU 0.5 阈值很保守；IoU > 0.5 的几何上几乎不可能是两栋。加测试用例覆盖

**[Risk 5] 性能（O(n²) 在 7552 楼上）**
→ 用 50 m grid bucket 空间索引；实测 hash bucket 后只比较邻居，预计 < 5 s

## Migration Plan

1. 实现 `cartography/dedup.py`（新文件：polygon utils + `dedup_buildings`）
2. 改 `cartography/lanecove.py`：
   - 在 `_infill_riverview` 调用前插入 `region = dedup_buildings(region)`
   - 重写 `has_collision` 用 AABB
   - rv 屋生成后追加到 existing AABB list
3. 加 `tests/test_atlas_quality.py`（pytest fixture：load cache 后跑断言）
4. 删 cache 重跑 cartography → atlas 重新生成
5. 跑全 pytest（确认无回归）
6. 手工开 Map Explorer 肉眼验证
7. archive sync cartography spec

**回滚**：本 change 是数据质量 fix；如需回滚 git revert + 重跑 cartography
即可。

## Open Questions

1. **Q1**：OSM 内部 dedup 阈值是否要降到 IoU > 0.3？
   倾向：本 change 用 0.5 严格阈值；如果 dedup 后还有目测可见的"几乎重合"
   再调
2. **Q2**：Overture has_height 字段（`overture:height`）能否升级为 Building.floors？
   倾向：不在本 change 范围；属 cartography-enrichment 范畴
3. **Q3**：是否要把 dedup 应用到 OutdoorArea（park / road segment 也可能重复）？
   倾向：不做；road 段是切碎的，重叠属设计预期；park 重复目测无明显问题
