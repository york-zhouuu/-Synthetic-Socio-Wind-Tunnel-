# Design — enrich-lanecove-map

## 核心决策：Conflation 发生在 GeoJSON 层，而非 Atlas 层

**两个可选位置**：

| 位置 | 优点 | 缺点 |
|---|---|---|
| A. GeoJSON 层（选定） | 一次合成、可重放、可手动检查产物；importer 无需多源逻辑 | 需自写 conflation |
| B. Atlas 层（多源同时导入） | 每源独立 importer | 跨源 ID 冲突、连通度推断复杂 |

选 A。产物是 `data/lanecove_enriched.geojson`，仍是 FeatureCollection，
走原有 importer，零改动下游。

## 数据源分工

```
OSM Overpass (lanecove_osm.geojson)
    │   [~3386 buildings with polygons, sparse tags]
    │   [~3395 highway LineStrings for roads]
    │
Overture Buildings (overture_buildings.geojson)
    │   [global ML + OSM-derived polygons, ~dense coverage]
    │   [attrs: class, height, num_floors, names.primary]
    │
Overture Places (overture_places.geojson)
    │   [~POI points — name, category, confidence, addresses]
    │
    ▼
conflation.merge_sources() ── lanecove_enriched.geojson
    │
    ▼
GeoJSONImporter ── Region ── Atlas
```

### 为什么 Overture 是首选而非 Microsoft Footprints

- Overture 的 Buildings 主题本身就包含了 Microsoft、Google、OSM 等来源的
  合并（由 Overture Foundation 做 conflation），附有 `sources` 字段。
- Overture Places 免费、覆盖 64M POI、含 category/confidence 字段。
- Microsoft 仅有几何，无 POI 语义；若未来发现 Overture 覆盖不足，再作为
  fallback 引入。

## Conflation 算法

### 输入
- `osm_features`: 已有的 `data/lanecove_osm.geojson`
- `overture_buildings`: `data/overture_buildings.geojson`
- `overture_places`: `data/overture_places.geojson`

### 步骤

1. **初始集合**：把 `osm_features` 中所有 polygon / linestring 原样放入输出。
2. **Overture Buildings 去重**：对每个 Overture building polygon：
   - 计算其中心点；
   - 若中心点位于任何 OSM building polygon 内部 → **合并属性**
     （只把 OSM 缺失的字段从 Overture 写进去：`height`, `overture:class`,
     `overture:names`, `overture:confidence`, `overture:source`）；
   - 否则 → **新增** 该 building 到输出集，属性里加
     `overture:primary_source="overture_buildings"`。
3. **Places → Building 贴合**：对每个 Overture Place 点：
   - 找到包含该点的 building polygon（优先 OSM，次优先 Overture 已合入的）；
   - 若找到：把该 Place 的 `names.primary`、`categories.primary` 等写入建筑的
     `properties["affordances"]`（列表累积）；若建筑当前 `name` 为空或默认
     `building_NNNN`，同步用 Place 名字覆盖。
   - 若找不到（独立 POI）：以 Place 点为中心构造一个小 polygon（如 8×8m 方块）
     作为"隐式建筑"纳入，标注 `overture:primary_source="overture_places"`。
4. **输出**：FeatureCollection，features 顺序为 `[osm_original..., overture_added_bldgs..., place_stubs...]`。

### 几何匹配用 point-in-polygon，不用面积重叠

理由：Lane Cove 尺度下建筑多为独立 polygon，中心点 in polygon 足够准确；
面积重叠（IoU）在 OSM / Overture 几何精度不一致时容易误判，也更慢。

### 冲突仲裁

| 字段 | 优先源 |
|---|---|
| `name` | OSM（人工编辑权重高） > Overture Places.names.primary > Overture Buildings.names.primary |
| `building_type` 推断输入 | Overture Places.categories.primary > OSM `amenity/shop/building` > Overture Buildings.class |
| `height` / `num_floors` | Overture（纯几何属性，OSM 常缺失） |
| `addr:*` | OSM > G-NAF（暂不接入） |

决策权交给 `importer._infer_building_type`，只需保证其能读到统一的输入字段。

## 文件格式与字段约定

### 合并后 GeoJSON 中一个富化 building feature 示例

```json
{
  "type": "Feature",
  "geometry": { "type": "Polygon", "coordinates": [[...]] },
  "properties": {
    "@id": "way/12345",              // 若来自 OSM
    "@category": "building",
    "building": "yes",
    "name": "Sunrise Café",           // 可能来自 Overture Place
    "amenity": "cafe",                // OSM 原有
    "overture:class": "commercial",
    "overture:height": 6.5,
    "overture:confidence": 0.92,
    "overture:primary_source": "osm",
    "affordances": [                  // conflation 注入
      {
        "activity_type": "buy_coffee",
        "source": "overture_places",
        "category": "eat_and_drink.coffee",
        "name": "Sunrise Café",
        "description": "Coffee shop (Overture)."
      }
    ]
  }
}
```

- `properties.affordances` 是 list；importer 会把它转成 `ActivityAffordance`
  tuple，直接落到 `Building.affordances`。
- `overture:*` 前缀避免污染 OSM 原生命名空间；导入器将它们复制进 `osm_tags`
  方便感知层检索。

## 数据规模与性能

Lane Cove 2066 范围（约 30 km²）的预估：
- Overture Buildings：~6–8K 个 polygon
- Overture Places：~800–1500 POI

合计远小于 Sydney 全局；拉取 + conflation 在本机单次运行 < 30s 可行。

每次 bump Overture 版本，只需重跑 `tools/fetch_overture.py`。

## 与 cartography spec 的对接

本 change 在 `openspec/changes/enrich-lanecove-map/specs/cartography/spec.md`
引入一组 **MODIFIED** / **ADDED** Requirements：

- MODIFIED "GeoJSON 导入主入口" —— importer 需读新增字段。
- ADDED "多源富化流水线" —— 规定 `conflation.merge_sources` 契约。
- ADDED "POI 贴合建筑" —— 规定 Place → Affordance 的映射规则。
- ADDED "富化覆盖率指标" —— 诊断工具新增维度。

## 风险与兜底

- **Overture 停服/格式变**：产物已 commit 到 git，重建时回退到"纯 OSM" 模式
  即可；importer 对 Overture 字段缺失保持可容忍。
- **Place 贴错建筑**：point-in-polygon 可能把"咖啡馆在街边小亭"错贴成隔壁
  residential。conflation 输出 `confidence` 字段，`< 0.5` 的 Place 不贴，
  而是独立为 stub building。
- **许可合规**：Overture 数据同时遵循 ODbL（来自 OSM 部分）与 CDLA-P 2.0
  （来自其它贡献者）。我们的仓库是公开的，需在 README 加 attribution 段落。
