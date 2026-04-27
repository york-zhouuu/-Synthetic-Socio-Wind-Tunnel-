## Context

2026-04-26 用户在 Map Explorer 里发现两个水面问题（Lane Cove River 大水道完全
不可见 + 小溪穿街）。Overpass API 直接核查证实：

- Lane Cove River relation 含 74 条 outer way，**0 条自闭合**——按 OSM 多边形
  约定，需要按端点拼接成闭合环
- `fetch_lanecove.py:270` 处的代码 `if not way_is_closed(coords): continue`
  把 74 条全 drop 了

OSM 多边形组装是个标准算法（Wiki: Relation:multipolygon）；本 change 实现"够
用版"覆盖 atlas 实际用到的水域。

## Goals / Non-Goals

**Goals**：
- Lane Cove River、Sydney Harbour 等大水域 multipolygon 正确组装为闭合 polygon
- Map Explorer 渲染时跳过 `tunnel=yes` / `layer<0` 的水道（不再穿街）
- fetch 脚本的 ring assembly 是确定性的（同样 OSM 输入产同样 GeoJSON）

**Non-Goals**：
- 不实现 OSM 通用 multipolygon 全功能（不处理 self-intersecting / multi-ring
  outer / 退化 case）；只覆盖本 atlas 用到的水
- 不引入 shapely / osmium / pyrosm 等大依赖（手写够用）
- 不重做 inner ring（孔洞）的 polygon-with-holes 表示——hole 数据先 drop，
  视觉上河中岛屿被填满（atlas 里影响可接受；以后 cartography-quality change
  里再补）
- 不调整水的视觉样式（蓝色深浅、stream 粗细等渲染美术决策）

## Decisions

### D1：Ring assembly 算法选 "贪心端点匹配"

**选择**：从 unvisited outer ways 池里随便拿一条做种子，把它的最后一个端点拿
出来；找池中以这个端点开头或结尾的下一条 way；接上（如果是结尾匹配则反转
该 way 顺序）；重复，直到回到种子起点（环闭合）或池空（开放链丢弃）。

**伪代码**：
```python
def assemble_rings(outer_way_coords: list[list[Coord]]) -> list[list[Coord]]:
    pool = list(outer_way_coords)
    rings = []
    while pool:
        chain = list(pool.pop(0))
        while True:
            tail = chain[-1]
            # find next way that starts or ends at tail
            for i, w in enumerate(pool):
                if w[0] == tail:
                    chain.extend(w[1:])
                    pool.pop(i); break
                if w[-1] == tail:
                    chain.extend(reversed(w[:-1]))
                    pool.pop(i); break
            else:
                break  # no continuation found; abandon partial chain
            if chain[0] == chain[-1]:
                rings.append(chain); break
    return rings
```

**Rationale**：OSM 多边形 wiki 算法本身就是这个；O(n²) 对 ~100 条 way 完全够
用。不需要复杂数据结构。

**端点匹配用 node_id 不用 (lon, lat)**：Overpass 返回的 way 是 node id 列表；
在投影 / round-trip 后 (lon, lat) 浮点比较有 epsilon 风险。直接比 node id
更稳。

### D2：开放链（unmatched outer ways）丢弃 + 警告

**选择**：如果某条 chain 走到尾找不到下一段且首尾不闭合 → 丢弃 + log warning。

**Rationale**：OSM 偶尔有数据错误（缺一段 way）；丢弃比错误闭合（强行连首尾）
安全。warning 让维护者发现数据问题。

### D3：Inner ring（孔洞）暂时丢弃

**选择**：只组装 `role=outer`；`role=inner` 跳过。

**Rationale**：
- Lane Cove 区域看了一遍：Lane Cove River relation 0 个 inner，Sydney Harbour
  也是。少量 inner 是远海岛，不在 atlas bbox 内。
- atlas 的 Polygon 模型不支持孔洞（vertices 只有一个 list）
- 强行实现需要扩 Polygon 模型 → 改契约 → 不在本 change 范围

如果未来某个 atlas 的水域有重要孔洞（如河中岛），单独 cartography-quality
change 处理。

### D4：fetch_lanecove.py 加 dry-run / smoke 模式

**选择**：保留现有 CLI，只内部 refactor relation 处理函数。不加新 flag。

**Rationale**：scope 控制；测试用 unit test 而不是 CLI smoke。

### D5：Map Explorer tunnel 过滤位置

**选择**：在 `server.py` 加载 OSM features 时过滤——遇到水 LineString 检查
tags：

```python
if tags.get("tunnel") in ("yes", "culvert", "building_passage"):
    continue
try:
    if int(tags.get("layer", "0")) < 0:
        continue
except ValueError:
    pass
if tags.get("covered") == "yes":
    continue
```

**Rationale**：渲染层是消费方；过滤逻辑放消费方语义清晰。GeoJSON 仍含完整
水道数据（其它工具可能需要地下涵洞信息）。

### D6：测试策略

**选择**：
1. 单元测试 ring assembly（手造数据，无网络依赖）：
   - 4 条 way 构成矩形 → 装出 1 个闭合环
   - 中断的 chain（少 1 条 way）→ 返空 list + warning
   - 已闭合的单 way → 直接作为环输出
2. 集成测试用 cached `lanecove_osm.geojson`（fetch 后）：
   - 断言至少 1 个 water polygon area > 50000 m²
   - 断言 LCR 名字出现在某个 polygon 的 properties

不直接调 Overpass API（CI 不稳 + 人 GitHub 上限）。

## Risks / Trade-offs

**[Risk 1] 端点 node_id 在 Overpass 返回里不全**
→ 我们 fetch query 加 `>;` recursion 拉所有节点；如果某 way 节点缺失则 chain
  断 → drop（D2 行为）。验证：fetch 完后比较 way 输入数 vs 装环输出数

**[Risk 2] 某些 relation 有多个独立闭合外环**（如海湾分两块）
→ D1 算法天然支持：每装满一个环再开新种子。OK

**[Risk 3] Overpass 调用不稳定（429 / 504）**
→ 复用现有 retry 逻辑；不引入新 risk

**[Risk 4] inner ring 丢失视觉差**
→ Lane Cove 区域无重大 inner ring；接受

**[Risk 5] re-fetch 改了别的非 water 数据**
→ fetch query 设计是确定性的；OSM 上游可能有微小数据变化（贡献者编辑），
  但建筑 / 道路过去几个月稳定。如有变化，dedup pass 会处理多出来的重复

## Migration Plan

1. 实现 `_assemble_multipolygon` + 单元测试
2. 重构 `fetch_lanecove.py` 的 relation 处理逻辑用新函数
3. 跑 `python3 tools/fetch_lanecove.py` 重 fetch（10-20 s）
4. 跑 `python3 tools/enrich_map.py` 重 enrich
5. `rm data/lanecove_atlas.json` + 重 bake atlas
6. 加 Map Explorer tunnel filter
7. 跑全 pytest
8. 手工开 Map Explorer 验视觉
9. archive sync cartography spec

**回滚**：本 change 是数据/渲染 fix；如需回滚 git revert + 重 fetch 即可。
下游不受影响。

## Open Questions

1. **Q1**: 是否给 fetch 脚本加 cache（避免每次重 fetch）？
   倾向：暂不；fetch 一次时间不长，cache 复杂度不值
2. **Q2**: Map Explorer 是否要给 stream 不同颜色 / dashing 区分明渠 vs 暗
   涵洞 vs 季节性？
   倾向：本 change 只过滤地下；视觉样式留给后续
3. **Q3**: 给 atlas Region 加 `water_polygons` 字段？
   倾向：不；现有 outdoor_areas 里 area_type="water" 已经够；新字段是 spec
   change，scope 不值
