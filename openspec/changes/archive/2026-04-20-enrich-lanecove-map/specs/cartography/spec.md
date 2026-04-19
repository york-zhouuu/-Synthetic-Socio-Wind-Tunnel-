# cartography — 多源地图富化（change delta）

## MODIFIED Requirements

### Requirement: GeoJSON 导入主入口
`GeoJSONImporter.import_file(path, region_id) → Region` SHALL：
- 解析标准 FeatureCollection；
- **从 OSM 标签 与 Overture 富化字段**（以 `overture:` 为前缀）两套元数据推断
  `function_type`、`area_type`、`building_type`、`height`、`floors`；
- 将长度超过设定阈值（默认 100 米）的道路分段为 50–100 米的
  `OutdoorArea(area_type="street")`；
- 若 feature `properties["affordances"]` 存在（来自 conflation），SHALL 把它
  解码为 `ActivityAffordance` tuple 写入 `Building.affordances`；
- 自动推断连接（街-街、建筑-街、交叉口）；
- 返回可直接交给 `Atlas` 的 Region。

#### Scenario: 导入富化后的 GeoJSON
- **WHEN** 输入文件中某 building 属性含 `{"name": "Sunrise Café",
  "amenity": "cafe", "affordances": [{"activity_type": "buy_coffee", ...}]}`
- **THEN** 返回的 Region 里该 Building SHALL `name == "Sunrise Café"`，
  `building_type == "cafe"`，`affordances` 至少含一条 `buy_coffee`

#### Scenario: 兼容纯 OSM 输入
- **WHEN** 输入文件为无 `overture:*` 字段与 `affordances` 的纯 OSM 导出
- **THEN** importer SHALL 不报错，产出等价于当前实现的 Region

## ADDED Requirements

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
- **THEN** `mock_map.create_atlas_from_osm` SHALL 使用纯 OSM 文件，并在日志中
  明确标注 `[fallback] pure OSM`

#### Scenario: 增量刷新
- **WHEN** 只重跑 `tools/fetch_overture.py` 和 `tools/enrich_map.py` 而不动其它
- **THEN** `data/lanecove_enriched.geojson` SHALL 被原子替换；下次 atlas 生成
  能看到新数据

### Requirement: Overture Buildings 去重规则
`merge_sources` SHALL：
- 以 OSM buildings 为初始集合全量保留；
- 对每个 Overture building polygon，取其中心点：
  - 若落入任一 OSM building polygon → **合并属性**，把 OSM 缺失的字段
    （`overture:class`、`overture:height`、`overture:num_floors`、
    `overture:names.primary`、`overture:confidence`、`overture:primary_source="osm"`）
    补上；
  - 否则 → **新增** 该 Overture building 到输出，标注
    `overture:primary_source="overture_buildings"`。
- SHALL NOT 覆盖 OSM 已有字段（name、amenity、shop、building）。

#### Scenario: OSM 已命名的建筑不被覆盖
- **WHEN** OSM 含 `name="Lane Cove Public Library"`，Overture buildings 含
  同位置但 `names.primary="Library Lane Cove"`
- **THEN** 合并后该 building 的 `name` 仍为 `"Lane Cove Public Library"`，
  Overture 名字仅以 `overture:names.primary` 保留

#### Scenario: OSM 未覆盖区域被 Overture 补齐
- **WHEN** 某地段 OSM 无任何 building polygon，Overture buildings 有 10 个
- **THEN** 合并后该地段 SHALL 新增 10 个 building polygon，
  每个 `properties["overture:primary_source"] == "overture_buildings"`

### Requirement: POI 贴合建筑生成 affordance
`merge_sources` SHALL 为每个 Overture Place 点找到合适宿主：

- 优先宿主 = 包含该点的 OSM building polygon；
- 次优宿主 = 包含该点的 Overture-added building polygon；
- 若都找不到且 Place 的 `confidence >= place_confidence_floor`（默认 0.5），
  SHALL 构造一个边长 `stub_size_m` 的正方形 polygon 作为 stub building；
- 若 `confidence < place_confidence_floor` 且无宿主，SHALL 丢弃该 Place
  并记录在合并日志中。

当找到宿主后：
- 把 Place 的 `names.primary`、`categories.primary/alternate`、`confidence`
  合并到宿主 `properties["affordances"]` 列表（累积，可多个）；
- 若宿主 `name` 为空或匹配默认模式 `^building_\d+$`，
  SHALL 用 Place 的 `names.primary` 覆盖 `name`。

#### Scenario: 咖啡馆 POI 贴到建筑
- **WHEN** 某 OSM building 原 name 为 `"building_447"`，Overture Place 点落其内
  `names.primary="Sunrise Café"`，`categories.primary="eat_and_drink.coffee"`
- **THEN** 合并后该 building `name=="Sunrise Café"`，
  `affordances` 至少含一条 `{activity_type="eat", ...}` 且
  `properties["overture:place:category"]=="eat_and_drink.coffee"`

#### Scenario: 低置信度的 POI 被丢弃
- **WHEN** 一个 Place `confidence=0.2` 且无宿主 polygon
- **THEN** 合并产物 SHALL 不含此 Place，合并日志 SHALL 记录丢弃原因

### Requirement: Overture 类别到 ActivityAffordance 的映射
conflation 模块 SHALL 提供一个确定性的"类别 → activity_type"映射：

| Overture category 前缀 | activity_type |
|---|---|
| `eat_and_drink.*` | `eat` |
| `shopping.*` | `shop` |
| `education.*` | `study` |
| `health.*` | `medical` |
| `community_and_government.*` | `civic` |
| `arts_and_entertainment.*` | `entertainment` |
| `accommodation.*` | `stay` |
| 其它 / 未命中 | `visit` |

- 未命中的 Place SHALL 仍被保留为 `activity_type="visit"` 的 affordance，
  并把原始 category 放在 `description` 里（`f"{category.primary}"`）。
- 时间段 `time_range` 默认为 `(0, 24)`，除非 Overture Place 提供结构化营业时间。

#### Scenario: 未知类别降级
- **WHEN** Place category 为 `religion.synagogue`（未命中上表）
- **THEN** 合并后对应 affordance `activity_type=="visit"`，
  `description` 包含原类别字符串

### Requirement: 富化覆盖率指标
`tools/diagnose_atlas.py` SHALL 在现有输出之外报告：
- `named_building_share` = `name` 不匹配通用占位符正则
  `^(building_\d+|house)$`（大小写不敏感）的建筑占比
- `typed_building_share` = `building_type != "residential"` 的建筑占比
- `affordance_covered_share` = `len(affordances) > 0` 的建筑占比（含默认
  `reside`，反映"任何语义"覆盖）
- `reside_covered_share` = 含 `reside` affordance 的建筑占比（居住语义）
- `poi_covered_share` = 含 **非 `reside`** affordance 的建筑占比
  （即真实 POI 绑定的建筑；这是"商业密度"意义上的富化）
- `poi_covered_count` = 绝对数量，便于低密度郊区用绝对值做门禁
- `overture_source_counts`：按 `osm_tags["overture:primary_source"]` 聚合

郊区现实校准：Lane Cove 2066 主要是住宅郊区，大多数建筑就是无名住宅。
阈值如下，面向郊区场景：

`tests/test_cartography.py::TestLaneCoveEnrichedConnectivity`
SHALL 在 `data/lanecove_enriched.geojson` 存在时断言：
- 主连通分量建筑占比 ≥ 85%（不回归）
- `affordance_covered_share >= 0.80`（含 reside 默认后，几乎每栋建筑都有语义）
- `reside_covered_share >= 0.70`（至少 7 成建筑是居住，带 reside 默认）
- `poi_covered_count >= 700`（绝对数：至少 700 栋建筑绑定了真实 POI）

商业密度的百分比指标不做门禁（郊区天然低），仅在诊断输出里可见以支持
后续实验调优。

#### Scenario: 富化指标达标
- **WHEN** 运行 `python3 tools/diagnose_atlas.py data/lanecove_atlas.json`
  （由富化 GeoJSON 生成的 atlas）
- **THEN** 输出 SHALL 包含 `reside_covered_share >= 0.70`、
  `poi_covered_count >= 700` 两行，`TestLaneCoveEnrichedConnectivity` SHALL PASS

### Requirement: 住宅建筑的默认语义与 agent 接入
Lane Cove 90% 以上建筑是住宅，若只有商业 POI 会富化，agent 将无法"枚举可住的
建筑"。为此 importer SHALL 在 `_extract_building` 中为每个
`building_type == "residential"` 且当前 affordances 为空的建筑，追加一条
默认 `ActivityAffordance`：

- `activity_type = "reside"`
- `capacity` 按启发式推断：`building == "apartments"` 或 `overture:class ==
  "residential"` 且 `floors >= 3` 时，`capacity = min(12, floors * 4)`；
  否则 `capacity = 1`。
- `description` 以 `"(inferred)"` 结尾，便于 Phase 2 的真实住户数据覆盖时
  以来源区分。

`atlas.service.Atlas` SHALL 暴露：
- 已存在的 `list_buildings_by_type(building_type)`；
- 新增 `list_residential_buildings()` 便利方法（等价于
  `list_buildings_by_type("residential")`），语义即"住宅候选集"。

Phase 2 扩展点（不在本 change 实施，但需保持接口不破坏）：
- 住户（tenant）与家庭（household）结构化数据将附加到 Building.osm_tags
  或新字段 `residential_profile`；
- Agent 的 `profile.home_location` 分配逻辑由 orchestrator 消费
  `list_residential_buildings()` 与 affordance.capacity 做容量约束。

#### Scenario: 纯住宅建筑获得默认 reside affordance
- **WHEN** 导入一个 `properties["building"] == "house"` 且无 POI 绑定的建筑
- **THEN** 产出的 `Building.affordances` SHALL 含且仅含一条
  `activity_type == "reside"` 且 `description` 以 `"(inferred)"` 结尾

#### Scenario: 带 POI 的住宅不被 reside 覆盖
- **WHEN** 某 apartment building 绑定了一条 `eat` POI（例如楼底下的餐厅）
- **THEN** affordances SHALL 含 `eat`；此时是否补默认 `reside` 由实现决定，
  但真实的 POI affordance SHALL 保留

#### Scenario: 多层公寓推断更高容量
- **WHEN** `osm_tags["overture:class"] == "residential"` 且 `floors == 5`
- **THEN** 生成的 `reside` affordance `capacity` SHALL 为
  `min(12, 5*4) == 12`

#### Scenario: Agent 枚举住宅候选
- **WHEN** agent 工厂调用 `atlas.list_residential_buildings()`
- **THEN** 返回所有 `building_type == "residential"` 的 Building，每个都可通过
  其 `affordances` 中的 `reside.capacity` 读取住户容量

### Requirement: 许可与 Attribution
仓库 `README.md` SHALL 有一节"Data sources & attribution"，列出：
- OpenStreetMap 贡献者（ODbL）；
- Overture Maps Foundation（ODbL + CDLA-P 2.0）；
- Geoscape G-NAF（若日后接入，需 EULA 链接）；
- Microsoft Global ML Building Footprints（若作为 fallback 接入，CDLA-P 2.0）。

- `data/` 下的派生产物 SHALL 在文件头注释或伴随的 `README.md` 指明其数据来源
  组合与版本时间戳。

#### Scenario: 审查合规
- **WHEN** 外部审查员查看仓库 README
- **THEN** SHALL 能直接看到所有数据源的许可文本链接与适用范围
