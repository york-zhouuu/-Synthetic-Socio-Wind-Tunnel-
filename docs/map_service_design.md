# 地图服务设计文档：从真实街区到社交推演

> 本文档说明当前地图服务的完整设计，以及它如何支撑项目 Brief 中的核心研究问题。

---

## 一、地图服务在项目中的位置

项目 Brief 的核心命题是：

> **物理距离前所未有的近，社会距离前所未有的远。**

地图服务的职责是：把这句话变成一个**可计算的空间结构**——让 Agent 可以在其中行走、相遇、被边界阻隔、被干预打通。

```
真实城市 (Zetland)          地图服务                    模拟实验
─────────────────    ───────────────────    ──────────────────────
OSM GeoJSON 数据  →  GeoJSONImporter
                     │
                     ▼
                     Region (静态数据)
                     │ buildings
                     │ outdoor_areas
                     │ connections
                     │ borders        →    Atlas (只读查询)
                                           │
                                           ├→ Agent 寻路
                                           ├→ Agent 感知周围环境
                                           ├→ 干预系统判断作用范围
                                           └→ 指标系统计算轨迹偏离
```

---

## 二、空间模型：三类 Location

地图中的世界由三类可停留的空间组成。Agent 不是在坐标系里连续移动的——而是在**离散的 location 之间逐步跳转**，每个 tick 移动一步。

### 2.1 Building（建筑）

Agent 的目的地。具有功能类型（`building_type`），决定 Agent 会不会去、什么时候去。

```python
Building(
    id="sunrise_cafe",
    name="Sunrise Café",
    building_type="cafe",          # ← Agent 规划日程时用这个决策
    osm_tags={"amenity": "cafe"},  # ← 从 OSM 提取的原始标签
    active_hours=(7, 22),          # ← 营业时间
    polygon=...,                   # ← 几何轮廓
    rooms={},                      # ← 室内布局，首次进入时按需生成
)
```

**与 Brief 的关系**：Building 是"第三空间"（Third Places）的载体——咖啡馆、酒吧、社区中心。Brief 中"数字诱饵实验"要把 Agent 引向这些地方。

### 2.2 OutdoorArea — Street Segment（街道段）

Agent 行走的路径。这是本次重构的核心创新：**道路不是抽象的连接线，而是 Agent 可以停留、可以碰到人的空间**。

```python
OutdoorArea(
    id="main_st_seg_3",
    name="Main Street (3)",
    area_type="street",            # ← 标记为街道段
    road_name="Main Street",       # ← 所属道路
    segment_index=2,               # ← 在道路中的顺序
    surface="asphalt",
    polygon=...,                   # ← 道路线段向两侧扩展生成的矩形
)
```

一条 400m 的街被切成 ~5 段（每段 80m ≈ 步行 1 分钟）。Agent 从家走到咖啡馆，必须经过中间的街道段：

```
tick 1: home (Building)
tick 2: elm_st_seg_1 (Street)          ← 出门上街
tick 3: elm_st_seg_2 (Street)          ← 走在路上，这里 Bob 也在！偶遇！
tick 4: main_st_seg_3 (Street)         ← 转到主街
tick 5: sunrise_cafe (Building)        ← 到达目的地
```

**与 Brief 的关系**：街道段是"偶遇"（Serendipity）发生的场所。Brief 说"公共空间沦为降噪耳机走廊"——在模拟中，街道段上的相遇事件就是度量"偶遇"是否回归的指标。

### 2.3 OutdoorArea — Open Space（开放空间）

公园、广场、操场。Agent 可以主动前往并停留。

```python
OutdoorArea(
    id="central_park",
    name="Central Park",
    area_type="park",              # ← 区分于 street
    surface="grass",
    vegetation_density=0.5,
)
```

**与 Brief 的关系**：开放空间是"空间激活"指标的核心——干预前可能是死水（无人停留），干预后可能变成社交热点。

---

## 三、Connection（连接）：Agent 怎么走

Location 之间的路由关系。Agent 不能在任意两个 Location 之间瞬移——必须沿着 Connection 图逐步移动。

```python
Connection(from_id, to_id, path_type, distance, bidirectional)
```

四种 `path_type`：

| path_type | 含义 | 例子 |
|-----------|------|------|
| `entrance` | 建筑/公共空间 ↔ 最近的街道段 | cafe ↔ main_st_seg_3 |
| `residential` / `primary` / ... | 同一条路的相邻段 | seg_1 ↔ seg_2 |
| `intersection` | 两条路的交叉口 | main_st_seg_5 ↔ oak_ave_seg_3 |
| `path` | 通用连接 | park ↔ seg_2 |

### 一个完整的连接图长什么样

```
                    [Apartments]
                         │ entrance
                         ▼
[Café] ──entrance── [Main St seg1] ──road── [Main St seg2] ──road── [Main St seg3]
                                                  │ intersection
                                                  ▼
                                         [Oak Ave seg1] ──road── [Oak Ave seg2]
                                                                       │ entrance
                                                                       ▼
                                                                   [Park]
```

Agent 从 Apartments 去 Park，NavigationService 用 A* 找到最短路径：
`Apartments → Main St seg1 → Main St seg2 → Oak Ave seg1 → Oak Ave seg2 → Park`

每步一个 tick（5 分钟模拟时间），走完这条路需要 5 tick = 25 分钟。路上每经过一个 seg，都有机会遇到其他 Agent。

**GeoJSONImporter 自动推断连接**：导入 OSM 数据时，Importer 会：
1. 同一条路的相邻段自动串联
2. 两条路的端点距离 < 30m 自动标记为十字路口
3. 每个建筑/开放空间自动连接到最近的街道段

---

## 四、BorderZone（边界）：Brief 的核心研究对象

> **Thesis 位置说明**（2026-04-21 由 `thesis-focus` change 收敛）：
> `BorderZone` 是**空间层面**的边界建模，属于 `spatial-output` 层的
> 基础数据结构，**不等于 thesis 的主边界**。v2 thesis 的主边界是
> `attention-main`（注意力位移造成的附近性盲区），见
> `docs/agent_system/00-thesis.md`。以下"四重边界"为 Brief v1 遗留的
> 表述；`BorderZone` 的 `BorderType` 枚举仍然用于地图标注，但不再是
> 并列 thesis 研究对象。

Brief v1 定义了四重边界（注意力、算法、通勤、心理，现已在 `thesis-focus`
中收敛为"一主三机制链"）。在地图层，这些边界被建模为 `BorderZone`：

```python
BorderZone(
    border_id="railway_divide",
    name="Railway Divide",
    border_type=BorderType.PHYSICAL,   # PHYSICAL / SOCIAL / INFORMATIONAL
    side_a=("block_a_seg_1", "block_a_seg_2", "apartments_north"),
    side_b=("block_b_seg_1", "shop_south", "park"),
    permeability=0.2,                  # 0=完全隔绝, 1=完全开放
    crossing_connections=("underpass",),
    description="铁路线将北区和南区分隔开来",
)
```

### 边界的三个维度

| BorderType | Brief 中的对应 | 在模型中的效果 |
|------------|---------------|---------------|
| `PHYSICAL` | 墙/围栏/铁路/封闭的门 | `permeability` 影响 Agent 是否选择穿越 |
| `SOCIAL` | 阶层/文化/社区规约 | Agent 的 Planner 根据 `permeability` 降低穿越意愿 |
| `INFORMATIONAL` | 信息茧房/注意力黑洞 | 影响 Agent 是否感知到边界另一侧的事件 |

### 边界查询 API

```python
# 两个 Agent 是否被边界分隔？
atlas.get_border_between_locations("apartments_north", "shop_south")
# → BorderZone(border_id="railway_divide", ...)

# Agent 在边界的哪一侧？
atlas.get_border_side("railway_divide", "apartments_north")
# → "a"

# 两个 location 是否在同侧？
atlas.locations_on_same_side("railway_divide", "loc_1", "loc_2")
# → True / False
```

**这些查询直接服务于实验指标**：对照组和实验组可以按"边界的哪一侧"自然分组，而不是手工指定 agent ID 列表。

---

## 五、动态层：Ledger 中的运行时变化

Atlas 是冻结的（`frozen=True`）——但实验需要在运行时修改地图。这通过 Ledger 实现：

### 5.1 DynamicConnection（动态连接）

Space Unlock 实验的核心机制：在运行时添加一条原本不存在的连接。

```python
# 实验第 4 天，打开围墙上的小门
ledger.add_dynamic_connection(
    connection_id="wall_gate",
    from_id="block_a_seg_2",
    to_id="block_b_seg_1",
    path_type="path",
    distance=5.0,
    description="围墙上新开了一扇小门",
    tick=day4_tick,
)
```

NavigationService 在计算路径时，需要同时查看 Atlas 的静态连接和 Ledger 的动态连接。

### 5.2 BorderOverride（边界渗透性覆盖）

在运行时动态改变边界的渗透性：

```python
# 干预：把铁路隔断的渗透性从 0.2 提高到 0.8
ledger.set_border_permeability(
    border_id="railway_divide",
    permeability=0.8,
    tick=day4_tick,
    reason="Space Unlock experiment: opened underpass",
)
```

---

## 六、三个实验如何使用地图服务

### 实验 1：数字诱饵（Digital Lure）

```
用到的地图能力：
├── atlas.locations_within_radius(center, 500)   ← 找到推送范围内的所有 location
├── atlas.get_building("sunset_bar")              ← 获取目标地点信息
├── atlas.find_path(agent_loc, "sunset_bar")      ← 计算 Agent 到酒吧的路径
└── 指标：对比 Agent 轨迹经过的 street segments 变化
```

推送信息"距离你 50 米的酒吧今晚有试饮"→ Agent 的 Planner 用 `find_path` 评估距离 → 决定是否偏离原计划 → **轨迹偏离度**就是核心指标。

### 实验 2：空间解锁（Space Unlock）

```
用到的地图能力：
├── atlas.get_border("railway_divide")            ← 获取边界信息
├── atlas.get_border_side(border, agent_loc)      ← 判断 Agent 在哪一侧
├── ledger.add_dynamic_connection(...)            ← 运行时开门
├── ledger.set_border_permeability(...)           ← 降低边界阻隔
└── 指标：对比 side_a 和 side_b 的 Agent 交互频率变化
```

A/B 两区的 Agent 原本因为没有连接（或连接距离极大）而无法相遇。干预后新增连接，Agent 发现新路径，开始穿越。

### 实验 3：共同感知（Shared Perception）

```
用到的地图能力：
├── atlas.list_street_segments()                  ← 获取所有街道段（搜索区域）
├── atlas.get_building_info(loc)                  ← Agent 检查建筑时获取信息
├── atlas.locations_within_radius_of(loc, 100)    ← 找寻猫的搜索范围
└── 指标：原本无交集的 Agent 是否在同一 location 停留
```

被赋予"找猫"任务的 Agent 会偏离通勤轨迹，前往公园、后巷等平时不去的地方。如果多个 Agent 同时出现在同一个 street segment 或 open space，就触发社交事件。

---

## 七、地图构建流程

### 方式 A：从 OSM 导入真实地图

```python
from synthetic_socio_wind_tunnel.cartography.importer import GeoJSONImporter

importer = GeoJSONImporter()
region = importer.import_file(
    "zetland.geojson",
    region_id="zetland",
    segment_length=80.0,    # 街道段长度（米）
)

# 产出一个包含以下内容的 Region：
# - 建筑（自动识别 cafe/residential/shop 等类型）
# - 街道段（道路被切分为 80m 一段的 OutdoorArea）
# - 开放空间（公园/广场）
# - 连接图（自动推断：建筑↔街道、街道↔街道、十字路口）
```

三阶段流程：

```
Stage 1: OSM 提取           Stage 2: LLM 充实（待实现）    Stage 3: 人工审核
─────────────────           ──────────────────────        ─────────────
GeoJSON → Region            为建筑生成描述                 检查连接合理性
自动推断连接                  为街道生成氛围                 修正功能类型
提取 building_type           按需生成室内布局               增删地标
提取 area_type                                            标注边界
```

### 方式 B：编程式构建（用于测试/小规模场景）

```python
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.atlas.models import BorderType

region = (
    RegionBuilder("zetland_block", "Zetland Block A")

    # 建筑
    .add_building("apt_north", "North Apartments", building_type="residential")
        .polygon([(0, 20), (15, 20), (15, 35), (0, 35)])
        .end_building()
    .add_building("cafe", "Corner Café", building_type="cafe")
        .polygon([(20, 20), (28, 20), (28, 28), (20, 28)])
        .active_hours(7, 22)
        .end_building()

    # 街道
    .add_street("main_seg_1", "Main St (1)", road_name="Main Street")
        .polygon([(0, 14), (20, 14), (20, 20), (0, 20)])
        .segment_index(0)
        .end_outdoor()
    .add_street("main_seg_2", "Main St (2)", road_name="Main Street")
        .polygon([(20, 14), (40, 14), (40, 20), (20, 20)])
        .segment_index(1)
        .end_outdoor()

    # 南区建筑
    .add_building("apt_south", "South Apartments", building_type="residential")
        .polygon([(0, 0), (15, 0), (15, 10), (0, 10)])
        .end_building()

    # 连接
    .connect("apt_north", "main_seg_1", "entrance")
    .connect("cafe", "main_seg_2", "entrance")
    .connect("main_seg_1", "main_seg_2", "residential")
    .connect("apt_south", "main_seg_1", "entrance")

    # 边界：北区 vs 南区（铁路）
    .add_border("railway", "Railway Line", BorderType.PHYSICAL)
        .border_sides(
            ["apt_north", "cafe", "main_seg_1", "main_seg_2"],  # 北侧
            ["apt_south"],                                       # 南侧
        )
        .border_permeability(0.1)
        .border_description("铁路线将南北两个居民区隔开")
        .end_border()

    .build()
)
```

---

## 八、地图规模参考

以 Zetland 一个典型封闭社区为例：

| 元素 | 数量 | 说明 |
|------|------|------|
| Building | 50–100 | 公寓楼、商铺、公共设施 |
| Street Segment | 100–200 | 10–20 条街 × 每条 5–15 段 |
| Open Space | 5–15 | 公园、广场、操场 |
| Connection | 300–500 | 段串联 + 十字路口 + 建筑入口 |
| Border | 2–5 | 铁路/主干道/社区规约 |
| **Total locations** | **~200–300** | 足够 1000 Agent 分散 |

---

## 九、关键 API 速查

### Atlas（只读查询）

```python
# 位置查询
atlas.get_building(id) → Building | None
atlas.get_outdoor_area(id) → OutdoorArea | None
atlas.get_location(id) → Building | Room | OutdoorArea | None

# 类型查询
atlas.list_buildings_by_type("cafe") → [Building, ...]
atlas.list_street_segments() → [OutdoorArea, ...]
atlas.list_open_spaces() → [OutdoorArea, ...]
atlas.list_road_names() → ["Main Street", "Oak Avenue", ...]

# 空间查询
atlas.locations_within_radius(center_coord, 500.0) → [(id, dist), ...]
atlas.locations_within_radius_of(location_id, 500.0) → [(id, dist), ...]
atlas.find_path(from_id, to_id) → (success, [path], distance)

# 边界查询
atlas.get_border(border_id) → BorderZone | None
atlas.get_border_between_locations(loc_a, loc_b) → BorderZone | None
atlas.get_border_side(border_id, location_id) → "a" | "b" | None
atlas.locations_on_same_side(border_id, loc_a, loc_b) → bool | None

# 层级信息（给 Agent 的 LLM 用）
atlas.get_building_info(id) → dict    # Agent 到达建筑时调用
atlas.get_room_info(id) → dict        # Agent 进入房间时调用
atlas.get_region_overview() → dict     # Agent 初始化时调用
```

### Ledger（运行时变更）

```python
# 动态连接（Space Unlock）
ledger.add_dynamic_connection(id, from_id, to_id, ...)
ledger.remove_dynamic_connection(id)

# 边界覆盖
ledger.set_border_permeability(border_id, new_permeability)
ledger.get_border_permeability(border_id) → float | None
ledger.clear_border_override(border_id)
```

---

## 十、当前状态 & 待完成项

| 组件 | 状态 | 备注 |
|------|------|------|
| Atlas Models | ✅ 完成 | Building/OutdoorArea/Connection/BorderZone |
| Atlas Service | ✅ 完成 | 位置/类型/空间/边界查询 |
| GeoJSONImporter | ✅ 完成 | 建筑+道路+连接推断 |
| RegionBuilder | ✅ 完成 | 编程式构建，含边界 |
| Ledger 动态连接 | ✅ 完成 | DynamicConnection + BorderOverride |
| NavigationService 集成动态连接 | ⬜ 待做 | 目前只读 Atlas 连接，需合并 Ledger 动态连接 |
| LLM 地图充实（Stage 2） | ⬜ 待做 | 为建筑/街道生成描述和氛围 |
| 真实场地 GeoJSON 导入验证 | ⬜ 待做 | 用 Zetland 数据跑一遍 pipeline |
| 可视化审核工具 | ⬜ 待做 | 浏览器中渲染 polygon + connection |
