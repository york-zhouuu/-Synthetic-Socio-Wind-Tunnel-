# atlas — 静态地理布景

## Purpose
Atlas 是 CQRS 架构中的"查询侧只读层"，承载城市的不可变几何与语义：
建筑、房间、户外空间（含路段）、连接图、边界区。它是所有 agent 共享的
客观物理世界，不含任何动态状态。

## Requirements

### Requirement: Region 为不可变聚合根
Atlas SHALL 以 `atlas.models.Region` 作为聚合根，包含：
`id`、`name`、`bounds_min/max`、`buildings: dict[str, Building]`、
`outdoor_areas: dict[str, OutdoorArea]`、`connections: tuple[Connection, ...]`、
`doors: dict[str, DoorDef]`、`borders: dict[str, BorderZone]`。

- Region 及其嵌套结构 SHALL 在构造后不可修改（frozen），可安全并发读取。
- `atlas.service.Atlas` 服务 SHALL 只暴露只读方法，不提供任何写操作。

#### Scenario: 运行期并发读取
- **WHEN** 多个 agent 并发调用 `Atlas.get_building(id)`
- **THEN** SHALL 返回一致的不可变对象，无锁竞争

### Requirement: 建筑与房间模型
`Building` SHALL 包含 `id`、`name`、`polygon`、`function_type`（cafe / residential /
library / shop / ...）、`rooms`、`affordances`、`entry_signals`、`osm_tags`。
`Room` SHALL 包含 `id`、`name`、`polygon`、`containers`、`affordances`、
`typical_sounds`、`typical_smells`。

- 建筑的 `entry_signals` SHALL 描述从街道可观察到的外部信号
  （`visible_from_street`、`signage`、`price_visible`、`facade_description`），
  供感知层在"未进入"状态下生成外观描述。
- 房间的 `typical_sounds` / `typical_smells` SHALL 作为听觉 / 嗅觉滤镜的素材来源。

#### Scenario: 咖啡馆的外观可观察性
- **WHEN** 观察者站在一条与咖啡馆连通的街道段
- **THEN** Atlas.get_building 返回的 `entry_signals` SHALL 为感知层
  提供"玻璃门"、"挂牌"、"价目表可见"等字段

### Requirement: 街道作为可导航 OutdoorArea
`OutdoorArea` SHALL 包含 `id`、`name`、`polygon`、`area_type`
（street / park / plaza / playground 等）、`surface`、`affordances`、
`entry_signals`、`segment_index`、`road_name`。

- 当 `area_type == "street"` 时，该 OutdoorArea SHALL 为可导航位置，
  `segment_index` 与 `road_name` 标识同一道路的分段顺序。
- agent 走过的每一段街道 SHALL 是一次独立的位置访问事件，
  使得"路上相遇"成为可能。

#### Scenario: 长路分段
- **WHEN** cartography 导入一条长于 100 米的道路
- **THEN** Atlas SHALL 见到多段 `OutdoorArea(area_type="street",
  road_name="...")`，相邻 `segment_index` 之间有 `Connection`

### Requirement: 连接图完整性
`Connection` SHALL 包含 `from_id`、`to_id`、`distance`、`path_type`
（entrance / path / road / intersection / door / stairs）、`bidirectional`。
门的开闭/锁状态由 `atlas.models.DoorDef` 定义静态属性、由
`ledger.models.DoorState` 维护动态状态，**不在 Connection 上**。

- Atlas 加载时 SHALL 校验每条连接的两端 id 存在于 `buildings` 或
  `outdoor_areas` 中；否则应拒绝加载。
- 所有对外开放的建筑 SHALL 至少有一条 `Connection` 连向其外部的
  OutdoorArea（街道、广场等）。

#### Scenario: 孤立建筑被拒绝
- **WHEN** Region 构造时出现没有任何外部连接的建筑
- **THEN** Atlas 初始化 SHALL 报错，提示哪座建筑孤立

### Requirement: 活动承受性（Affordance）作为事实而非判断
`ActivityAffordance` SHALL 使用可观察字段：`activity_type`、`time_range`、
`capacity`、`requires`、`language_of_service`、`description`。

- affordance 内 MUST NOT 包含数值评分类字段（如 comfort_score、noise_level 数字）。
- 仅记录"可以做什么、什么时间、需要什么"，由感知层与 agent 的 LLM 负责主观判断。

#### Scenario: 图书馆阅览承受性
- **WHEN** 查询图书馆的 affordances
- **THEN** 返回一条 `activity_type="reading"`、`time_range="08:00-20:00"`、
  `capacity=50` 的记录，但不含任何"安静度打分"

### Requirement: 路径查询与空间索引
`Atlas.find_path(from_id, to_id)` SHALL 基于连接图返回可达性，
`find_locations_within_radius(center, radius)` SHALL 支持半径查询。

- 本层返回的 path 仅基于静态拓扑；动态门锁、阻塞由 navigation/engine 层叠加。

#### Scenario: 纯静态最短路径
- **WHEN** 调用 `Atlas.find_path("cafe_a", "park_b")`
- **THEN** SHALL 返回以 id 列表表示的连通序列，或在不连通时返回空结果

### Requirement: 边界区（BorderZone）
`BorderZone` SHALL 包含 `border_id`、`border_type`
（`PHYSICAL` / `SOCIAL` / `INFORMATIONAL`）、`side_a`、`side_b`、`permeability`
（取值 0–1）。

- 边界具有方向性：`side_a → side_b` 与 `side_b → side_a` 的渗透可在上层按需区分。
- 边界不改变静态连通性；但上层（perception / simulation）SHOULD 据 `permeability`
  调整信息与 entity 的流动。

#### Scenario: 查询跨边界事实
- **WHEN** 调用 `Atlas.has_border_crossing(loc_a, loc_b)`
- **THEN** SHALL 返回 `True` 当且仅当两地分属某 BorderZone 的两侧集合

### Requirement: 容器定义与空间预算
`ContainerDef` SHALL 包含 `container_id`、`name`、`container_type`、
`item_capacity`、`surface_capacity`、`can_lock`、`search_difficulty`。

- Atlas 仅定义容量上限；运行时占用量由 ledger 维护。
- ledger / collapse 在放入物品时 SHALL 依据 Atlas 的容量做预算约束。

#### Scenario: 容量上限不可越界
- **WHEN** collapse 尝试向某 Atlas 容器注入物品使其超过 `item_capacity`
- **THEN** 操作 SHALL 失败，并返回对应错误码
