# Tasks — cartography-dedup-buildings

修 atlas 里的建筑物重叠问题（60.8% 涉及，~3000 大重叠对）。新增 dedup pass
+ 升级 rv 碰撞检测 + 加几何质量回归测试。

**Chain-Position**: `infrastructure`
**前置**: 无（独立 fix）

## 1. dedup 模块

- [x] 1.1 新建 `synthetic_socio_wind_tunnel/cartography/dedup.py`：
  - `_polygon_aabb(p: Polygon) -> tuple[float, float, float, float]`
  - `_aabb_overlap(a, b) -> bool`
  - `_shoelace(vertices) -> float` —— signed area
  - `_clip_polygon(subject, clipper) -> list[Coord]` —— Sutherland-Hodgman
    凸多边形裁剪
  - `polygon_iou(a: Polygon, b: Polygon) -> float`
  - `dedup_buildings(region: Region, *, iou_threshold: float = 0.5) -> Region`

- [x] 1.2 `dedup_buildings` 实现：
  - 用 50 m grid bucket 空间索引避免 O(n²)
  - 对每对邻居 building 算 IoU；> threshold 加入"合并组"
  - score 函数（D3）：`100*has_real_name + len(osm_tags) + 5*has_overture +
    10*has_typed_building + 5*has_description + 2*len(affordances)`
  - 合并：保留高分主体；把丢弃栋的非空 osm_tags / affordances / description
    并入主体（osm_tags 用 `setdefault`，affordances 用 set union by tuple）
  - 在主体的 osm_tags 里加 `merged_from_ids: "id1,id2,..."` 记录

- [x] 1.3 单元测试 `tests/test_cartography_dedup.py`：
  - `test_polygon_iou_identical`: 完全重合 → IoU > 0.99
  - `test_polygon_iou_disjoint`: AABB 不相交 → IoU == 0
  - `test_polygon_iou_half_overlap`: 50% 重叠 → IoU ≈ 0.33
  - `test_dedup_keeps_richer`: 两栋 IoU=0.95，一栋有 name 一栋无 → 保留 named
  - `test_dedup_merges_tags`: 合并后 osm_tags 含两边的非空字段
  - `test_dedup_skips_terrace`: 共墙排屋（IoU < 0.05）→ 不合并
  - `test_dedup_records_merged_from`: 主体的 osm_tags['merged_from_ids']
    SHALL 含被丢弃栋的 id

## 2. 接入 lanecove pipeline

- [x] 2.1 改 `synthetic_socio_wind_tunnel/cartography/lanecove.py`：
  - import `from .dedup import dedup_buildings`
  - 在 `_infill_riverview(region)` 调用**之前**插入：
    ```python
    n_before = len(region.buildings)
    region = dedup_buildings(region)
    print(f"[dedup] {n_before} → {len(region.buildings)} buildings")
    ```

## 3. rv 碰撞检测升级

- [x] 3.1 改 `_infill_riverview` 内部：
  - `existing` 列表从 `[(cx, cy)]` 改为 `[(x0, y0, x1, y1)]`（AABB 列表）
  - 初始化时遍历 `region.buildings.values()` 取 polygon AABB
  - `has_collision(...)` 改签名 + 实现：接收 lot AABB，对每个 existing AABB
    用 `_aabb_overlap` 判断
- [x] 3.2 rv 屋生成成功后追加自己的 AABB 到 existing：
  - `existing.append((x0, y0, x1, y1))` for each new rv house

## 4. 几何质量回归测试

- [x] 4.1 新建 `tests/test_atlas_quality.py`：
  - fixture：load 现有 cache `data/lanecove_atlas.json` 为 Region（不重跑 importer）
  - `test_no_iou_duplicates`: 大于 IoU 0.5 的对数 SHALL == 0
  - `test_significant_overlaps_under_threshold`: 大于 30 m² 重叠的对数
    SHALL < 50
  - `test_building_count_in_expected_range`: dedup 后建筑数 SHALL ∈ [5800, 7000]
    （baseline 7552，预计降到 6000±）
  - tests skip 如果 cache 不存在（CI 友好）

## 5. Re-bake atlas

- [x] 5.1 删 `data/lanecove_atlas.json`
- [x] 5.2 跑一次 cartography 重建：
  ```bash
  python3 -c "from synthetic_socio_wind_tunnel.cartography.lanecove import create_atlas_from_osm; create_atlas_from_osm()"
  ```
- [x] 5.3 验证日志含 `[dedup] N_before → N_after`，差值合理（>1000）

## 6. 验证

- [x] 6.1 全 pytest 通过（533+）；新增的 atlas_quality + dedup 测试也通过
- [x] 6.2 跑 6-variant smoke 30 天确认 sim 不破：
  ```bash
  python3 tools/run_variant_suite.py --variants baseline,hyperlocal_push \
    --seeds 2 --num-days 3 --agents 20 --mode dev --phase-days 1,1,1
  ```
- [x] 6.3 手工开 Map Explorer (`python3 tools/map_explorer/server.py`) 肉眼看
  几个明显的旧重叠区域（CBD / Riverview）确认改善
- [x] 6.4 `openspec validate cartography-dedup-buildings --strict` 通过

## 7. 文档

- [x] 7.1 更新 `docs/map_pipeline/04-reading-the-atlas.md`：
  - 楼数从 "7552" 改为新值
  - 移除"建议重算 bounds"节里的"OSM × OSM 重复"警告（已修）
- [x] 7.2 更新 `docs/agent_system/19-system-snapshot.md` 历史决策点表
