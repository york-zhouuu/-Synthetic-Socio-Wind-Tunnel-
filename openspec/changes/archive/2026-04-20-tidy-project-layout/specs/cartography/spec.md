# cartography — 布局整理（change delta）

## MODIFIED Requirements

### Requirement: 多源富化流水线
仓库 SHALL 提供一条可复现的"多源 → 单文件 GeoJSON → Atlas"富化流水线：

1. **Fetch**：`tools/fetch_overture.py` 以 Lane Cove bbox 拉取 Overture
   `building` 与 `place` 主题，分别产出
   `data/sources/overture_buildings_YYYY-MM.geojson`、
   `data/sources/overture_places_YYYY-MM.geojson`。
2. **Conflate**：`cartography.conflation.merge_sources(osm_path,
   overture_buildings_path, overture_places_path, *, place_confidence_floor,
   stub_size_m) → dict` 返回合并后的 FeatureCollection。
3. **Persist**：`tools/enrich_map.py` 把合并产物写入
   `data/lanecove_enriched.geojson`。
4. **Import**：`GeoJSONImporter` 消费上一步产物，产出 Atlas Region。

- merge_sources SHALL 纯 Python（不强依赖 shapely），point-in-polygon 用射线法。
- merge_sources SHALL 保持 OSM 的 `@id` / `@category` 字段，以便回溯来源。

#### Scenario: 回退到纯 OSM
- **WHEN** `data/lanecove_enriched.geojson` 不存在但 `data/lanecove_osm.geojson` 存在
- **THEN** `cartography.lanecove.create_atlas_from_osm` SHALL 使用纯 OSM 文件，
  并在日志中明确标注 `[fallback] pure OSM`

#### Scenario: 增量刷新
- **WHEN** 只重跑 `tools/fetch_overture.py` 和 `tools/enrich_map.py` 而不动其它
- **THEN** `data/lanecove_enriched.geojson` SHALL 被原子替换；下次 atlas 生成
  能看到新数据

## ADDED Requirements

### Requirement: Lane Cove 生产入口位于 cartography.lanecove
Lane Cove 真实场景的 atlas 加载 / Riverview 合成补齐 / demo 知识地图构建
SHALL 位于 `synthetic_socio_wind_tunnel.cartography.lanecove` 模块，
暴露以下公共函数：

- `create_atlas_from_osm(path: Path | None = None, segment_length: float = 60.0) -> Atlas`
- `create_demo_knowledge_maps(atlas: Atlas) -> dict[str, AgentKnowledgeMap]`
- `create_ledger_with_demo_knowledge(atlas: Atlas) -> Ledger`

- 该模块 SHALL NOT 包含任何与虚构演示场景（例如"新苑里社区"）相关的函数；
  那些 SHALL 位于 `tools/map_explorer/demo_map.py`。
- `tools/map_explorer/mock_map.py` 若存在，SHALL 仅作为打 `DeprecationWarning`
  的兼容 shim，`from synthetic_socio_wind_tunnel.cartography.lanecove import *`
  与 `from tools.map_explorer.demo_map import *` 并重新导出。

#### Scenario: 生产入口路径
- **WHEN** 外部代码调用 `from synthetic_socio_wind_tunnel.cartography.lanecove
  import create_atlas_from_osm; atlas = create_atlas_from_osm()`
- **THEN** 返回一个加载好的 `Atlas`（优先用富化 GeoJSON，回退到纯 OSM），
  与调用前的旧路径 `tools.map_explorer.mock_map.create_atlas_from_osm`
  行为等价

#### Scenario: 旧路径 shim 仍可用但发出弃用警告
- **WHEN** 外部代码仍使用 `from tools.map_explorer.mock_map import
  create_atlas_from_osm`
- **THEN** 调用可成功，但 Python SHALL 发出一条 `DeprecationWarning`，
  消息指向 `synthetic_socio_wind_tunnel.cartography.lanecove`

### Requirement: 数据拉取工具命名统一
Lane Cove OSM 数据抓取脚本 SHALL 统一命名为 `tools/fetch_lanecove.py`。
不再保留 `_v2` 或其它版本后缀；任何临时/过期脚本 SHALL 被删除而非保留为
"参考版本"。

#### Scenario: 统一入口
- **WHEN** 新读者查看 `tools/` 目录
- **THEN** SHALL 只看到一个 `fetch_lanecove.py`（非 `_v1` / `_v2` 变体），
  与 `fetch_overture.py` 并列作为两类数据抓取入口
