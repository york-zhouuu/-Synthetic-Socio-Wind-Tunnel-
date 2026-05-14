"""Build fancy single-file HTML dashboard for a suite output.

Self-contained: no external CDN deps for data; uses inline Leaflet from CDN
for the map (one <script> tag). Atlas geometry is reduced to centroids +
area_type per location to keep HTML size manageable.

Usage:
    python3 tools/build_viz_dashboard.py <suite_dir> [--out dashboard.html]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import pyproj


def _polygon_centroid(coords: list) -> tuple[float, float] | None:
    """Compute centroid of a polygon's coords [[x,y], [x,y], ...]."""
    if not coords:
        return None
    n = len(coords)
    if n == 0:
        return None
    xs = sum(c[0] for c in coords) / n
    ys = sum(c[1] for c in coords) / n
    return (xs, ys)


def _load_atlas_summary(atlas_path: Path, proj_center_path: Path) -> dict[str, Any]:
    """Reduce atlas to per-location centroid + type + area_type + size.

    Converts projected (metres) coords back to lat/lon for Leaflet display.
    Atlas structure:
    - outdoor_areas / buildings: dict[id, area_dict]
    - polygon.vertices: list[{"x": float, "y": float}] (projected metres)
    - proj_center.json: {"center_lat": float, "center_lon": float}
    """
    with atlas_path.open(encoding="utf-8") as fh:
        atlas = json.load(fh)
    with proj_center_path.open(encoding="utf-8") as fh:
        center = json.load(fh)
    lat0 = center["center_lat"]
    lon0 = center["center_lon"]

    proj = pyproj.Proj(proj="aeqd", lat_0=lat0, lon_0=lon0, units="m")

    out_locs: dict[str, dict] = {}

    def _process_area(aid: str, data: dict, type_label: str, type_field: str) -> None:
        poly = data.get("polygon", {})
        verts = poly.get("vertices", []) or poly.get("coords", [])
        if not verts:
            return
        if isinstance(verts[0], dict):
            xs = [v.get("x", 0) for v in verts]
            ys = [v.get("y", 0) for v in verts]
        else:
            xs = [v[0] for v in verts]
            ys = [v[1] for v in verts]
        if not xs:
            return
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        lon, lat = proj(cx, cy, inverse=True)
        out_locs[aid] = {
            "type": type_label,
            "area_type": data.get(type_field, "unknown"),
            "lat": lat,
            "lon": lon,
            "name": data.get("name", aid),
        }

    outdoor = atlas.get("outdoor_areas", {})
    if isinstance(outdoor, dict):
        for aid, data in outdoor.items():
            _process_area(aid, data, "outdoor", "area_type")
    else:
        for data in outdoor:
            _process_area(data["id"], data, "outdoor", "area_type")

    buildings = atlas.get("buildings", {})
    if isinstance(buildings, dict):
        for bid, data in buildings.items():
            _process_area(bid, data, "building", "building_type")
    else:
        for data in buildings:
            _process_area(data["id"], data, "building", "building_type")

    return {
        "locations": out_locs,
        "center": {"lat": lat0, "lon": lon0},
    }


def _load_suite(suite_dir: Path) -> dict[str, list[dict]]:
    by_variant: dict[str, list[dict]] = {}
    for vd in sorted(suite_dir.iterdir()):
        if not vd.is_dir() or not vd.name.startswith("variant_"):
            continue
        for sf in sorted(vd.glob("seed_*.json")):
            # Skip companion position-trace files (seed_X_positions.json) —
            # they have their own schema and are consumed separately.
            if "_positions" in sf.stem:
                continue
            with sf.open(encoding="utf-8") as fh:
                by_variant.setdefault(vd.name, []).append(json.load(fh))
    return by_variant


def _aggregate_variant(seeds: list[dict]) -> dict[str, Any]:
    """Average across seeds for visualisation."""
    if not seeds:
        return {}
    # Use first seed for now (D1' has 1 seed; D2 will have N)
    rm = seeds[0]["run_metrics"]
    space_act = rm.get("space_activation", {})
    per_day = rm.get("per_day", [])

    # Average across seeds if multi-seed
    if len(seeds) > 1:
        # Aggregate space_activation
        space_act = {}
        for s in seeds:
            for k, v in s["run_metrics"].get("space_activation", {}).items():
                space_act[k] = space_act.get(k, 0) + v
        for k in space_act:
            space_act[k] /= len(seeds)
        # Aggregate per_day (median across seeds per day)
        per_day_lists: list[list] = []
        for s in seeds:
            pd = s["run_metrics"].get("per_day", [])
            per_day_lists.append(pd)
        n_days = min(len(p) for p in per_day_lists) if per_day_lists else 0
        per_day = []
        for d in range(n_days):
            day_data: dict[str, Any] = {}
            for k in per_day_lists[0][d].keys():
                vals = [
                    p[d].get(k) for p in per_day_lists
                    if isinstance(p[d].get(k), (int, float))
                ]
                if vals:
                    day_data[k] = statistics.median(vals)
            per_day.append(day_data)

    return {
        "encounter_total_median": statistics.median(
            s["run_metrics"]["encounter_stats"]["total"] for s in seeds
        ),
        "traj_dev_protag": [
            s["run_metrics"].get("trajectory_deviation_m") for s in seeds
        ],
        "weak_tie": [
            s["run_metrics"].get("weak_tie_formation_count", 0) for s in seeds
        ],
        "cost_total": sum(
            (s["run_metrics"].get("cost_breakdown") or {}).get("total", 0)
            for s in seeds
        ),
        "space_activation": space_act,
        "per_day": per_day,
        "replan_count": [
            s["run_metrics"].get("extensions", {}).get("replan_count", 0)
            for s in seeds
        ],
        "n_seeds": len(seeds),
        "rep_lock": seeds[0]["run_metrics"]
            .get("extensions", {}).get("reproducibility_lock", {}),
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Synthetic Socio Wind Tunnel · 实验结果可视化</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC",
               "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  margin: 0; padding: 0;
  background: #0f0f12;
  color: #e8e8e8;
}
header {
  padding: 40px 60px 20px;
  border-bottom: 1px solid #2a2a30;
}
.tag {
  font-size: 13px; letter-spacing: 0.15em; color: #888;
  text-transform: uppercase; margin-bottom: 8px;
}
h1 { font-size: 32px; margin: 0 0 8px; font-weight: 700; }
.subtitle { color: #999; font-size: 16px; margin: 0 0 0; }

.container { max-width: 1400px; margin: 0 auto; padding: 0 30px; }

/* Stats row */
.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin: 30px 0;
}
.stat-card {
  background: #1a1a20;
  border-radius: 12px;
  padding: 24px;
  border-top: 4px solid #888;
}
.stat-card.baseline { border-top-color: #6b7280; }
.stat-card.hp { border-top-color: #c8553d; }
.stat-card.gd { border-top-color: #fd7e14; }
.stat-card.pf { border-top-color: #10b981; }
.stat-label {
  font-size: 12px;
  color: #999;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin-bottom: 8px;
}
.stat-main { font-size: 32px; font-weight: 700; line-height: 1.1; }
.stat-sub { font-size: 14px; color: #888; margin-top: 6px; }
.delta-pos { color: #10b981; }
.delta-neg { color: #ef4444; }
.delta-zero { color: #888; }

/* Tabs */
.tabs {
  display: flex;
  gap: 4px;
  margin: 24px 0 0;
  border-bottom: 1px solid #2a2a30;
}
.tab {
  padding: 12px 24px;
  background: none;
  color: #999;
  border: none;
  border-bottom: 3px solid transparent;
  cursor: pointer;
  font-size: 15px;
  font-family: inherit;
  transition: all 0.15s;
}
.tab:hover { color: #fff; }
.tab.active {
  color: #fff;
  border-bottom-color: #c8553d;
}
.tab.baseline.active { border-bottom-color: #6b7280; }
.tab.hp.active { border-bottom-color: #c8553d; }
.tab.gd.active { border-bottom-color: #fd7e14; }
.tab.pf.active { border-bottom-color: #10b981; }

/* Map */
#map {
  height: 600px;
  border-radius: 12px;
  margin: 24px 0;
  background: #1a1a20;
}
.legend {
  background: #1a1a20;
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 13px;
  color: #ccc;
  line-height: 1.6;
}
.legend-gradient {
  display: inline-block;
  width: 100%;
  height: 12px;
  background: linear-gradient(to right, #1e3a5f, #c8553d);
  border-radius: 4px;
  margin: 6px 0;
}

/* Time series */
.chart-container {
  background: #1a1a20;
  padding: 28px;
  border-radius: 12px;
  margin: 24px 0;
}
.chart-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 4px;
}
.chart-desc {
  font-size: 14px;
  color: #999;
  margin-bottom: 24px;
}
.chart-svg {
  width: 100%;
  height: 360px;
  display: block;
}

/* Section heading */
h2 {
  font-size: 24px;
  margin: 60px 0 16px;
  font-weight: 600;
}
.section-desc {
  color: #999;
  font-size: 15px;
  margin-bottom: 24px;
}

footer {
  margin-top: 80px;
  padding: 30px 60px;
  border-top: 1px solid #2a2a30;
  color: #666;
  font-size: 13px;
}

@media (max-width: 900px) {
  .stats { grid-template-columns: repeat(2, 1fr); }
  header { padding: 30px 20px 15px; }
}
</style>
</head>
<body>

<header>
  <div class="container">
    <p class="tag">Synthetic Socio Wind Tunnel · 实验证据可视化</p>
    <h1>Lane Cove 四组对照 · {{ subtitle }}</h1>
    <p class="subtitle">{{ run_meta }}</p>
  </div>
</header>

<div class="container">

  <!-- KEY STATS -->
  <div class="stats">{{ stat_cards }}</div>

  <!-- MAP SECTION -->
  <h2>① 空间证据 · 哪里被激活了</h2>
  <p class="section-desc">
    Lane Cove 真实街区上叠 4 个对照组的 14 天累积 dwell 热度——
    哪些 location 在每组干预下被居民频繁停留。点击切换 variant。
  </p>

  <div class="tabs" id="map-tabs">
    <button class="tab baseline active" data-variant="variant_baseline">① 什么都不推</button>
    <button class="tab hp" data-variant="variant_hyperlocal_push">② 超在地推送 (hp)</button>
    <button class="tab gd" data-variant="variant_global_distraction">③ 推全球新闻 (gd)</button>
    <button class="tab pf" data-variant="variant_phone_friction">④ 减少手机吸力 (pf)</button>
  </div>

  <div id="map"></div>

  <div class="legend">
    <strong>颜色编码</strong>：dwell 热度低 → 高
    <div class="legend-gradient"></div>
    <small>圈的大小 ∝ √累计 dwell ticks。只显示 top 80 个 location（按 dwell 排序）</small>
  </div>

  <!-- TIME SERIES SECTION -->
  <h2>② 时间序列 · 14 天里 4 组怎么演化</h2>
  <p class="section-desc">
    干预从 day 4 开始（前 4 天是 baseline period，4 组完全一致）。
    看分歧从哪天起、怎么放大。
  </p>

  <div class="chart-container">
    <div class="chart-title">每日总偶遇数（encounter total per day）</div>
    <div class="chart-desc">居民在同一 location 共处的 (pair × tick) 数。pf 在 day 9-13 的 spike 是 friction 累积效应的标志。</div>
    <svg class="chart-svg" id="chart-enc"></svg>
  </div>

  <div class="chart-container">
    <div class="chart-title">每日不同对子数（distinct pairs per day）</div>
    <div class="chart-desc">当天有多少对 agent 相遇过——衡量"接触多样性"。pair 数高说明遇见的人 *种类* 多，不是同一对反复见。</div>
    <svg class="chart-svg" id="chart-pairs"></svg>
  </div>

  <div class="chart-container">
    <div class="chart-title">每日新建立的弱关系（new_ties_today）</div>
    <div class="chart-desc">从 day 0 的 1615 个新关系暴增 → day 13 只剩个位数（饱和）。intervention 期能看到 pf/gd 略保持新关系产能，hp 接近 baseline。</div>
    <svg class="chart-svg" id="chart-newties"></svg>
  </div>

  <footer>
    <div class="container">
      <p>
        <strong>provider</strong>: {{ provider }} ·
        <strong>model_version</strong>: {{ model_version }} ·
        <strong>seeds</strong>: {{ seed_count }} ·
        <strong>agents</strong>: {{ agents }} ·
        <strong>days</strong>: {{ days }}
      </p>
      <p>
        <strong>code_commit</strong>: <code>{{ code_commit }}</code> ·
        相关文档：
        <a href="../../docs/四个对照组.html" style="color:#c8553d">四个对照组说明</a> ·
        <a href="../../docs/limitations-ethics.md" style="color:#c8553d">局限与伦理</a> ·
        <a href="../../docs/2026-05-12-d1-deepseek-deep-analysis.md" style="color:#c8553d">深度解读</a>
      </p>
    </div>
  </footer>

</div>

<script>
const VIZ_DATA = {{ viz_data_json }};

const VARIANT_COLOR = {
  variant_baseline: '#6b7280',
  variant_hyperlocal_push: '#c8553d',
  variant_global_distraction: '#fd7e14',
  variant_phone_friction: '#10b981',
};

const VARIANT_LABEL = {
  variant_baseline: '什么都不推',
  variant_hyperlocal_push: '超在地推送',
  variant_global_distraction: '推全球新闻',
  variant_phone_friction: '减少手机吸力',
};

// ============ MAP ============
const center = VIZ_DATA.atlas.center;
const map = L.map('map', { zoomControl: true }).setView([center.lat, center.lon], 15);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap, © CartoDB',
  maxZoom: 19,
}).addTo(map);

let currentLayer = null;

function renderHeatmap(variantName) {
  if (currentLayer) {
    map.removeLayer(currentLayer);
  }
  const variant = VIZ_DATA.variants[variantName];
  if (!variant) return;
  const sp = variant.space_activation;
  // Sort locations by dwell descending; take top 80
  const sorted = Object.entries(sp)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 80);
  if (sorted.length === 0) return;
  const maxDwell = sorted[0][1];

  const group = L.featureGroup();
  sorted.forEach(([locId, dwell]) => {
    const loc = VIZ_DATA.atlas.locations[locId];
    if (!loc) return;
    const intensity = Math.pow(dwell / maxDwell, 0.6);
    const radius = 4 + Math.sqrt(dwell / maxDwell) * 18;
    // Color blend: dark blue (#1e3a5f) → red orange (#c8553d)
    const r = Math.round(30 + (200 - 30) * intensity);
    const g = Math.round(58 + (85 - 58) * intensity);
    const b = Math.round(95 + (61 - 95) * intensity);
    const color = `rgb(${r}, ${g}, ${b})`;
    L.circleMarker([loc.lat, loc.lon], {
      radius: radius,
      color: VARIANT_COLOR[variantName],
      fillColor: color,
      fillOpacity: 0.65,
      weight: 1.5,
      opacity: 0.9,
    }).bindPopup(
      `<strong>${loc.name}</strong><br>` +
      `type: ${loc.area_type}<br>` +
      `dwell: ${Math.round(dwell)} ticks<br>` +
      `variant: ${VARIANT_LABEL[variantName]}`
    ).addTo(group);
  });
  group.addTo(map);
  currentLayer = group;
}

// Tab switching
document.querySelectorAll('#map-tabs .tab').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#map-tabs .tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderHeatmap(btn.dataset.variant);
  });
});
// initial
renderHeatmap('variant_baseline');

// ============ TIME SERIES ============
function drawTimeSeries(svgId, metricKey, yLabel) {
  const svg = document.getElementById(svgId);
  svg.innerHTML = '';
  const w = svg.clientWidth || 800;
  const h = 360;
  const pad = { top: 20, right: 30, bottom: 40, left: 70 };
  const innerW = w - pad.left - pad.right;
  const innerH = h - pad.top - pad.bottom;

  const variants = Object.keys(VIZ_DATA.variants);
  const numDays = VIZ_DATA.variants[variants[0]].per_day.length;
  // Get all values to determine y range
  let yMin = Infinity, yMax = -Infinity;
  variants.forEach(v => {
    VIZ_DATA.variants[v].per_day.forEach(d => {
      const val = d[metricKey];
      if (typeof val === 'number') {
        yMin = Math.min(yMin, val);
        yMax = Math.max(yMax, val);
      }
    });
  });
  if (yMin === Infinity) { yMin = 0; yMax = 1; }
  const yRange = yMax - yMin || 1;
  yMin = Math.max(0, yMin - yRange * 0.05);
  yMax = yMax + yRange * 0.05;

  const xScale = (d) => pad.left + (d / (numDays - 1)) * innerW;
  const yScale = (v) => pad.top + (1 - (v - yMin) / (yMax - yMin)) * innerH;

  // Axes
  const xAxis = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  for (let d = 0; d < numDays; d++) {
    if (d % 2 !== 0 && d !== numDays - 1) continue;
    const x = xScale(d);
    const tick = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    tick.setAttribute('x', x);
    tick.setAttribute('y', h - 15);
    tick.setAttribute('text-anchor', 'middle');
    tick.setAttribute('fill', '#888');
    tick.setAttribute('font-size', '12');
    tick.textContent = `day ${d}`;
    xAxis.appendChild(tick);
  }
  svg.appendChild(xAxis);

  // y axis labels
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (i / 4) * innerH;
    const value = yMax - (i / 4) * (yMax - yMin);
    const tick = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    tick.setAttribute('x', pad.left - 8);
    tick.setAttribute('y', y + 4);
    tick.setAttribute('text-anchor', 'end');
    tick.setAttribute('fill', '#888');
    tick.setAttribute('font-size', '11');
    tick.textContent = value > 1000 ? (value / 1000).toFixed(0) + 'k' : value.toFixed(0);
    svg.appendChild(tick);
    // gridline
    const grid = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    grid.setAttribute('x1', pad.left);
    grid.setAttribute('y1', y);
    grid.setAttribute('x2', pad.left + innerW);
    grid.setAttribute('y2', y);
    grid.setAttribute('stroke', '#2a2a30');
    grid.setAttribute('stroke-width', '1');
    svg.appendChild(grid);
  }

  // intervention vline
  const interventionStart = 4;
  const interventionLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  interventionLine.setAttribute('x1', xScale(interventionStart));
  interventionLine.setAttribute('y1', pad.top);
  interventionLine.setAttribute('x2', xScale(interventionStart));
  interventionLine.setAttribute('y2', pad.top + innerH);
  interventionLine.setAttribute('stroke', '#888');
  interventionLine.setAttribute('stroke-width', '1');
  interventionLine.setAttribute('stroke-dasharray', '4 4');
  svg.appendChild(interventionLine);
  const interventionLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  interventionLabel.setAttribute('x', xScale(interventionStart) + 4);
  interventionLabel.setAttribute('y', pad.top + 14);
  interventionLabel.setAttribute('fill', '#888');
  interventionLabel.setAttribute('font-size', '11');
  interventionLabel.textContent = '← intervention starts';
  svg.appendChild(interventionLabel);

  // Lines per variant
  variants.forEach(v => {
    const data = VIZ_DATA.variants[v].per_day;
    const color = VARIANT_COLOR[v];
    let path = '';
    data.forEach((d, i) => {
      const val = d[metricKey];
      if (typeof val !== 'number') return;
      const cmd = i === 0 ? 'M' : 'L';
      path += `${cmd}${xScale(i)},${yScale(val)} `;
    });
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    line.setAttribute('d', path);
    line.setAttribute('stroke', color);
    line.setAttribute('stroke-width', '2.5');
    line.setAttribute('fill', 'none');
    svg.appendChild(line);
    // Dots
    data.forEach((d, i) => {
      const val = d[metricKey];
      if (typeof val !== 'number') return;
      const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      dot.setAttribute('cx', xScale(i));
      dot.setAttribute('cy', yScale(val));
      dot.setAttribute('r', '3.5');
      dot.setAttribute('fill', color);
      svg.appendChild(dot);
    });
  });

  // Legend
  const legend = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  variants.forEach((v, i) => {
    const lx = pad.left + 10 + i * 170;
    const ly = pad.top + 10;
    const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    dot.setAttribute('cx', lx);
    dot.setAttribute('cy', ly);
    dot.setAttribute('r', '5');
    dot.setAttribute('fill', VARIANT_COLOR[v]);
    legend.appendChild(dot);
    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', lx + 9);
    text.setAttribute('y', ly + 4);
    text.setAttribute('fill', '#ccc');
    text.setAttribute('font-size', '12');
    text.textContent = VARIANT_LABEL[v];
    legend.appendChild(text);
  });
  svg.appendChild(legend);
}

drawTimeSeries('chart-enc', 'encounter_count_total', '偶遇总数');
drawTimeSeries('chart-pairs', 'distinct_encounter_pairs', '不同对子');
drawTimeSeries('chart-newties', 'new_ties_today', '新弱关系');
</script>

</body>
</html>
"""


def build_dashboard(suite_dir: Path, atlas_path: Path,
                    proj_path: Path, out_path: Path) -> None:
    by_variant = _load_suite(suite_dir)
    if not by_variant:
        print(f"error: no variant_*/seed_*.json in {suite_dir}", file=sys.stderr)
        sys.exit(2)

    atlas_summary = _load_atlas_summary(atlas_path, proj_path)

    variants_data = {}
    for name, seeds in by_variant.items():
        variants_data[name] = _aggregate_variant(seeds)

    viz_data = {
        "atlas": atlas_summary,
        "variants": variants_data,
    }

    # Pick metadata from baseline
    base = variants_data.get("variant_baseline", {})
    rep = base.get("rep_lock", {})
    sample_seed = next(iter(by_variant.values()))[0]
    mdr = sample_seed.get("multi_day_result", {})

    # Build stat cards
    baseline_enc = variants_data.get("variant_baseline", {}).get(
        "encounter_total_median", 0,
    )

    def _delta(name: str) -> str:
        v = variants_data.get(name, {}).get("encounter_total_median", 0)
        if baseline_enc == 0:
            return "—"
        pct = (v - baseline_enc) / baseline_enc * 100
        cls = "delta-pos" if pct > 0 else ("delta-neg" if pct < 0 else "delta-zero")
        sign = "+" if pct >= 0 else ""
        return f'<span class="{cls}">{sign}{pct:.1f}%</span>'

    def _stat_card(short: str, name_zh: str, name_en: str, variant_key: str) -> str:
        v = variants_data.get(variant_key, {})
        enc = v.get("encounter_total_median", 0)
        return (
            f'<div class="stat-card {short}">'
            f'<div class="stat-label">{name_zh}</div>'
            f'<div class="stat-main">{enc/1000:.0f}k</div>'
            f'<div class="stat-sub">总偶遇 · '
            f'{_delta(variant_key) if variant_key != "variant_baseline" else "baseline"}'
            f' · <code style="color:#888;font-size:11px;">{name_en}</code>'
            f'</div>'
            f'</div>'
        )

    stat_cards = (
        _stat_card("baseline", "① 什么都不推", "baseline", "variant_baseline") +
        _stat_card("hp", "② 超在地推送", "hyperlocal_push", "variant_hyperlocal_push") +
        _stat_card("gd", "③ 推全球新闻", "global_distraction", "variant_global_distraction") +
        _stat_card("pf", "④ 减少手机吸力", "phone_friction", "variant_phone_friction")
    )

    n_seeds = max((v.get("n_seeds", 0) for v in variants_data.values()), default=0)
    run_meta = (
        f'{n_seeds} seed × 14 day × {mdr.get("metadata", {}).get("n_agents", "~100")} agents · '
        f'provider = {rep.get("provider", "?")}'
    )
    subtitle = (
        "30 seed publishable run" if n_seeds >= 30 else
        ("15 seed publishable run" if n_seeds >= 15 else "smoke validation")
    )

    html = (
        HTML_TEMPLATE
        .replace("{{ subtitle }}", subtitle)
        .replace("{{ run_meta }}", run_meta)
        .replace("{{ stat_cards }}", stat_cards)
        .replace("{{ provider }}", str(rep.get("provider", "?")))
        .replace("{{ model_version }}", str(rep.get("model_version", "?")))
        .replace("{{ seed_count }}", str(n_seeds))
        .replace("{{ agents }}", str(mdr.get("metadata", {}).get("n_agents", "?")))
        .replace("{{ days }}", str(sample_seed["run_metrics"].get("num_days", "?")))
        .replace("{{ code_commit }}", str(rep.get("code_commit", "?"))[:12])
        .replace("{{ viz_data_json }}", json.dumps(viz_data, ensure_ascii=False))
    )

    out_path.write_text(html, encoding="utf-8")
    size_kb = len(html.encode()) / 1024
    print(f"✅ wrote {out_path} ({size_kb:.1f} KB)")
    print(f"   {sum(v.get('n_seeds', 0) for v in variants_data.values())} seed × "
          f"{len(by_variant)} variants × {len(atlas_summary['locations'])} locations")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("suite_dir", type=Path)
    p.add_argument(
        "--atlas", type=Path,
        default=Path("data/lanecove_atlas.json"),
    )
    p.add_argument(
        "--proj-center", type=Path,
        default=Path("data/lanecove_proj_center.json"),
    )
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    if not args.suite_dir.is_dir():
        print(f"error: not a directory: {args.suite_dir}", file=sys.stderr)
        return 2

    out = args.out or args.suite_dir / "dashboard.html"
    build_dashboard(args.suite_dir, args.atlas, args.proj_center, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
