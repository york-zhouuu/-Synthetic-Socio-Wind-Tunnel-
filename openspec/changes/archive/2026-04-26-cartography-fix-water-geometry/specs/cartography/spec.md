## ADDED Requirements

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
