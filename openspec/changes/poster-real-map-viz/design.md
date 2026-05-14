## Context

海报 A1 印刷尺寸（594mm × 841mm），单张卡片 preview 区约 60mm × 38mm。在 600 DPI 印刷下，
这是 1417 × 897 px 的实际渲染空间——可以放进相当多细节。

我们已有的渲染管线 (`build_2d_replay.py`) 是**全屏交互式 HTML + 时间滑块**，
对静态海报来说太重；而我们没有一个"提取一帧 + 输出印刷质量静态 SVG"的工具。
这就是要新增的部分。

数据源现状：

- `data/lanecove_atlas.json` ≈ 17MB JSON，含 5,480 个 building polygon (residential / cafe / shop / etc.) +
  street segments + outdoor areas，每个 polygon 都有完整顶点
- `data/experiments/20260513_051605_preflight_1000agent_smoke/.../variant_baseline/seed_*_positions.json` ×19
  ——每个 ~7MB，记录 1000 agent × 1 天 × 每 5 分钟一帧的位置变化

## Goals

- 静态印刷质量 SVG（A1 海报里 60mm × 38mm 区域内可读），含真实 Lane Cove 街道 + building polygon
- 在地图上叠加一个 dwell-density 热点层（暖色对应 agent 长期停留处）
- 海报 06 卡 + 03 卡的数字从手编 placeholder 换成 preflight 19 seed 实测值
- 工具可独立 CLI 跑，参数化输入 atlas 路径 + position trace glob

## Non-Goals

- 不实现交互（hover / play / scrub）——印刷海报本就静态
- 不等 D1' Gemini run 完成才能产出（preflight 19 seed 数据足够）
- 不替换 02 / 04 / 05 / 06 三张卡的 schematic 图——那几张本来就是抽象示意

## Decisions

### D1：thumbnail 渲染策略 — Python SVG 直生成

候选 A：用 Folium / Leaflet 截屏 → PNG 嵌入  
候选 B：用 Python 直接拼 SVG 字符串  
候选 C：调用现有 `build_2d_replay.py` 加一个 `--export-static-svg DAY:TICK` 模式

选 B（直接 SVG）：
- 印刷海报需要矢量；PNG 在 A1 600 DPI 下需要 ~5000px 宽，体积大
- 不引入新依赖（avoid Folium / playwright）
- 与海报内联 SVG 风格一致，可直接 `<svg>` 嵌入
- C 选项理论上更 DRY，但 build_2d_replay 是动态 viewer，硬塞 static export 会污染那个文件

### D2：dwell heatmap 算法 — 网格累计

把 1000 m × 1000 m 范围切成 50 × 50 网格（20m × 20m 单元）。
对每个 position_changes 记录，按 location_id 查 atlas 拿到 centroid，
落到对应网格 cell 上 +1。19 seed 累加。

热点强度 → 不透明度（0% baseline → 80% peak）+ 颜色（pink → yellow gradient）。

为什么不直接 plot 每个 agent 的轨迹：
- 19 seed × 1000 agent × ~4600 changes/seed = ~87M 个点——SVG 撑不住
- 客户/答辩看的是"<u>哪里聚人</u>"，不是单条轨迹

### D3：缩略图分层结构（z-order，从下到上）

1. 背景：浅米色 `var(--bg)`
2. 1000m radius 圆环（pink dashed）
3. Outdoor area polygons (park / playground)：浅绿填充
4. Street segments：深灰 1px line
5. Building polygons：按 area_type 着色（residential 浅粉、cafe 黄、shop 灰、office 暗黄）
6. Dwell heatmap：半透明色块覆盖
7. Plaza 标记：黄色矩形 + 标签
8. 1000m label

### D4：海报数字替换 — 从 preflight 19 seed 算

`tools/build_atlas_thumbnail.py` 额外接受 `--stats-out` 参数，
吐出一个 `poster_baseline_stats.json` 含：

```json
{
  "n_seeds": 19,
  "n_agents_total": 19000,
  "weak_tie_formation_mean": ...,
  "weak_tie_formation_iqr": [..., ...],
  "encounter_per_day_median": ...,
  "dwell_residential_pct": ...,
  "dwell_street_pct": ...,
  "config": "1000 agent × 1 day × baseline × stub"
}
```

然后 poster_a1.html 里的"实验答案"卡按这份 stats 改数字 + 加注"19 seed × 1-day stub
preflight baseline only — D1' 14d Gemini 全量见正在跑的 run"。

### D5：A1 PDF 输出

海报最终要从浏览器 print → A1 PDF。SVG thumbnail 内联在 HTML 里，
浏览器会按矢量打印。无需额外步骤。

## Risks / Trade-offs

- **SVG 文件大**：5,480 polygons × ~10 vertices each = ~55K 路径点；纯 SVG 可能 1–2 MB
  → mitigation: 只渲染 1000m radius 内的 building（preflight runs are bounded by this radius）
- **dwell heatmap 颜色 vs polygon 颜色冲突**：可能视觉上看不清楚
  → mitigation: 网格 cell 用 mix-blend-mode multiply 或单独的 hue（橙色），与 building 着色错开
- **19 seed 都是 baseline、都是 1 day、都是 stub LLM**：算出来的"实验答案"不能直接归因为
  hp vs baseline 的差异，只能给"基线本来什么样"的数字
  → mitigation: 海报上明确标注"1-day stub baseline preflight"；hp vs gd vs pf 等 D1' Gemini 跑完再补
- **印刷时 SVG 字体后备**：客户机器没装 PingFang/Noto CJK
  → mitigation: 内联 SVG 内只放数字 + 拉丁字符；中文写到外层 HTML，复印时不依赖 SVG 字体

## Migration Plan

1. 写 `tools/build_atlas_thumbnail.py` 工具（含 dwell heatmap + stats out）
2. 跑：`python3 tools/build_atlas_thumbnail.py \
       --atlas data/lanecove_atlas.json \
       --positions "data/experiments/20260513_051605_*/.../variant_baseline/seed_*_positions.json" \
       --out docs/poster_atlas_thumbnail.svg \
       --stats-out docs/poster_baseline_stats.json`
3. 用 Python 读 `poster_baseline_stats.json`，patch `docs/poster_a1.html` 里的"实验答案"数字
4. 把 docs/poster_a1.html 的"地图与图表"卡里 sketch SVG 换成 `<object data="poster_atlas_thumbnail.svg">` 或内联 svg
5. 浏览器打开海报视觉验收

## Open Questions

- **要不要在海报上再加一张第 7 张卡显示 dwell heatmap 单独?** 还是只 embed 到 01 卡里就够？
  → 倾向：embed 到 01 卡足够。如果空间允许，第 7 张专门讲 heatmap + 边界注释。
- **D1' Gemini run 完成后是否要再生成一张含真 hp 数据的 thumbnail?**
  → 是；本 change 只解 preflight 数据可视化；D1' 完成后另起 change 做 publishable 版。
