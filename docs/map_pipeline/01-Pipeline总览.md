# 地图构建 Pipeline 总览

## 目标

将真实城市地理数据转换为 synthetic_socio_wind_tunnel 可运行的 Atlas 地图。

**核心原则：**
- 模拟在 building/location 粒度运行，room 细节按需生成
- **道路是可行走的空间**，不只是连接线——agent 会经过街道，能在路上碰到人

---

## 地图的空间模型

地图由三类 location 组成，agent 在它们之间逐步移动：

```
┌──────────────────────────────────────────────────────────────────┐
│                        Region (整个社区)                          │
│                                                                  │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐                  │
│   │ Building │    │ Building │    │ Building │  ← 建筑           │
│   │ (cafe)   │    │ (home)   │    │ (shop)   │    可进入的目的地  │
│   └────┬─────┘    └────┬─────┘    └────┬─────┘                  │
│        │               │               │                        │
│   ─────┴───────────────┴───────────────┴─────  ← 街道段          │
│        Main Street [seg_1] [seg_2] [seg_3]       agent 经过的路径│
│   ───────────────────┬───────────────────────                    │
│                      │                                          │
│              ┌───────┴───────┐                                  │
│              │  OutdoorArea  │  ← 公共空间                       │
│              │   (park)      │    可停留的开放区域                │
│              └───────────────┘                                  │
└──────────────────────────────────────────────────────────────────┘
```

**三类 location：**

| 类型 | 例子 | agent 行为 | Atlas 模型 |
|------|------|-----------|-----------|
| **Building** | 咖啡馆、公寓、图书馆 | 目的地，停留做事 | `Building` |
| **Street Segment** | Main Street 第1段 | 经过，路上可能遇人 | `OutdoorArea(area_type="street")` |
| **Open Space** | 公园、广场、操场 | 停留、社交、活动 | `OutdoorArea(area_type="park/plaza")` |

**Connection 关系：**

```
Building ←→ 最近的 Street Segment (入口连接)
Street Segment ←→ 相邻的 Street Segment (道路延续)
Street Segment ←→ Open Space (公园入口)
Street Segment ←→ 另一条街的 Street Segment (十字路口)
```

**agent 的移动示例：**

```
Emma 从家去咖啡馆:

tick 1: home (Building)
tick 2: elm_street_seg_1 (Street)       ← 出门上街
tick 3: elm_street_seg_2 (Street)       ← 走在路上，这里 Bob 也在！
tick 4: main_street_seg_3 (Street)      ← 转到主街
tick 5: sunrise_cafe (Building)         ← 到达目的地
```

---

## 整体流程

```
┌──────────────────────────────────────────────────────────────┐
│                    Stage 1: OSM 提取                          │
│                                                              │
│  OpenStreetMap GeoJSON 文件                                   │
│       │                                                      │
│       ├─→ 建筑轮廓 (building polygons) → Building             │
│       ├─→ 道路网络 (highway lines) → Street Segments          │
│       ├─→ 公共空间 (leisure/landuse polygons) → OutdoorArea   │
│       ├─→ 建筑语义标签 (amenity, shop, building type)          │
│       └─→ 自动推断 Connection (建筑↔街道↔街道↔建筑)            │
│                                                              │
│  产出: 骨架 Region (建筑 + 街道段 + 公共空间 + 连接)            │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                    Stage 2: LLM 充实                          │
│                                                              │
│  输入: 骨架 Region (只有几何 + OSM 标签)                       │
│                                                              │
│  LLM 做的事:                                                  │
│  ├─→ 为每个建筑生成自然语言描述                                  │
│  ├─→ 推断功能类型 (cafe/residential/library/shop...)           │
│  ├─→ 补充环境氛围 (typical_sounds, typical_smells)              │
│  ├─→ 为街道段生成氛围 (交通声、行人声、沿街商铺气味)              │
│  └─→ [可选] 为重要建筑生成室内布局 (rooms)                       │
│                                                              │
│  产出: 充实后的 Region JSON                                    │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                    Stage 3: 人工审核                           │
│                                                              │
│  审核内容:                                                    │
│  ├─→ 连接关系是否合理 (建筑和哪段街道相连?)                      │
│  ├─→ 街道分段是否合理 (段太长→都在同一location; 太短→tick太多)   │
│  ├─→ 建筑功能是否正确                                          │
│  ├─→ 描述是否自然                                              │
│  └─→ 增删重要地标                                              │
│                                                              │
│  产出: 最终 atlas.json                                        │
└──────────────────────────────────────────────────────────────┘
```

---

## Stage 1: OSM 提取 — 详细设计

### 输入

从 OpenStreetMap 导出的 GeoJSON 文件（.geojson），覆盖目标社区范围。

导出方法：
1. 打开 https://www.openstreetmap.org
2. 导航到目标区域
3. 点击 "Export" → 选择区域 → 下载 `.osm` 文件
4. 用 `osmtogeojson` 工具转为 GeoJSON（`npm install -g osmtogeojson && osmtogeojson input.osm > output.geojson`）

### 解析逻辑

#### 1. 建筑提取（已有，需增强）

现有行为：检测 `building` tag → 创建 Building 对象

需增强：
- 提取 `amenity` tag（cafe, restaurant, library, school, hospital...）
- 提取 `shop` tag（supermarket, bakery, clothes...）
- 提取 `name` tag（优先使用 OSM 中的真实名称）
- 提取 `building:levels` tag（楼层数）
- 将这些信息存入 Building 的新字段 `function_type` 和 `osm_tags`

#### 2. 公共空间提取（已有，需增强）

现有行为：检测 `leisure`/`landuse`/`amenity` → 创建 OutdoorArea

需增强：
- 区分 area_type：park / plaza / playground / garden / parking
- 提取面积信息用于后续判断

#### 3. 道路提取与分段（新增，核心）

**这是最关键的新增功能。** 道路不再只是 Connection 的来源，道路本身就是 agent 可以行走和相遇的空间。

OSM 中道路是 LineString 类型：

```json
{
  "type": "Feature",
  "geometry": {"type": "LineString", "coordinates": [[lon1,lat1], [lon2,lat2], ...]},
  "properties": {"highway": "residential", "name": "Main Street"}
}
```

**处理流程：**

```
原始道路 LineString
    │
    ▼
分段 (每 50-100m 一段)
    │
    ▼
每段生成一个 OutdoorArea(area_type="street")
    │
    ▼
相邻段之间自动创建 Connection
    │
    ▼
检测沿街建筑，创建 Building ↔ 最近街道段的 Connection
```

**道路分段策略：**

```python
def segment_road(road_points: list[Coord], road_name: str,
                 segment_length: float = 80.0) -> list[OutdoorArea]:
    """
    将一条长道路分为多个 OutdoorArea 段。

    segment_length 的选择:
    - 80m ≈ 步行 1 分钟
    - 对应模拟中的 1 tick (5 分钟) 包含约 5 个段
    - 这意味着走一条 400m 的街需要 5 个 tick = 25 分钟模拟时间
    - 如果觉得太慢，可以让 agent 每 tick 移动 2-3 段
    """
```

**分段长度的考量：**

| segment_length | 一条 400m 街的段数 | agent 过街 tick 数 | 路上碰面概率 |
|---------------|-------------------|-------------------|-------------|
| 40m | 10 段 | 10 tick | 高（但地图节点太多） |
| **80m** | **5 段** | **5 tick** | **中（推荐）** |
| 160m | 2-3 段 | 2-3 tick | 低（路上碰面太难） |

**道路宽度（polygon 生成）：**

街道段需要一个 polygon（OutdoorArea 的必填字段）。从 LineString 生成：

```
原始 LineString:  ────────────
生成的 polygon:   ┌──────────┐   (线段两侧各扩展 road_width/2)
                  └──────────┘
```

道路宽度参考：

| highway 类型 | 默认宽度 | 说明 |
|-------------|---------|------|
| footway / path | 2m | 人行小路 |
| residential | 6m | 住宅区道路 |
| service | 4m | 服务道路 |
| secondary | 8m | 次干道 |
| primary | 10m | 主干道 |

#### 4. Connection 自动推断（新增，核心）

Connection 把所有 location 串成可导航的图。分三步：

**Step 4a: 街道段之间的串联**

同一条道路的相邻段自动连接：

```
main_st_seg_1 ←→ main_st_seg_2 ←→ main_st_seg_3
(distance = 段长, path_type = 道路类型)
```

**Step 4b: 十字路口处的连接**

两条道路的端点/中间点距离 < 阈值（如 20m）时，连接对应的段：

```
main_st_seg_5 ←→ oak_ave_seg_3    (十字路口)
```

**Step 4c: 建筑/公共空间 ↔ 最近街道段**

每个 Building 和 OutdoorArea(非 street) 连接到最近的街道段：

```
sunrise_cafe ←→ main_st_seg_3    (distance = 建筑入口到街道的距离)
central_park ←→ elm_st_seg_2     (distance = 公园入口到街道的距离)
central_park ←→ oak_ave_seg_4    (公园可能有多个方向的入口)
```

**如果建筑没有靠近任何街道**（OSM 数据不完整），回退到距离阈值法。

### 产出格式

```python
Region(
    id="my_community",
    name="My Community",
    bounds_min=Coord(x=..., y=...),
    bounds_max=Coord(x=..., y=...),
    buildings={
        "sunrise_cafe": Building(
            id="sunrise_cafe",
            name="Sunrise Café",
            polygon=Polygon(vertices=(...)),
            function_type="cafe",
            osm_tags={"amenity": "cafe", "cuisine": "coffee"},
        ),
        "maple_apartments": Building(..., function_type="residential"),
        ...
    },
    outdoor_areas={
        # 公共空间
        "central_park": OutdoorArea(
            id="central_park", name="Central Park",
            area_type="park", surface="grass", ...
        ),
        # 街道段
        "main_st_seg_1": OutdoorArea(
            id="main_st_seg_1", name="Main Street (1)",
            area_type="street", surface="asphalt",
            osm_tags={"highway": "residential", "name": "Main Street"},
        ),
        "main_st_seg_2": OutdoorArea(..., area_type="street"),
        "main_st_seg_3": OutdoorArea(..., area_type="street"),
        "elm_st_seg_1": OutdoorArea(..., area_type="street"),
        ...
    },
    connections=(
        # 街道段串联
        Connection(from_id="main_st_seg_1", to_id="main_st_seg_2", distance=80.0, path_type="residential"),
        Connection(from_id="main_st_seg_2", to_id="main_st_seg_3", distance=80.0, path_type="residential"),
        # 十字路口
        Connection(from_id="main_st_seg_3", to_id="elm_st_seg_1", distance=15.0, path_type="intersection"),
        # 建筑入口
        Connection(from_id="sunrise_cafe", to_id="main_st_seg_2", distance=10.0, path_type="entrance"),
        Connection(from_id="maple_apartments", to_id="elm_st_seg_1", distance=8.0, path_type="entrance"),
        # 公园入口
        Connection(from_id="central_park", to_id="main_st_seg_3", distance=20.0, path_type="entrance"),
        Connection(from_id="central_park", to_id="elm_st_seg_2", distance=25.0, path_type="entrance"),
        ...
    ),
)
```

---

## Stage 2: LLM 充实 — 详细设计

### 目的

骨架 Region 只有几何和 OSM 标签，对模拟来说信息不够。需要 LLM 来：

1. **生成建筑描述** — agent 感知系统需要自然语言描述
2. **推断环境氛围** — typical_sounds, typical_smells 影响感知滤镜
3. **为街道段生成氛围** — 不同街道有不同的声音和气味（商业街 vs 住宅区）
4. **[可选] 为重要建筑生成室内布局** — 当 agent 需要进入建筑内部时

### 建筑描述生成

输入给 LLM 的 prompt：

```
这是一个社区地图中的建筑。请根据以下信息生成简短的描述。

建筑名称: Sunrise Café
功能类型: cafe
OSM 标签: amenity=cafe, cuisine=coffee
楼层数: 1
建筑材料: brick
附近的地标: Central Park (50m), Maple Apartments (35m)

请生成:
1. 一句话描述 (给 agent 的感知系统用)
2. 3-5 个典型声音 (如 coffee_grinding, chatter, music)
3. 2-3 个典型气味 (如 fresh_coffee, pastry)
4. 这个地方通常在什么时间段活跃 (如 7:00-18:00)
```

### 街道段描述生成

街道段也需要氛围，但可以按整条街批量生成，然后分配到各段：

```
这是社区地图中的一条街道。请根据以下信息生成描述。

街道名称: Main Street
道路类型: residential
沿街建筑: Sunrise Café (cafe), Fresh Mart (supermarket), Maple Apartments (residential)
段数: 5 段

请为这条街整体生成:
1. 白天的典型声音 (如 traffic, pedestrian_chatter, birds)
2. 夜间的典型声音
3. 典型气味 (如果沿街有餐饮)
4. 街道的整体氛围描述
```

### 室内布局按需生成（薛定谔式）

**核心思想：Room 在 agent 第一次进入建筑时才生成。**

这与 synthetic_socio_wind_tunnel 已有的"薛定谔细节"机制完全一致——CollapseService 就是干这个的。

流程：
1. Agent 决定进入 `sunrise_cafe`
2. 系统检查：`sunrise_cafe.rooms` 是否为空？
3. 如果为空 → 调用 LLM 生成室内布局
4. 生成的 rooms 持久化到 Atlas/Ledger 中
5. 后续访问直接使用已生成的数据

---

## Stage 3: 人工审核 — 操作建议

### 审核清单

1. **街道分段**
   - 段是否太长或太短？（推荐 50-100m/段）
   - 同一条街的段是否首尾相连？
   - 十字路口处两条街是否正确连接？

2. **建筑-街道连接**
   - 每个建筑是否连接到了正确的街道段？
   - 同一个建筑有没有连到不相邻的街上（错误）？

3. **可达性**
   - 从任意建筑出发，能否到达其他所有建筑？（图是否连通）
   - 是否有孤立的街道段或建筑？

4. **建筑功能**
   - function_type 是否正确
   - OSM 数据可能过时（已关闭的商店、改了用途的建筑）

5. **描述质量**
   - 是否自然、合理
   - 是否有 hallucination（编造了不存在的细节）

### 工具支持

建议后续开发一个简单的可视化审核工具：
- 在浏览器中渲染所有 location polygon（建筑、街道段、公共空间用不同颜色）
- Connection 线叠加显示
- 点击 location 查看详细信息
- 可以拖拽调整、添加/删除 connection

---

## 选址建议

目标社区特征：

- **相对封闭** — 有明确的地理边界（河流、铁路、主干道等）
- **能自循环** — 有居住、商业、公共空间，居民日常需求可在社区内解决
- **人群分布均匀** — 不是只有一个中心的辐射状布局

**选址时额外检查道路数据：**
- OSM 中道路网络是否完整？（如果只有主干道没有小路，街道段会很稀疏）
- 道路是否有 name 标签？（有名字的街道生成的段 ID 更可读）
- 人行道 (footway/path) 是否标注？（纯步行路径对社交模拟很重要）

---

## 与现有系统的兼容性

**完全兼容，不需要改核心架构。原因：**

街道段就是 `OutdoorArea`（area_type="street"），现有引擎已经完整支持：

- `move_entity("emma", "main_st_seg_2")` — 移动到街道段 ✓
- `NavigationService.find_path("home", "cafe")` — 自动经过中间的街道段 ✓
- `PerceptionPipeline.render(...)` — 在街道段上能看到同段的其他 agent ✓
- 街道段和建筑在代码层面没有区别，都是 location ID

**这意味着：**
- Agent 从家走到咖啡馆，会经过中间的街道段，路上能遇到人
- NavigationService 的 A* 寻路会自动计算经过哪些街道段
- 不需要新增任何运行时代码，只是地图数据更丰富了

## 地图规模预估

以一个典型封闭社区为例：

| 元素 | 数量 | 说明 |
|------|------|------|
| Building | 50-100 | 住宅楼、商铺、公共设施 |
| Street Segment | 100-200 | 10-20 条街 × 每条 5-15 段 |
| Open Space | 5-15 | 公园、广场、操场 |
| Connection | 300-500 | 段串联 + 十字路口 + 建筑入口 |
| **Total locations** | **~200-300** | 足够 1000 agent 分散 |
