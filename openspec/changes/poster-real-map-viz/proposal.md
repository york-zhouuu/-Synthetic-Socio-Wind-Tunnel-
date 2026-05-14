## Why

`docs/poster_a1.html` 当前版本里的"地图与图表"卡片用了一张**手画 SVG**（5 条线 + 几个红点）当作地图——
完全是装饰，不是从真实数据生成的。这违反 CLAUDE.md 关于"对外报告必须落到 Lane Cove 真街名 / 真数字"的写作约束，
也辜负了项目里已存在的**真实地图渲染管线**（`build_2d_replay.py` / `build_viz_dashboard.py` / `lanecove_atlas.json`）。

客户/答辩看到这个海报会立刻意识到："你们号称有 5,480 栋建筑的真实地图，海报上为什么只有 5 根线？"——
方法学可信度立刻破产。

项目里现有的真实可视化资源：

- `data/lanecove_atlas.json`：含真实 building polygon、street segment、area_type tag
- `tools/build_2d_replay.py`：消费 `seed_*_positions.json` 输出**带真街道形状的 SVG 时间轴 replay**
- `tools/build_viz_dashboard.py`：输出基于 Leaflet 的地图 dashboard 含 encounter heatmap
- 19 个 `seed_*_positions.json` 来自 2026-05-13 1000-agent preflight smoke——已有可用数据

## What Changes

- 在 `docs/poster_a1.html` 的 "01 · 地图与图表" 卡片里：用 `tools/build_atlas_thumbnail.py` （新增）生成一张**静态 SVG 缩略图**，嵌入到海报 `<img>` 或内联 `<svg>`
  - 缩略图渲染真实 Lane Cove 街道 + building polygon + 1000m radius circle + Plaza 标记 + 真实 agent dwell density 热点
  - 数据源：`data/lanecove_atlas.json` + 现有 preflight seed 的 position trace
- 在 "03 · 实验答案" 卡片里：把示例数字（555/631/510/578）替换为**从 preflight 19 seed 真实算出的 baseline 均值/IQR**，加注"baseline only, 1-day"标签
- 海报另增第 7 张卡或 panel 显示**真实 dwell-density heatmap**（用 19 seed 聚合的位置数据）
- 把 SVG 装饰版的"假地图"换成上述真品；保留"5 幕故事条 / 架构图 / lock 字段 / 文档树"等抽象示意（这些本就是 schematic）
- 新增 `tools/build_atlas_thumbnail.py` CLI 工具，可独立运行重新生成缩略图

## Capabilities

### New Capabilities

无（不引入新仿真能力；只是新增一个离线渲染工具）。

### Modified Capabilities

无（不修改任何 spec-level 行为）。

## Impact

- **新增代码**：`tools/build_atlas_thumbnail.py`（独立 CLI；不依赖正在跑的 D1' run）
- **修改文件**：`docs/poster_a1.html`（替换 sketch SVG → 嵌入真实 thumbnail；用 preflight 真数据替换 placeholder）
- **数据依赖**：现有 `data/lanecove_atlas.json` + 现有 preflight 19 seed positions（无需等 D1' 跑完）
- **不影响**：任何运行中的 simulation / D1' run / 单元测试 / 其它海报章节
- **可独立验证**：缩略图生成是一次性离线任务，跑完看 `docs/poster_atlas_thumbnail.svg` 是否含真实街道形状即知成功
