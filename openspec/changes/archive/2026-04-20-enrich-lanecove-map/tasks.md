# Tasks — enrich-lanecove-map

## 1. 数据拉取
- [x] 1.1 新增 `pyproject.toml` 开发依赖组 `map-enrichment`：`overturemaps`、
      `shapely`（可选；也可手写 point-in-polygon 兜底）
- [x] 1.2 写 `tools/fetch_overture.py`：
      - 常量：`LANECOVE_BBOX = (151.145, -33.843, 151.178, -33.798)`
      - 调用 `overturemaps download --type=building --bbox=... -f geojson`
      - 调用 `overturemaps download --type=place --bbox=... -f geojson`
      - 产物写 `data/sources/overture_buildings_YYYY-MM.geojson`、
        `data/sources/overture_places_YYYY-MM.geojson`
      - 同步软链/复制一份到 `data/overture_buildings.geojson` /
        `data/overture_places.geojson` 作为"当前"版本
- [x] 1.3 README 增加 "Data sources & attribution" 段
      列出 OSM、Overture、Geoscape 的各自许可

## 2. Conflation 模块
- [x] 2.1 新建 `synthetic_socio_wind_tunnel/cartography/conflation.py`：
      - `merge_sources(osm_path, overture_buildings_path, overture_places_path,
         *, place_confidence_floor=0.5, stub_size_m=8.0) -> dict`
        返回合并后的 GeoJSON FeatureCollection
      - 内部用 `_polygon_contains_point` 纯 Python 实现（射线法）
- [x] 2.2 conflation 规则按 design.md 的四步实施：
      - 初始集合 = OSM 原样
      - Overture Buildings 去重（中心点 in OSM polygon 合属性，否则新增）
      - Places 贴建筑（累积 affordances；覆盖匿名 name）
      - 找不到宿主的 Place 变成 stub building
- [x] 2.3 规则 3 的 affordance 映射：Overture `categories.primary` → 粗类：
      - `eat_and_drink.*` → `ActivityAffordance(activity_type="eat")`
      - `shopping.*` → `shop`
      - `education.*` → `study`
      - `health.*` → `medical`
      - `community_and_government.*` → `civic`
      - 未知类别 → 仅保留 `description` 里的原始字符串
- [x] 2.4 新建 `tools/enrich_map.py` CLI，调用 merge_sources 并写
      `data/lanecove_enriched.geojson`

## 3. Importer 扩展
- [x] 3.1 `cartography/importer.py::_extract_building` 读取：
      - `properties["overture:class"]` → 参与 `_infer_building_type`
      - `properties["overture:height"]` → 若无 OSM height，推断 floors
      - `properties["overture:names"]` → name 空时回填
      - `properties["affordances"]` → 若存在，转成 `ActivityAffordance` tuple
        写入 `Building.affordances`
- [x] 3.2 把新增的 Overture 字段一并复制进 `Building.osm_tags`（以 `overture:`
      前缀保持命名空间），供下游感知层检索
- [x] 3.3 `_make_id` 保持当前去重行为；确认 Overture 新增 polygon 的生成 ID
      不与 OSM 冲突

## 4. Pipeline 切换
- [x] 4.1 `tools/map_explorer/mock_map.py::create_atlas_from_osm` 加入逻辑：
      - 若 `data/lanecove_enriched.geojson` 存在 → 用它
      - 否则用 `data/lanecove_osm.geojson`（兼容回退）
- [x] 4.2 删除旧 `data/lanecove_atlas.json`、重跑生成富化版
      （`make enrich-map` 完整链已跑通；diagnose 输出确认 4 条门禁全过：
      connectivity 93.8%，affordance 97.6%，reside 96.2%，POI-bound 794）

## 5. 诊断 & 测试
- [x] 5.1 `tools/diagnose_atlas.py` 新增三项指标：
      - `named_building_share`：`name != "building_\d+"` 的建筑占比
      - `typed_building_share`：`building_type != "residential"`（即非默认）的占比
      - `affordance_covered_share`：`len(affordances) > 0` 的建筑占比
- [x] 5.2 `tests/test_cartography.py` 新增：
      - `TestConflation::test_category_to_activity_mapping`
      - `TestConflation::test_merges_overture_attrs_into_osm_building`
      - `TestConflation::test_merges_overture_building_without_osm_host`
      - `TestConflation::test_place_point_inside_building_adds_affordance`
      - `TestConflation::test_osm_name_not_overwritten_by_overture_place`
      - `TestConflation::test_unhosted_low_confidence_place_is_dropped`
      - `TestConflation::test_unhosted_high_confidence_place_becomes_stub`
      - `TestImporterReadsEnrichedFields::*`（3 条：affordances / overture:class / overture:height）
- [x] 5.3 新增 `TestLaneCoveEnrichedConnectivity`：仅当
      `data/lanecove_enriched.geojson` 存在时运行，断言
      `main_component_share >= 85%` 不回归、`named >= 60%`、`typed >= 25%`

## 6. Spec 落地与归档
- [ ] 6.1 本 change 的 `specs/cartography/spec.md` delta 审阅通过后，
      执行 `/opsx:archive enrich-lanecove-map` 把 MODIFIED 条款合并进
      `openspec/specs/cartography/spec.md`（留给用户 review 后触发）
- [x] 6.2 更新 `docs/map_pipeline/` 里的实操指南，加入 enrichment 流程图

## 7. 横切
- [x] 7.1 `.gitignore` 明确 `data/sources/` 目录不入 git（时间戳原始快照每次重拉），
      保留 `data/overture_buildings.geojson` / `data/overture_places.geojson`
      / `data/lanecove_enriched.geojson` 入 git 保证可复现
- [x] 7.2 新增 Makefile 任务 `make enrich-map`：
      `fetch-overture → conflate → regenerate-atlas → diagnose-atlas`
