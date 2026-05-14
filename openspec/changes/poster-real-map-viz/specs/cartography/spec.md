## ADDED Requirements

### Requirement: Atlas thumbnail CLI 生成印刷用静态地图

`tools/build_atlas_thumbnail.py` SHALL 提供一个独立 CLI，
从 `data/lanecove_atlas.json` 和一组 `seed_*_positions.json` 渲染
**静态 SVG 缩略图**，可嵌入 A1 海报或其它印刷品。

输出 SVG 必须包含以下分层（z-order 从下到上）：

1. 1000m radius 圆环（以 atlas region 中心为圆心）
2. Outdoor area polygons（park / playground / street outdoor 类）
3. Street segment 线
4. Building polygons，按 `building_type` 着色（residential / cafe / shop / office）
5. Dwell density heatmap（20m × 20m 网格累计 position changes，半透明叠层）
6. Plaza / 关键 anchor 的文字标签

#### Scenario: 1000-agent preflight 数据生成印刷海报缩略图

- **WHEN** CLI 调用：
  ```
  tools/build_atlas_thumbnail.py \
    --atlas data/lanecove_atlas.json \
    --positions "<glob to seed_*_positions.json>" \
    --out docs/poster_atlas_thumbnail.svg \
    --stats-out docs/poster_baseline_stats.json
  ```
- **THEN** SHALL 输出一个 SVG 文件，含真实 Lane Cove building polygon
  形状（非手画 sketch）；同时输出一个 JSON 含 n_seeds、
  dwell_residential_pct、median encounter per day 等统计字段，
  供海报正文引用

#### Scenario: 没有 position 数据时仍能输出底图

- **WHEN** `--positions` 留空或匹配到 0 文件
- **THEN** SHALL 输出仅含 atlas 几何（无 heatmap 层）的 SVG，
  不报错；stats JSON 写入 `"n_seeds": 0` 标记
