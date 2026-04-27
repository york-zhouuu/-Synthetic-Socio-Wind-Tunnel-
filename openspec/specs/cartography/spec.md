# cartography — 地图构建

## Purpose
`cartography` 模块提供两种离线手段把真实世界或设计稿转成 Atlas Region：
1. `GeoJSONImporter` — 从 OpenStreetMap 等 GeoJSON 自动导入；
2. `RegionBuilder` — 程序化 fluent API，便于写单元测试与小规模手造地图。
两者产出的 Region 都 SHALL 满足 atlas 的所有结构与完整性约束。

## Requirements

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

#### Scenario: 导入包含咖啡馆和街道的小块 GeoJSON
- **WHEN** 输入的 GeoJSON 含 `amenity=cafe` 的建筑与一条 200 米长的道路
- **THEN** 返回的 Region SHALL 至少含 1 个 `Building(function_type="cafe")`
  与 ≥2 段 `OutdoorArea(area_type="street")`，两者之间有连接

#### Scenario: 导入富化后的 GeoJSON
- **WHEN** 输入文件中某 building 属性含 `{"name": "Sunrise Café",
  "amenity": "cafe", "affordances": [{"activity_type": "buy_coffee", ...}]}`
- **THEN** 返回的 Region 里该 Building SHALL `name == "Sunrise Café"`，
  `building_type == "cafe"`，`affordances` 至少含一条 `buy_coffee`

#### Scenario: 兼容纯 OSM 输入
- **WHEN** 输入文件为无 `overture:*` 字段与 `affordances` 的纯 OSM 导出
- **THEN** importer SHALL 不报错，产出等价于当前实现的 Region

### Requirement: 道路分段规则
导入器 SHALL 将单条路的几何拆分为长度约 50–100 米的段。

- 拆分阈值 SHALL 可通过配置/参数调整。
- 每一段 SHALL 填入 `segment_index`（从 0 连续递增）与 `road_name`，使同一路的
  段可被还原。
- 相邻段之间 SHALL 自动生成 `Connection(path_type="road")`。

#### Scenario: 一条 300 米的主路
- **WHEN** 导入一条 300 米的单路段
- **THEN** SHALL 产出 3–6 段，`segment_index` 依次递增，相邻段有连接

### Requirement: 建筑到街的接入
任意 `Building` SHALL 至少与其几何最近的一段街道建立
`Connection(path_type="entrance")`。

- 若最近街道距离超过阈值（默认 30 米），导入器 SHOULD 记录警告但仍尝试连接，
  避免产生"孤岛建筑"。

#### Scenario: 孤立建筑警告
- **WHEN** 某建筑周围 30 米内无街道
- **THEN** 导入器 SHALL 仍返回一个连接（到最近街道）并在日志/返回值中标记警告

### Requirement: 交叉口推断
导入器 SHALL 先用 OSM 原始节点精确匹配（两段共享同一 lon/lat 节点），
再做几何邻近回退：任意两段（来自不同 OSM way）的投影端点距离 < 10 米 即视为路口，
生成 `Connection(path_type="intersection")`。

- 精确匹配用原始经纬度的 1e-6 精度（~0.1m）做 key。
- 几何回退 SHALL 使用端点（段多边形两短边的中点），不得用段中心距离。

#### Scenario: OSM 共享节点即路口
- **WHEN** 两段从不同 OSM way 来，但其原始 LineString 共享同一个节点
- **THEN** 两段之间 SHALL 生成一条 `intersection` 连接

#### Scenario: 相邻但未合并节点的 OSM 数据
- **WHEN** 两段端点的投影距离为 7 米（< 10m 阈值）
- **THEN** 两段 SHALL 被连接，即使 OSM 未显式共享节点

### Requirement: 同名多 way 不互相覆盖
导入器 SHALL 按 OSM way 分组维护段序列（非按 road name），
避免同名不同 way（如 "Burns Bay Road" 被拆成多个 way）互相覆盖 adjacency 链。

- 同一 way 内相邻段以 `path_type=<highway>` 连接；
- 不同 way 之间的连接一律交由交叉口推断。

#### Scenario: 同名两 way 互不吞并
- **WHEN** OSM 有两个均名为 "Burns Bay Road" 的 way，各含 5 段
- **THEN** 各自的 4 条 adjacency 连接都应被生成（共 8 条），不会被另一 way 的 5 段覆盖

### Requirement: 建筑入口带距离上限
`_connect_to_street` SHALL 把建筑 / 非街道 outdoor 连到最近街段，且距离
MUST NOT 超过 200 米；超过则放弃连接并保留该位置为"孤岛候选"，方便诊断
工具 surface 而非静默虚假连接。

#### Scenario: 孤岛建筑
- **WHEN** 某建筑最近的街段距离 > 200 米
- **THEN** 导入器 SHALL 不生成 entrance 连接；连通度诊断 SHALL 能看到该建筑孤立

### Requirement: ID 去重
`_make_id(name, prefix)` SHALL 对重复规范化后的 id 追加递增后缀
（如 `house`, `house_1`, `house_2`），保证不同原始实体不会被同 id 覆盖。

#### Scenario: 两个 "House" 同时出现
- **WHEN** GeoJSON 含两个 name="House" 的建筑
- **THEN** 一个 id 为 `house`，另一个 id 为 `house_1`，两个都保留在 `region.buildings`

### Requirement: 真实世界数据的连通度门禁
在测试套件中，SHALL 有一条基于真实 OSM 数据（`data/lanecove_osm.geojson`）的
回归测试：导入后 `buildings in main component / len(buildings) >= 85%`。

- 若门禁回归，说明 importer 的连接推断被破坏，应优先修复。

#### Scenario: importer 回归被测出
- **WHEN** 导入 Lane Cove OSM 后主连通分量建筑占比降到 80%
- **THEN** `tests/test_cartography.py::TestLaneCoveConnectivity` SHALL 失败

### Requirement: 程序化 RegionBuilder
`RegionBuilder` SHALL 提供 fluent API：
- `add_building(id, name, building_type)` 返回建筑子 builder，可进一步
  `.polygon(...)`、`.add_room(...)`、`.add_affordance(...)`、`.end_building()`；
- `add_street(id, name, road_name)` / `add_outdoor(id, name, area_type)`
  返回户外子 builder，可 `.polygon(...)`、`.segment_index(...)`、`.end_outdoor()`；
- `connect(from_id, to_id, path_type, distance)` 添加连接；
- `add_border(border_id, name, border_type)` 返回边界子 builder；
- `build() → Region` 校验并冻结。

#### Scenario: 构建最小可测试 Region
- **WHEN** 用 builder 添加 1 建筑 + 1 街道 + 1 连接后 `build()`
- **THEN** 返回合法的 Region，`Atlas(region)` 初始化不抛错

### Requirement: 构建期完整性校验
`RegionBuilder.build()` 与 `GeoJSONImporter.import_file` 在返回前 SHALL：
- 校验所有 `Connection` 的两端 id 存在；
- 校验容器 `item_capacity` / `surface_capacity` 为非负整数；
- 校验没有孤立的公共建筑（至少一条连接）；
- 若失败 SHALL 抛结构化异常，不返回半合法 Region。

#### Scenario: 悬空连接
- **WHEN** builder 中出现 `connect(from="ghost", to="real")` 其中 `ghost` 未定义
- **THEN** `build()` SHALL 抛异常指明"未定义位置：ghost"

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
Importer SHALL 在 `_extract_building` 中为每个 `building_type == "residential"`
且当前 affordances 为空的建筑追加默认 `ActivityAffordance`，确保 agent 可
枚举到所有住宅（Lane Cove 90% 以上建筑是住宅，若仅靠商业 POI 富化则会
全部漏掉）：

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

### Requirement: Lane Cove 生产入口位于 cartography.lanecove
`synthetic_socio_wind_tunnel.cartography.lanecove` 模块 SHALL 是 Lane Cove
场景代码的唯一生产入口（atlas 加载 / Riverview 合成补齐 / demo 知识地图
构建），暴露以下公共函数：

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


### Requirement: OSM multipolygon relation 正确组装为闭合环

OSM fetch / 处理工具 SHALL 把 multipolygon relation 的 outer way 端点拼接
成闭合环并输出为 GeoJSON Polygon；MUST NOT 仅依赖"每个 outer way 自身已
闭合"的假设——OSM 中大水域（河、湾、海等）的 outer way 普遍是开放分段。

设计意图（见 `cartography-fix-water-geometry` change design D1-D3）：
- Lane Cove River relation 含 74 条 outer way，0 条自闭合 → 当前实现全部
  丢弃 → river polygon 完全消失
- OSM `Relation:multipolygon` wiki 标准算法是逐段端点匹配组成环
- 本要求只规定 outer ring 行为；inner ring（孔洞）暂不要求

具体要求：

1. 处理 `type=multipolygon` relation 时 SHALL 收集所有 `role=outer` 成员 way
   的节点 id 序列；按端点 node_id 匹配（不用 lon/lat 浮点比较）拼接成环
2. 每个闭合环 SHALL 输出为一个 GeoJSON Polygon feature；保留 relation 的
   tags（如 `name`, `natural`, `water` 等）作 properties
3. 拼接过程中如某 chain 找不到下一段且首尾不闭合 SHALL 丢弃该 chain 并
   `logger.warning("unclosed multipolygon outer chain in relation %d", rel_id)`；
   MUST NOT 强行连接首尾
4. `role=inner` 成员 way 在本 change 不组装；后续 cartography-quality change
   补充孔洞支持

#### Scenario: 4 条开放 way 拼成 1 个闭合矩形
- **WHEN** relation 含 4 条 outer way，分别是矩形的 4 条边（共享端点）
- **THEN** assemble 函数 SHALL 返回 1 个闭合环 Polygon，含 5 个顶点（首末
  相同）

#### Scenario: 已闭合的单 way 直接作为环
- **WHEN** relation 只有 1 条 outer way，且该 way 自身首末节点 id 相同（已
  闭合）
- **THEN** SHALL 输出 1 个 Polygon；不需拼接

#### Scenario: 链断裂时 drop 不强行闭环
- **WHEN** relation 的 outer way 缺一段，导致 chain 走到尾找不到下一段
- **THEN** 该 chain SHALL 被丢弃；logger.warning SHALL 含 relation_id；其它
  能闭合的环 SHALL 仍输出

#### Scenario: Lane Cove River 实际数据可装
- **WHEN** fetch_lanecove.py 处理含 Lane Cove River relation 的 Overpass
  响应（74 条 outer way）
- **THEN** 输出的 GeoJSON SHALL 至少含 1 个 water polygon，name 为
  "Lane Cove River"，footprint 面积 > 50000 m²


### Requirement: Map Explorer 过滤地下水道 + 裁切到核心 bbox

`tools/map_explorer/server.py` 加载 OSM 水 features 时 SHALL：(a) 过滤掉
地下涵洞类水道避免视觉穿街；(b) 把水多边形裁切到 Lane Cove 核心 render
bbox，避免 Sydney Harbour / Port Jackson 等大水域（数十 km²）淹没核心
社区视图。

具体要求：

1. SHALL 跳过 `tags["tunnel"] ∈ {"yes", "culvert", "building_passage"}` 的
   waterway
2. SHALL 跳过 `tags["layer"] < 0` 的 waterway（数值解析失败时容忍：不过滤）
3. SHALL 跳过 `tags["covered"] == "yes"` 的 waterway
4. 水多边形（Polygon）SHALL 通过 Sutherland-Hodgman 算法裁切到 render bbox
   （Lane Cove 核心 + 适当 padding）；完全在 bbox 外的多边形 MUST NOT 渲染

#### Scenario: 普通溪流保留
- **WHEN** OSM feature 是 `waterway=stream` 无 tunnel/layer/covered 标签
- **THEN** server SHALL 把它加入 `context_layers["water"]`

#### Scenario: tunnel=culvert 被跳过
- **WHEN** OSM feature 是 `waterway=stream` + `tunnel=culvert`
- **THEN** server MUST NOT 把它加入渲染层

#### Scenario: Sydney Harbour 大水域被裁切
- **WHEN** OSM 水多边形 footprint 远超 render bbox（如 Sydney Harbour 26 km²）
- **THEN** server SHALL 把它裁到 render bbox；保留 bbox 内可见的水边缘
  片段，丢弃外部部分

#### Scenario: 完全在 bbox 外的水域被丢弃
- **WHEN** OSM 水多边形完全在 render bbox 外（如远海湾）
- **THEN** server MUST NOT 把它加入渲染层
