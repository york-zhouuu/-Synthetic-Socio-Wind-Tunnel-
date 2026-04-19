# Change: enrich-lanecove-map

## Why

当前 Lane Cove 地图由单一 OSM Overpass 查询生成：
- 仅 3386 个 building 多边形，且多数为 `name="building_NNNN"` 的匿名框，
  连同 1176 个 `mock_map._infill_riverview` 合成的 `rv_*` 住宅，感知上"看不见"
  真正有身份的城市肌理（商铺、机构、设施的名字和类型）。
- OSM 节点化的 amenity/shop tags 虽然存在，但多为 node（门牌级点位），
  并没有绑定到具体建筑 polygon；感知层拿到的建筑本质上是几何 + 几个稀疏 OSM tags。
- 实验需要的是"咖啡馆 / 图书馆 / 社区中心 / 托儿所"等可被 agent 识别和叙事
  引用的场所。当前数据支持不了"Emma 走进 Sunrise Café，看到三位熟客"这类
  基础场景。

真实世界数据层（可免费开源使用）能大幅改善：

| 数据源 | 覆盖 Lane Cove 吗 | 我们需要的字段 | 许可 |
|---|---|---|---|
| **Overture Maps Buildings** | ✅ 全球含 Sydney | polygon, class, names, height | CDLA-P 2.0 / ODbL |
| **Overture Maps Places** | ✅ 全球 64M POI | point, names, categories, phone, socials, confidence | CDLA-P 2.0 |
| **Microsoft Global ML Building Footprints** | ✅ 11M+ AU | polygon（ML 推断）| CDLA-P 2.0 |
| **G-NAF（Geoscape）** | ✅ AU 全量 15.9M 地址 | 街道地址 → 坐标 | 开放 EULA |
| NSW Geoscape Buildings | NSW 政府限定 | 屋顶材质、高度、属性 | 仅限政府 |

核心动作：引入 **Overture Maps** 作为 Buildings + Places 主富化层，
必要时用 **Microsoft Footprints** 做几何缺口回填、**G-NAF** 做地址点补齐，
在导入 Atlas 前通过 conflation（几何关联 + 属性合并）把多源数据合成
一份"富化 GeoJSON"。

## What Changes

### 新增能力

1. **多源采集脚本** `tools/fetch_overture.py`
   - 用 `overturemaps` CLI 以 Lane Cove bbox 拉取 `building` + `place` 主题
   - 输出 GeoJSON 到 `data/overture_buildings.geojson`、`data/overture_places.geojson`

2. **多源 conflation** `synthetic_socio_wind_tunnel/cartography/conflation.py`
   - 规则 1（OSM-first 保名）：OSM 有 polygon 且含有语义 tag → 保留，用 Overture 补 height/class/confidence
   - 规则 2（Overture 填白）：OSM 无、Overture 有的 building polygon → 纳入
   - 规则 3（Place 贴 polygon）：Overture Place 点落在某 building 内 → 作为"入驻"实体附加到建筑的 `affordances` / `entry_signals` / osm_tags.name
   - 规则 4（多 Place 同建筑）：一个建筑多 POI → 保留为多条 affordance（餐厅 + 理发店共一栋）
   - 输出：单个合并后的 GeoJSON，供现有 `GeoJSONImporter` 消费

3. **数据缓存与版本化**
   - `data/sources/` 存放各原始源快照（带时间戳）
   - `data/lanecove_enriched.geojson` 为合并产物，commit 到 git（与 osm 快照并列）
   - `data/lanecove_atlas.json` 改由 enriched 版本再跑 importer 生成

4. **诊断脚本扩展** `tools/diagnose_atlas.py` 增加：
   - named vs anonymous building 占比
   - POI/affordance 覆盖建筑数
   - building_type 分布

### 修改能力

- `cartography/importer.py`：
  - `_extract_building` 读取更丰富的 OSM tags（含合并来的 Overture 字段：
    `height`、`overture:class`、`overture:names`、`overture:source`）。
  - 若输入 feature 含 `affordances`（来自 conflation），直接写入 Building.affordances。

- `map_explorer/mock_map.py`：`create_atlas_from_osm` 改读
  `data/lanecove_enriched.geojson`（若存在），否则退回纯 OSM。

## Non-goals

- **不**引入 NSW Geoscape 政府专供数据（非公开，合规风险）。
- **不**调用 Google Places / Mapbox / Foursquare 等**有限免费额度**的商业 API
  （无法复现 + 成本不稳定）。
- **不**实现 LLM 富化（给 affordance 打叙事）—— 这是后续 `collapse` 能力的事。
- **不**改变 Atlas 的 CQRS 形态；富化仅在"导入之前"一次性发生。
- **不**为普通 agent 引入地址级 G-NAF 解析（只在需要家庭住址时按需用）。
- **不**改变现有的连通度算法；本 change 只关心"有什么"，不改"如何相连"。

## Impact

### 受影响模块

- `tools/` — 新增 `fetch_overture.py`；`diagnose_atlas.py` 扩展。
- `synthetic_socio_wind_tunnel/cartography/` — 新增 `conflation.py`；`importer.py`
  扩展字段读取。
- `tools/map_explorer/mock_map.py` — 切换数据入口。
- `data/` — 新增 Overture 原始快照 + 合并产物；更新 `lanecove_atlas.json`。

### 预期效果（实验假设）

- 具名建筑 `share-with-name` 从 **~6%** → **≥60%**（通过 Overture Places 贴 polygon）。
- 建筑 `building_type` 非 "residential" 默认值的比例 从当前 OSM-only ≤ **5%**
  → **≥25%**（Overture 的 class/category 更丰富）。
- 连通度门禁（test_building_main_component_share ≥ 85%）**不回归**。
- `tests/test_cartography.py` 中新增两条富化相关测试：
  - POI 点落入 building 后成为 affordance 的基本契约
  - OSM 有语义 tag 的 building 不被 Overture 覆盖名字

### 依赖变化

- 新增 Python 依赖：`overturemaps`（PyPI 上的官方 CLI），用于抓取 Overture；
  使用 `uvx overturemaps` 即可避免长期依赖。
- conflation 代码零外部依赖（纯 Python + 已有 `shapely` 或手写几何判定）。

### 回滚策略

- 合并产物是可重放的：只需删除 `data/lanecove_enriched.geojson` + 重跑 fetch。
- 原始 OSM 快照 `data/lanecove_osm.geojson` 不删，确保可回退到"纯 OSM" 模式。

## 参考

- [Overture Maps Python CLI 文档](https://docs.overturemaps.org/getting-data/overturemaps-py/)
- [Overture Buildings Guide](https://docs.overturemaps.org/guides/buildings/)
- [Overture Places Guide](https://docs.overturemaps.org/guides/places/)
- [Microsoft Global ML Building Footprints](https://github.com/microsoft/GlobalMLBuildingFootprints)
- [Microsoft AustraliaBuildingFootprints](https://github.com/microsoft/AustraliaBuildingFootprints)
- [Geoscape G-NAF (data.gov.au)](https://data.gov.au/data/dataset/geocoded-national-address-file-g-naf)
