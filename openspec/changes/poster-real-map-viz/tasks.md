## 1. 新增 build_atlas_thumbnail.py

- [x] 1.1 创建 `tools/build_atlas_thumbnail.py`，CLI 接受 `--atlas` / `--positions` /
  `--out` / `--stats-out` / `--center-x` `--center-y` / `--radius-m`(默认 1000)
- [x] 1.2 读 `data/lanecove_atlas.json`，提取 1000m 半径内：
  - outdoor areas (park / playground / street)
  - building polygons (residential / cafe / shop / office / 等)
  - 渲染到 SVG viewBox（atlas coords 已经是 projected meters，无需 pyproj）
- [x] 1.3 解析所有 `seed_*_positions.json`，每个 PositionChange 按 `location_id`
  查 atlas 取 centroid，按 **25m × 25m** 网格累计 → 通行热度 grid
- [x] 1.4 渲染分层 SVG（顺序见 design.md D3）；输出到 `--out`
- [x] 1.5 计算 stats：n_seeds / dwell_by_type_pct / total_position_events /
  median_changes_per_seed；写 `--stats-out`

## 2. 用 preflight 数据生成第一版 thumbnail + stats

- [x] 2.1 跑命令：
  ```
  python3 tools/build_atlas_thumbnail.py \
    --atlas data/lanecove_atlas.json \
    --positions "data/experiments/20260513_051605_preflight_1000agent_smoke/20260513_051606_preflight/variant_baseline/seed_*_positions.json" \
    --out docs/poster_atlas_thumbnail.svg \
    --stats-out docs/poster_baseline_stats.json
  ```
  → 18 seed, 2070 building + 1928 outdoor in radius, 1.46M position events,
  SVG 841KB
- [x] 2.2 用浏览器打开 `docs/poster_atlas_thumbnail.svg` 视觉验收：
  - SVG 含 2070 个真 building polygon（residential 粉/cafe 黄/shop 浅黄/...）
  - 含 1928 个 outdoor area + street polyline + 1000m radius 圆环 + Plaza 标签
  - 通行热度 layer (pink overlay) 在街口聚集
  - **honesty note**: stats 显示 dwell_street_pct=95% 是因为 position_changes 记的是
    "经过/移动"事件不是停留时长——一个 agent 走过 22 个街段记 22 次,住一晚记 1 次。
    poster 文案改成"通行热度/movement density"，不是"dwell density"。

## 3. 海报 patch

- [x] 3.1 修改 `docs/poster_a1.html` 的 "01 · 地图与图表" 卡片：
  - 删除 5-line sketch SVG
  - 改成 `<object type="image/svg+xml" data="poster_atlas_thumbnail.svg">`
  - 正文改成"渲染自真实 atlas"
- [x] 3.2 修改 "03 · 实验答案" 卡片：
  - 把假的 555/631/510/578 hp 对比删除（preflight 没有 hp 数据）
  - 改成 area_type 分布：street 95% / residential 2.5% / shop 0.4% / restaurant 0.3% / ...
  - 明确标注"通行事件按 area_type" + "hp/gd/pf 需 D1' Gemini 跑完才能填"

## 4. 验收

- [ ] 4.1 浏览器打开 `docs/poster_a1.html`，确认 01 卡显示真实街区形状（不是 5 根线）
- [ ] 4.2 用 Cmd+P → Print to PDF → A1 size 预览，确认 SVG 缩放后字体可读
- [ ] 4.3 word count 重新计算：`combined ≤ 2200`
