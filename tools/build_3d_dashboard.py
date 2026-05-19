"""Build 3D Lane Cove sandbox dashboard with agent trajectories.

Tech stack (CDN-only, no build):
- maplibre-gl 3.x (open-source mapbox, no token needed)
- deck.gl 9.x (HexagonLayer / PathLayer / ScatterplotLayer / TripsLayer)
- Standalone HTML, no React / no Vite

Inspired by AgentSociety/frontend/src/pages/Replay/Deck.tsx but simplified
to single-file deliverable. 3D pitch view shows extruded hex columns of
dwell density and animated agent paths.

Usage:
    python3 tools/build_3d_dashboard.py <suite_dir> [--out 3d_dashboard.html]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics

# persist-per-day-summaries-across-resumes (2026-05-20): canonical
# seed_<N>.json regex — excludes day/tick/positions/partial aux files.
_REAL_SEED_RE = re.compile(r"^seed_\d+\.json$")
import sys
from pathlib import Path
from typing import Any

import pyproj


def _load_atlas_summary(atlas_path: Path, proj_center_path: Path) -> dict:
    with atlas_path.open(encoding="utf-8") as fh:
        atlas = json.load(fh)
    with proj_center_path.open(encoding="utf-8") as fh:
        center = json.load(fh)
    lat0 = center["center_lat"]
    lon0 = center["center_lon"]
    proj = pyproj.Proj(proj="aeqd", lat_0=lat0, lon_0=lon0, units="m")

    locs: dict[str, dict] = {}

    def _process(aid: str, data: dict, type_label: str, type_field: str) -> None:
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
        locs[aid] = {
            "type": type_label,
            "area_type": data.get(type_field, "unknown"),
            "lng": lon,
            "lat": lat,
            "name": data.get("name", aid),
        }

    outdoor = atlas.get("outdoor_areas", {})
    if isinstance(outdoor, dict):
        for aid, data in outdoor.items():
            _process(aid, data, "outdoor", "area_type")
    else:
        for data in outdoor:
            _process(data["id"], data, "outdoor", "area_type")

    buildings = atlas.get("buildings", {})
    if isinstance(buildings, dict):
        for bid, data in buildings.items():
            _process(bid, data, "building", "building_type")

    return {"locations": locs, "center": {"lat": lat0, "lng": lon0}}


def _load_suite(suite_dir: Path) -> dict[str, list[dict]]:
    by_variant: dict[str, list[dict]] = {}
    for vd in sorted(suite_dir.iterdir()):
        if not vd.is_dir() or not vd.name.startswith("variant_"):
            continue
        for sf in sorted(vd.glob("seed_*.json")):
            # Skip aux files: positions, snapshot, partial, day-summary.
            if not _REAL_SEED_RE.match(sf.name):
                continue
            with sf.open(encoding="utf-8") as fh:
                by_variant.setdefault(vd.name, []).append(json.load(fh))
    return by_variant


def _build_agent_trajectories(
    seeds: list[dict],
    locations: dict[str, dict],
    nav_router,
    max_agents: int = 100,
) -> list[dict]:
    """Build per-agent 14-day trajectory **through the real street network**.

    For each consecutive pair of (day d → day d+1) end-of-day locations,
    invokes NavigationService.find_route to get the actual sequence of
    outdoor_area / building locations the agent walks through, then
    converts that to lat/lng polyline.

    Returns list of {
        agent_id, path: [[lng,lat], ...], days: int,
        unique_locs: int, hops: int,
    }
    """
    if not seeds:
        return []
    rm = seeds[0]["run_metrics"]
    per_day = rm.get("per_day", [])
    if not per_day:
        return []

    all_agents = list(per_day[0].get("end_of_day_location_by_agent", {}).keys())
    sample = all_agents[:max_agents]

    # Cache routes between location pairs (huge speedup — many agents share
    # the same daily commute between home and work areas).
    route_cache: dict[tuple[str, str], list[str]] = {}

    def _route_locs(loc_a: str, loc_b: str) -> list[str]:
        """Return ordered list of location_ids on the street-network path."""
        if loc_a == loc_b:
            return [loc_a]
        key = (loc_a, loc_b)
        if key in route_cache:
            return route_cache[key]
        try:
            result = nav_router.find_route(loc_a, loc_b)
            if result.success and result.steps:
                # path = from_location followed by each step.to_location
                path = [loc_a]
                for step in result.steps:
                    if step.to_location and step.to_location != path[-1]:
                        path.append(step.to_location)
                route_cache[key] = path
                return path
        except Exception:
            pass
        # Fallback: straight 2-point line if routing fails
        route_cache[key] = [loc_a, loc_b]
        return [loc_a, loc_b]

    trajectories = []
    for agent_id in sample:
        daily_locs: list[str] = []
        for day in per_day:
            loc_id = day.get("end_of_day_location_by_agent", {}).get(agent_id)
            if loc_id:
                daily_locs.append(loc_id)

        if len(daily_locs) < 2:
            continue

        # Build full street-network path by routing between consecutive days
        full_path_locs: list[str] = [daily_locs[0]]
        for i in range(len(daily_locs) - 1):
            seg = _route_locs(daily_locs[i], daily_locs[i + 1])
            # Skip the first element (it's the previous segment's end)
            for loc in seg[1:]:
                full_path_locs.append(loc)

        # Convert location IDs to [lng, lat]
        path_lnglat = []
        for loc_id in full_path_locs:
            loc = locations.get(loc_id)
            if loc is not None:
                path_lnglat.append([loc["lng"], loc["lat"]])

        if len(path_lnglat) >= 2:
            trajectories.append({
                "agent_id": agent_id,
                "path": path_lnglat,
                "days": len(daily_locs),
                "unique_locs": len(set(daily_locs)),
                "hops": len(full_path_locs),
            })

    return trajectories


def _build_hex_data(
    seeds: list[dict],
    locations: dict[str, dict],
    top_n: int = 200,
) -> list[dict]:
    """Build hex data: list of {position, weight} for HexagonLayer."""
    if not seeds:
        return []
    rm = seeds[0]["run_metrics"]
    sp = rm.get("space_activation", {})
    sorted_locs = sorted(sp.items(), key=lambda x: -x[1])[:top_n]
    out = []
    for loc_id, dwell in sorted_locs:
        loc = locations.get(loc_id)
        if not loc:
            continue
        out.append({
            "position": [loc["lng"], loc["lat"]],
            "weight": float(dwell),
            "loc_id": loc_id,
            "name": loc["name"],
            "area_type": loc["area_type"],
        })
    return out


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SSWT · 3D Lane Cove Sandbox</title>
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet" />
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@9.0.38/dist.min.js"></script>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; overflow: hidden; background: #0a0a0e; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC",
               "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  color: #e8e8e8;
}
#map-container {
  position: fixed; inset: 0;
  width: 100%; height: 100vh;
}
#map, #deck-canvas { position: absolute; inset: 0; }

/* HUD */
.hud {
  position: fixed;
  pointer-events: none;
  z-index: 100;
}
.hud-top {
  top: 20px; left: 20px;
  pointer-events: auto;
}
.hud-bottom {
  bottom: 20px; left: 50%; transform: translateX(-50%);
  pointer-events: auto;
}
.hud-right {
  top: 20px; right: 20px;
  pointer-events: auto;
}

.panel {
  background: rgba(15, 15, 22, 0.92);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 12px;
  padding: 14px 18px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.4);
}

/* Title */
.title-panel {
  max-width: 380px;
}
.title-tag {
  font-size: 11px;
  letter-spacing: 0.15em;
  color: #888;
  text-transform: uppercase;
  margin-bottom: 6px;
}
.title-main {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 4px;
}
.title-sub {
  font-size: 13px;
  color: #aaa;
}

/* Variant tabs */
.variant-tabs {
  display: flex;
  gap: 6px;
  margin-top: 12px;
}
.tab {
  padding: 8px 14px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  color: #ccc;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
}
.tab:hover { background: rgba(255,255,255,0.1); color: #fff; }
.tab.active.baseline { background: #6b7280; color: #fff; border-color: #6b7280; }
.tab.active.hp { background: #c8553d; color: #fff; border-color: #c8553d; }
.tab.active.gd { background: #fd7e14; color: #fff; border-color: #fd7e14; }
.tab.active.pf { background: #10b981; color: #fff; border-color: #10b981; }

/* Layer toggles */
.toggle-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.toggle-row:last-child { margin-bottom: 0; }
.toggle-label {
  font-size: 13px;
  color: #ccc;
  min-width: 80px;
}
.toggle-btn {
  padding: 4px 12px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 6px;
  color: #999;
  font-size: 12px;
  cursor: pointer;
  font-family: inherit;
}
.toggle-btn.on { background: rgba(200,85,61,0.3); color: #fff; border-color: #c8553d; }

/* Bottom bar */
.bottom-bar {
  display: flex;
  gap: 16px;
  align-items: center;
}
.metric-mini {
  display: inline-flex;
  flex-direction: column;
  padding: 4px 14px;
  border-left: 2px solid rgba(255,255,255,0.1);
}
.metric-mini:first-child { border-left: none; }
.metric-mini .label {
  font-size: 10px;
  color: #888;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.metric-mini .value {
  font-size: 18px;
  font-weight: 600;
  color: #fff;
  margin-top: 2px;
}
.delta-pos { color: #10b981 !important; }
.delta-neg { color: #ef4444 !important; }

/* Tooltip */
#tooltip {
  position: absolute;
  pointer-events: none;
  background: rgba(15, 15, 22, 0.95);
  border: 1px solid rgba(255,255,255,0.1);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
  color: #fff;
  z-index: 200;
  display: none;
  max-width: 240px;
}

/* Legend (right panel) */
.legend {
  font-size: 12px;
  color: #ccc;
  line-height: 1.7;
}
.legend-row {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 4px;
}
.legend-row .dot {
  width: 12px; height: 12px; border-radius: 50%;
}
.legend-row .line {
  width: 24px; height: 3px;
}

/* Hint text */
.controls-hint {
  font-size: 11px;
  color: #777;
  margin-top: 8px;
  border-top: 1px solid rgba(255,255,255,0.05);
  padding-top: 8px;
  line-height: 1.5;
}
</style>
</head>
<body>

<div id="map-container">
  <div id="map"></div>
  <canvas id="deck-canvas"></canvas>
</div>

<div id="tooltip"></div>

<!-- Top-left: title + variant tabs -->
<div class="hud hud-top">
  <div class="panel title-panel">
    <div class="title-tag">Synthetic Socio Wind Tunnel · 3D 沙盘</div>
    <div class="title-main">Lane Cove · 14 天 4 组对照</div>
    <div class="title-sub" id="title-sub">{{ subtitle }}</div>

    <div class="variant-tabs" id="variant-tabs">
      <button class="tab baseline active" data-variant="variant_baseline">① 基线</button>
      <button class="tab hp" data-variant="variant_hyperlocal_push">② hp</button>
      <button class="tab gd" data-variant="variant_global_distraction">③ gd</button>
      <button class="tab pf" data-variant="variant_phone_friction">④ pf</button>
    </div>
  </div>
</div>

<!-- Top-right: layer toggles + legend -->
<div class="hud hud-right">
  <div class="panel" style="min-width: 220px;">
    <div class="toggle-row">
      <span class="toggle-label">3D 密度柱</span>
      <button class="toggle-btn on" id="toggle-hex">显示</button>
    </div>
    <div class="toggle-row">
      <span class="toggle-label">轨迹路径</span>
      <button class="toggle-btn on" id="toggle-path">显示</button>
    </div>
    <div class="toggle-row">
      <span class="toggle-label">末位点</span>
      <button class="toggle-btn" id="toggle-dot">隐藏</button>
    </div>

    <div class="controls-hint">
      <strong>操作</strong><br>
      鼠标 · 拖动平移 · 滚轮缩放<br>
      右键 · 旋转视角 (3D pitch)<br>
      点击柱 / 路径 · 看详情
    </div>
  </div>

  <div class="panel" style="margin-top: 12px; min-width: 220px;">
    <div class="legend">
      <strong style="display:block;margin-bottom:6px;">图例</strong>
      <div class="legend-row"><div class="dot" style="background:#fdba74;"></div>3D 柱: dwell 热度 (高 → 亮)</div>
      <div class="legend-row"><div class="line" style="background:currentColor;color:#888;"></div>路径: agent 14 天位置链</div>
      <div class="legend-row"><div class="dot" style="background:#fff;border:1px solid #c8553d;"></div>末位: day 13 终点</div>
    </div>
  </div>
</div>

<!-- Bottom: metrics summary -->
<div class="hud hud-bottom">
  <div class="panel bottom-bar" id="metric-bar">
    <!-- Populated dynamically -->
  </div>
</div>

<script>
const VIZ_DATA = {{ viz_data_json }};
const VARIANT_COLOR = {
  variant_baseline: [107, 114, 128],
  variant_hyperlocal_push: [200, 85, 61],
  variant_global_distraction: [253, 126, 20],
  variant_phone_friction: [16, 185, 129],
};
const VARIANT_LABEL = {
  variant_baseline: '① 什么都不推',
  variant_hyperlocal_push: '② 超在地推送 hp',
  variant_global_distraction: '③ 推全球新闻 gd',
  variant_phone_friction: '④ 减少手机吸力 pf',
};

let currentVariant = 'variant_baseline';
let showHex = true;
let showPath = true;
let showDot = false;

const center = VIZ_DATA.atlas.center;
const INITIAL_VIEW = {
  longitude: center.lng,
  latitude: center.lat,
  zoom: 14.5,
  pitch: 45,
  bearing: -20,
};

// ====== Maplibre base map ======
const map = new maplibregl.Map({
  container: 'map',
  style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
  center: [INITIAL_VIEW.longitude, INITIAL_VIEW.latitude],
  zoom: INITIAL_VIEW.zoom,
  pitch: INITIAL_VIEW.pitch,
  bearing: INITIAL_VIEW.bearing,
  antialias: true,
});

// ====== Deck.gl overlay ======
const { Deck, MapView } = deck;
const deckOverlay = new Deck({
  canvas: 'deck-canvas',
  initialViewState: INITIAL_VIEW,
  controller: true,
  views: new MapView({ repeat: true }),
  layers: [],
  onViewStateChange: ({ viewState }) => {
    map.jumpTo({
      center: [viewState.longitude, viewState.latitude],
      zoom: viewState.zoom,
      pitch: viewState.pitch,
      bearing: viewState.bearing,
    });
  },
  getTooltip: ({ object, layer }) => {
    if (!object) return null;
    if (layer.id.startsWith('hex-')) {
      const points = object.points || [];
      const totalDwell = points.reduce((s, p) => s + (p.source?.weight || 0), 0);
      const names = points.slice(0, 3).map(p => p.source?.name).filter(Boolean);
      return {
        html: `<strong>${names.join(' / ') || '区域'}</strong><br>
               总 dwell: ${Math.round(totalDwell)} ticks<br>
               含 ${points.length} 个 location`,
        style: { background: 'rgba(15,15,22,0.95)', color: '#fff',
                 borderRadius: '6px', padding: '8px 12px', fontSize: '12px' },
      };
    }
    if (layer.id.startsWith('path-')) {
      return {
        html: `<strong>agent ${object.agent_id}</strong><br>
               走过 ${object.unique_locs} 个不同 location<br>
               14 天位置变化`,
        style: { background: 'rgba(15,15,22,0.95)', color: '#fff',
                 borderRadius: '6px', padding: '8px 12px', fontSize: '12px' },
      };
    }
    return null;
  },
});

function buildLayers() {
  const variantData = VIZ_DATA.variants[currentVariant];
  if (!variantData) return [];
  const baseColor = VARIANT_COLOR[currentVariant];
  const layers = [];

  // HexagonLayer for 3D dwell density
  if (showHex) {
    layers.push(new deck.HexagonLayer({
      id: `hex-${currentVariant}`,
      data: variantData.hex_data,
      getPosition: d => d.position,
      getElevationWeight: d => d.weight,
      elevationScale: 0.05,
      elevationRange: [0, 1000],
      extruded: true,
      radius: 80,
      coverage: 0.92,
      colorRange: [
        [30, 58, 95, 100],
        [76, 102, 124, 140],
        [130, 142, 145, 180],
        [196, 173, 153, 210],
        [250, 200, 130, 230],
        [253, 126, 20, 255],
      ],
      opacity: 0.85,
      pickable: true,
      material: {
        ambient: 0.6, diffuse: 0.7, shininess: 16,
        specularColor: [255, 240, 200],
      },
    }));
  }

  // PathLayer for agent trajectories
  if (showPath) {
    layers.push(new deck.PathLayer({
      id: `path-${currentVariant}`,
      data: variantData.trajectories,
      getPath: d => d.path,
      getColor: d => [...baseColor, 150],
      getWidth: 3,
      widthMinPixels: 2,
      widthMaxPixels: 6,
      pickable: true,
      capRounded: true,
      jointRounded: true,
      opacity: 0.6,
    }));
  }

  // ScatterplotLayer for final positions (day 13)
  if (showDot) {
    const finalPositions = variantData.trajectories.map(t => ({
      ...t,
      position: t.path[t.path.length - 1],
    }));
    layers.push(new deck.ScatterplotLayer({
      id: `dot-${currentVariant}`,
      data: finalPositions,
      getPosition: d => d.position,
      getFillColor: [...baseColor, 200],
      getLineColor: [255, 255, 255, 200],
      getLineWidth: 1.5,
      getRadius: 30,
      radiusMinPixels: 4,
      radiusMaxPixels: 10,
      stroked: true,
      pickable: true,
    }));
  }

  return layers;
}

function refreshLayers() {
  deckOverlay.setProps({ layers: buildLayers() });
  refreshMetrics();
}

function refreshMetrics() {
  const v = VIZ_DATA.variants[currentVariant];
  const baseline = VIZ_DATA.variants['variant_baseline'];
  const bar = document.getElementById('metric-bar');
  if (!v || !baseline) { bar.innerHTML = ''; return; }

  const variantEnc = v.encounter_total;
  const baseEnc = baseline.encounter_total;
  const deltaEnc = baseEnc === 0 ? 0 : (variantEnc - baseEnc) / baseEnc * 100;
  const cls = deltaEnc > 0 ? 'delta-pos' : (deltaEnc < 0 ? 'delta-neg' : '');
  const sign = deltaEnc >= 0 ? '+' : '';

  const traj = v.traj_dev_protag !== null && v.traj_dev_protag !== undefined
    ? `${v.traj_dev_protag.toFixed(0)}m` : '—';
  const cost = v.cost_total > 0 ? `$${v.cost_total.toFixed(2)}` : '—';
  const trajClass = '';

  bar.innerHTML = `
    <div class="metric-mini">
      <span class="label">当前 variant</span>
      <span class="value" style="font-size:14px;">${VARIANT_LABEL[currentVariant]}</span>
    </div>
    <div class="metric-mini">
      <span class="label">总偶遇</span>
      <span class="value">${Math.round(variantEnc / 1000)}k</span>
    </div>
    <div class="metric-mini">
      <span class="label">vs 基线</span>
      <span class="value ${cls}">${currentVariant === 'variant_baseline' ? '—' : sign + deltaEnc.toFixed(1) + '%'}</span>
    </div>
    <div class="metric-mini">
      <span class="label">轨迹偏离</span>
      <span class="value">${traj}</span>
    </div>
    <div class="metric-mini">
      <span class="label">replan</span>
      <span class="value">${v.replan_count}</span>
    </div>
    <div class="metric-mini">
      <span class="label">cost</span>
      <span class="value">${cost}</span>
    </div>
  `;
}

// ====== UI wiring ======
document.querySelectorAll('#variant-tabs .tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#variant-tabs .tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentVariant = btn.dataset.variant;
    refreshLayers();
  });
});

function setupToggle(btnId, stateRef) {
  const btn = document.getElementById(btnId);
  btn.addEventListener('click', () => {
    if (stateRef.value) {
      stateRef.value = false;
      btn.classList.remove('on');
      btn.textContent = '隐藏';
    } else {
      stateRef.value = true;
      btn.classList.add('on');
      btn.textContent = '显示';
    }
    refreshLayers();
  });
}

const hexRef = { get value() { return showHex; }, set value(v) { showHex = v; } };
const pathRef = { get value() { return showPath; }, set value(v) { showPath = v; } };
const dotRef = { get value() { return showDot; }, set value(v) { showDot = v; } };
setupToggle('toggle-hex', hexRef);
setupToggle('toggle-path', pathRef);
setupToggle('toggle-dot', dotRef);

// Initial render
map.on('load', () => {
  refreshLayers();
});
</script>

</body>
</html>
"""


def build(suite_dir: Path, atlas_path: Path, proj_path: Path,
          out_path: Path) -> None:
    by_variant = _load_suite(suite_dir)
    if not by_variant:
        print(f"error: no variant_*/seed_*.json in {suite_dir}", file=sys.stderr)
        sys.exit(2)

    atlas_summary = _load_atlas_summary(atlas_path, proj_path)
    locations = atlas_summary["locations"]

    # Build the real NavigationService using cached Lane Cove atlas so
    # trajectory paths follow the actual street network, not straight lines.
    print(f"[build_3d] Loading atlas + building NavigationService...")
    from synthetic_socio_wind_tunnel.cartography.lanecove import (
        create_atlas_from_osm,
    )
    from synthetic_socio_wind_tunnel.ledger import Ledger
    from synthetic_socio_wind_tunnel.engine.navigation import NavigationService

    atlas = create_atlas_from_osm()
    ledger = Ledger()
    nav_router = NavigationService(atlas=atlas, ledger=ledger)
    print(f"[build_3d] NavigationService ready, computing trajectories…")

    variants_payload = {}
    for name, seeds in by_variant.items():
        trajectories = _build_agent_trajectories(
            seeds, locations, nav_router, max_agents=100,
        )
        hex_data = _build_hex_data(seeds, locations, top_n=200)
        rm = seeds[0]["run_metrics"]
        variants_payload[name] = {
            "encounter_total": rm["encounter_stats"]["total"],
            "traj_dev_protag": rm.get("trajectory_deviation_m"),
            "traj_dev_all": rm.get("trajectory_deviation_m_all"),
            "replan_count": rm.get("extensions", {}).get("replan_count", 0),
            "cost_total": (rm.get("cost_breakdown") or {}).get("total", 0),
            "weak_tie": rm.get("weak_tie_formation_count", 0),
            "trajectories": trajectories,
            "hex_data": hex_data,
            "n_seeds": len(seeds),
        }

    sample = next(iter(by_variant.values()))[0]
    rep = sample["run_metrics"].get("extensions", {}).get(
        "reproducibility_lock", {},
    )
    n_seeds = max(v.get("n_seeds", 0) for v in variants_payload.values())
    subtitle = (
        f"{n_seeds} seed × 14 day · provider={rep.get('provider', '?')} · "
        f"model={rep.get('model_version', '?')}"
    )

    viz_data = {
        "atlas": atlas_summary,
        "variants": variants_payload,
    }

    html = (
        HTML_TEMPLATE
        .replace("{{ subtitle }}", subtitle)
        .replace("{{ viz_data_json }}", json.dumps(viz_data, ensure_ascii=False))
    )
    out_path.write_text(html, encoding="utf-8")
    size_kb = len(html.encode()) / 1024
    n_traj = sum(len(v["trajectories"]) for v in variants_payload.values())
    n_hex = sum(len(v["hex_data"]) for v in variants_payload.values())
    print(f"✅ wrote {out_path} ({size_kb:.1f} KB)")
    print(f"   {len(variants_payload)} variants · "
          f"{n_traj} trajectories · {n_hex} hex points · "
          f"{len(locations)} locations indexed")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("suite_dir", type=Path)
    p.add_argument("--atlas", type=Path, default=Path("data/lanecove_atlas.json"))
    p.add_argument("--proj-center", type=Path,
                   default=Path("data/lanecove_proj_center.json"))
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    if not args.suite_dir.is_dir():
        print(f"error: not a directory: {args.suite_dir}", file=sys.stderr)
        return 2

    out = args.out or args.suite_dir / "3d_dashboard.html"
    build(args.suite_dir, args.atlas, args.proj_center, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
