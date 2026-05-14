"""Self-contained 2D SVG replay dashboard for 14-day agent activity.

Inherits the map_explorer SVG-polygon style (real Lane Cove building shapes)
but adds time-slider replay using per-tick position traces.

Key features:
- Real atlas polygons (residential / cafe / park / etc. with type colors)
- Day slider 1-N to scrub through days
- Per-tick slider 0-287 within each day for fine-grained replay
- Play/pause animation
- Variant tabs (baseline / hp / gd / pf)
- Click agent dot → highlight its trajectory for the day

Usage:
    python3 tools/build_2d_replay.py <suite_dir> [--out replay.html]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_atlas_polygons(atlas_path: Path) -> dict:
    """Extract real geometry from cached atlas JSON."""
    with atlas_path.open(encoding="utf-8") as fh:
        atlas = json.load(fh)

    locations: list[dict] = []
    bounds_min = [float("inf"), float("inf")]
    bounds_max = [float("-inf"), float("-inf")]

    def _polygon_to_xy(poly: dict) -> list[list[float]]:
        verts = poly.get("vertices") or poly.get("coords") or []
        out: list[list[float]] = []
        for v in verts:
            if isinstance(v, dict):
                out.append([v.get("x", 0.0), v.get("y", 0.0)])
            else:
                out.append([v[0], v[1]])
        return out

    def _update_bounds(xy_list: list[list[float]]) -> None:
        for x, y in xy_list:
            if x < bounds_min[0]: bounds_min[0] = x
            if y < bounds_min[1]: bounds_min[1] = y
            if x > bounds_max[0]: bounds_max[0] = x
            if y > bounds_max[1]: bounds_max[1] = y

    # Buildings — for tracjectory rendering use `entrance_coord` (door
    # position on polygon edge) rather than polygon center so polylines
    # don't "stab through" buildings. Polygon center is still kept for
    # tooltips / dwell-circle positioning.
    buildings = atlas.get("buildings", {})
    if isinstance(buildings, dict):
        for bid, data in buildings.items():
            pts = _polygon_to_xy(data.get("polygon", {}))
            if not pts:
                continue
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            _update_bounds(pts)
            ent = data.get("entrance_coord")
            entrance = (
                [ent.get("x", cx), ent.get("y", cy)] if ent else [cx, cy]
            )
            locations.append({
                "id": bid,
                "name": data.get("name", bid),
                "kind": "building",
                "subtype": data.get("building_type", "building"),
                "polygon": pts,
                "center": [cx, cy],
                "entrance": entrance,
            })

    # Outdoor areas
    outdoor = atlas.get("outdoor_areas", {})
    if isinstance(outdoor, dict):
        for aid, data in outdoor.items():
            pts = _polygon_to_xy(data.get("polygon", {}))
            if not pts:
                continue
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            _update_bounds(pts)
            atype = data.get("area_type", "outdoor")
            locations.append({
                "id": aid,
                "name": data.get("name", aid),
                "kind": "outdoor",
                "subtype": atype,
                "polygon": pts,
                "center": [cx, cy],
                "entrance": [cx, cy],
            })

    return {
        "bounds_min": bounds_min,
        "bounds_max": bounds_max,
        "locations": locations,
    }


def _load_suite_positions(suite_dir: Path) -> dict[str, dict]:
    """Load per-variant position traces from seed_X_positions.json files."""
    by_variant: dict[str, dict] = {}
    for vd in sorted(suite_dir.iterdir()):
        if not vd.is_dir() or not vd.name.startswith("variant_"):
            continue
        # Find first seed's position trace (single-seed dashboards for now)
        pos_files = sorted(vd.glob("seed_*_positions.json"))
        if not pos_files:
            continue
        with pos_files[0].open(encoding="utf-8") as fh:
            trace = json.load(fh)
        by_variant[vd.name] = {
            "n_agents": trace.get("n_agents", 0),
            "n_changes": trace.get("n_changes", 0),
            "changes": trace.get("changes", []),
        }
    return by_variant


def _load_suite_metrics(suite_dir: Path) -> dict[str, dict]:
    """Load per-variant run_metrics from seed_X.json (skip *_positions)."""
    by_variant: dict[str, dict] = {}
    for vd in sorted(suite_dir.iterdir()):
        if not vd.is_dir() or not vd.name.startswith("variant_"):
            continue
        for sf in sorted(vd.glob("seed_*.json")):
            if "_positions" in sf.stem:
                continue
            with sf.open(encoding="utf-8") as fh:
                d = json.load(fh)
            rm = d.get("run_metrics", {})
            # space_activation: location_id → dwell_ticks across all days/agents
            # Used by Overview mode to render proportional dwell circles.
            space_act = rm.get("space_activation", {}) or {}
            # Top-N to keep file size reasonable
            top_dwell = sorted(
                space_act.items(), key=lambda kv: -kv[1],
            )[:200]
            by_variant[vd.name] = {
                "encounter_total": rm.get("encounter_stats", {}).get("total", 0),
                "weak_tie": rm.get("weak_tie_formation_count", 0),
                "num_days": rm.get("num_days", 0),
                "feed_stats": rm.get("feed_stats", {}),
                "space_activation_top": top_dwell,  # [[loc_id, ticks], ...]
            }
            break
    return by_variant


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>SSWT · 14 天 agent 活动 replay</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; overflow: hidden; background: #1a1d2e;
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
  color: #d8dee8; }
#wrap { display: grid; grid-template-rows: auto 1fr auto; height: 100vh; }

header {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 16px;
  background: rgba(0,0,0,0.4); border-bottom: 1px solid rgba(255,255,255,0.06);
}
header h1 { font-size: 14px; font-weight: 600; color: #fff;
  letter-spacing: 0.05em; }
header .sub { font-size: 12px; color: #888; margin-left: 6px; }

.tabs { display: flex; gap: 4px; margin-left: auto; }
.tab {
  padding: 5px 12px; background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.06); border-radius: 6px;
  color: #aaa; font-size: 12px; cursor: pointer; font-family: inherit;
}
.tab:hover { background: rgba(255,255,255,0.1); color: #fff; }
.tab.active { background: rgba(232,160,112,0.18); color: #fff;
  border-color: #e8a070; }
.tab.active[data-v=variant_baseline] { background: rgba(140,150,170,0.25);
  border-color: #7a8090; }
.tab.active[data-v=variant_hyperlocal_push] { background: rgba(200,85,61,0.25);
  border-color: #c8553d; }
.tab.active[data-v=variant_global_distraction] { background: rgba(253,126,20,0.25);
  border-color: #fd7e14; }
.tab.active[data-v=variant_phone_friction] { background: rgba(16,185,129,0.25);
  border-color: #10b981; }

main { position: relative; overflow: hidden; background: #1a1d2e; }
#map-svg { width: 100%; height: 100%; cursor: grab; user-select: none; }
#map-svg:active { cursor: grabbing; }

footer {
  padding: 12px 16px; background: rgba(0,0,0,0.4);
  border-top: 1px solid rgba(255,255,255,0.06);
  display: grid; grid-template-columns: auto 1fr auto auto auto auto;
  align-items: center; gap: 16px;
}
.ctrl-label { font-size: 11px; color: #888; letter-spacing: 0.08em;
  text-transform: uppercase; }
.slider-wrap { display: flex; align-items: center; gap: 8px; min-width: 0; }
input[type=range] { flex: 1; min-width: 100px; accent-color: #e8a070; }
.day-readout, .tick-readout { font-size: 12px; color: #fff;
  font-family: 'Courier New', monospace; min-width: 80px; }

button.ctrl-btn {
  padding: 5px 12px; background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1); border-radius: 5px;
  color: #d8dee8; font-size: 12px; cursor: pointer; font-family: inherit;
}
button.ctrl-btn:hover { background: rgba(255,255,255,0.12); }
button.ctrl-btn.playing { background: rgba(232,160,112,0.2);
  border-color: #e8a070; }

.kpi-bar {
  position: absolute; top: 12px; right: 12px;
  display: flex; gap: 12px;
  background: rgba(15,15,22,0.85); backdrop-filter: blur(8px);
  padding: 10px 14px; border-radius: 8px;
  border: 1px solid rgba(255,255,255,0.06);
}
.kpi-item { display: flex; flex-direction: column; }
.kpi-item .label { font-size: 10px; color: #888;
  letter-spacing: 0.08em; text-transform: uppercase; }
.kpi-item .value { font-size: 16px; font-weight: 600; color: #fff; }

.legend {
  position: absolute; bottom: 12px; left: 12px;
  background: rgba(15,15,22,0.85); padding: 8px 12px;
  border-radius: 6px; font-size: 11px; line-height: 1.7;
  border: 1px solid rgba(255,255,255,0.06);
}
.legend .row { display: flex; align-items: center; gap: 6px; }
.legend .swatch { width: 12px; height: 12px; border-radius: 2px; }

#tooltip {
  position: fixed; pointer-events: none;
  background: rgba(15,15,22,0.95); color: #fff;
  padding: 6px 10px; border-radius: 4px;
  font-size: 11px; display: none; z-index: 100;
  border: 1px solid rgba(255,255,255,0.1);
}

.agent-dot { fill: #ffd860; stroke: #1a1d2e;
  vector-effect: non-scaling-stroke; stroke-width: 1.5;
  transition: cx 0.18s linear, cy 0.18s linear;
  filter: drop-shadow(0 0 4px rgba(255,216,96,0.8)); }
.agent-dot.protag { fill: #ff5a5a; stroke-width: 2.0;
  filter: drop-shadow(0 0 6px rgba(255,90,90,0.9)); }
.agent-tail { fill: none; stroke: #ffd860; stroke-opacity: 0.55;
  vector-effect: non-scaling-stroke; stroke-width: 1.2;
  stroke-linecap: round; stroke-linejoin: round; }
.agent-tail.protag { stroke: #ff5a5a; stroke-opacity: 0.7;
  stroke-width: 2.0; }

/* Overview mode (14-day synthesis) styles */
.overview-trail { fill: none; stroke-opacity: 0.18;
  vector-effect: non-scaling-stroke; stroke-width: 1.0;
  stroke-linecap: round; stroke-linejoin: round; }
.overview-trail.protag { stroke-opacity: 0.45; stroke-width: 1.6; }
.dwell-circle { fill-opacity: 0.55; stroke: #1a1d2e;
  vector-effect: non-scaling-stroke; stroke-width: 0.8; }
.ctrl-btn.mode-active { background: rgba(120,200,160,0.25);
  border-color: #80c8b0; color: #fff; }
footer.overview-mode #day-slider,
footer.overview-mode #tick-slider,
footer.overview-mode #play-btn,
footer.overview-mode #speed-btn,
footer.overview-mode #reset-btn,
footer.overview-mode .day-readout,
footer.overview-mode .tick-readout {
  opacity: 0.35; pointer-events: none;
}
</style>
</head>
<body>

<div id="wrap">
  <header>
    <h1>Lane Cove · 14 天 agent 活动 replay</h1>
    <span class="sub" id="subtitle">{{ subtitle }}</span>
    <div class="tabs" id="variant-tabs"></div>
  </header>

  <main>
    <svg id="map-svg" preserveAspectRatio="xMidYMid meet"></svg>

    <div class="kpi-bar" id="kpi-bar"></div>

    <div class="legend">
      <div class="row"><div class="swatch" style="background:#90b8d8;"></div>residential</div>
      <div class="row"><div class="swatch" style="background:#e8a070;"></div>cafe / restaurant</div>
      <div class="row"><div class="swatch" style="background:#e0d060;"></div>shop</div>
      <div class="row"><div class="swatch" style="background:#80c8b0;"></div>school</div>
      <div class="row"><div class="swatch" style="background:#8898c0;"></div>office</div>
      <div class="row"><div class="swatch" style="background:#58b870;"></div>park / playground</div>
      <div class="row"><div class="swatch" style="background:#586070;"></div>street</div>
      <div class="row"><div class="swatch" style="background:#ffd860;"></div>agent (scripted)</div>
      <div class="row"><div class="swatch" style="background:#ff5a5a;"></div>protagonist</div>
    </div>
  </main>

  <footer>
    <span class="ctrl-label">DAY</span>
    <div class="slider-wrap">
      <input type="range" id="day-slider" min="0" max="13" value="0">
      <span class="day-readout" id="day-readout">Day 1 / 14</span>
    </div>
    <span class="ctrl-label">TICK</span>
    <div class="slider-wrap" style="min-width:180px;">
      <input type="range" id="tick-slider" min="0" max="287" value="0">
      <span class="tick-readout" id="tick-readout">00:00</span>
    </div>
    <button class="ctrl-btn" id="mode-btn">📊 全景</button>
    <button class="ctrl-btn" id="play-btn">▶ Play</button>
    <button class="ctrl-btn" id="speed-btn">1×</button>
    <button class="ctrl-btn" id="reset-btn">Reset</button>
  </footer>
</div>

<div id="tooltip"></div>

<script>
const DATA = {{ viz_data_json }};
const TYPE_COLOR = {
  residential: "#90b8d8",
  cafe: "#e8a070", restaurant: "#e8a070", bar: "#d88060",
  shop: "#e0d060", commercial: "#c8b860",
  office: "#8898c0", school: "#80c8b0",
  hospital: "#f08080", worship: "#b0a0e0",
  hotel: "#98a8d0", entertainment: "#d888b8",
  community: "#70c090",
  industrial: "#888890", utility: "#707078",
  street: "#586070",
  park: "#58b870", garden: "#68c080", playground: "#78c068",
};
function locColor(s) { return TYPE_COLOR[s] || "#8090a0"; }

const TICKS_PER_DAY = 288;       // 5-min ticks × 24h
const SVG_NS = "http://www.w3.org/2000/svg";

const state = {
  variant: Object.keys(DATA.variants)[0],
  day: 0,
  tick: 0,
  playing: false,
  speed: 1,
  mode: "replay",  // "replay" or "overview"
  // viewBox
  view: { x: 0, y: 0, w: 0, h: 0 },
  // pre-built per-variant lookup
  // agentLocation[variant][agent_id] = current_loc_id (mutated as we replay)
  agentLocation: {},
  // changesByAbsTick[variant] = sorted list of (abs_tick, agent_id, loc_id)
  changesByAbsTick: {},
  // Cache: locationsById
  locationsById: {},
};

// ─── Init ────────────────────────────────────────────────────────────────────
function init() {
  // Index locations
  for (const loc of DATA.atlas.locations) {
    state.locationsById[loc.id] = loc;
  }
  // Pre-sort change events per variant by absolute tick
  for (const [v, payload] of Object.entries(DATA.variants)) {
    const enriched = payload.changes.map(c => ({
      abs_tick: c.day * TICKS_PER_DAY + c.tick,
      day: c.day, tick: c.tick,
      agent_id: c.agent_id, location_id: c.location_id,
    }));
    enriched.sort((a, b) => a.abs_tick - b.abs_tick);
    state.changesByAbsTick[v] = enriched;
  }

  setupViewBox();
  setupTabs();
  drawMap();
  setupControls();
  document.getElementById("mode-btn").addEventListener("click", toggleMode);
  renderCurrent();
  updateKPI();
}

function setupViewBox() {
  const [minX, minY] = DATA.atlas.bounds_min;
  const [maxX, maxY] = DATA.atlas.bounds_max;
  const w = maxX - minX;
  const h = maxY - minY;
  // SVG y-axis is flipped vs map coords; we'll apply transform=scale(1,-1)
  const pad = Math.max(w, h) * 0.02;
  state.view = { x: minX - pad, y: minY - pad,
                 w: w + 2 * pad, h: h + 2 * pad };
  const svg = document.getElementById("map-svg");
  svg.setAttribute("viewBox",
    `${state.view.x} ${state.view.y} ${state.view.w} ${state.view.h}`);
}

function setupTabs() {
  const tabs = document.getElementById("variant-tabs");
  const variantOrder = [
    "variant_baseline", "variant_hyperlocal_push",
    "variant_global_distraction", "variant_phone_friction",
  ];
  const label = {
    "variant_baseline": "① 基线",
    "variant_hyperlocal_push": "② hp",
    "variant_global_distraction": "③ gd",
    "variant_phone_friction": "④ pf",
  };
  for (const v of variantOrder) {
    if (!DATA.variants[v]) continue;
    const btn = document.createElement("button");
    btn.className = "tab";
    btn.dataset.v = v;
    btn.textContent = label[v] || v;
    if (v === state.variant) btn.classList.add("active");
    btn.addEventListener("click", () => switchVariant(v));
    tabs.appendChild(btn);
  }
}

function switchVariant(v) {
  state.variant = v;
  document.querySelectorAll(".tab").forEach(b => {
    b.classList.toggle("active", b.dataset.v === v);
  });
  state.agentLocation = {};
  renderCurrent();
  updateKPI();
}

function renderCurrent() {
  if (state.mode === "overview") drawOverview();
  else drawAgents();
}

function toggleMode() {
  state.mode = state.mode === "replay" ? "overview" : "replay";
  const btn = document.getElementById("mode-btn");
  const footer = document.querySelector("footer");
  if (state.mode === "overview") {
    btn.textContent = "🎬 Replay";
    btn.classList.add("mode-active");
    footer.classList.add("overview-mode");
    // Stop playback if running
    const playBtn = document.getElementById("play-btn");
    if (state.playing && playBtn) playBtn.click();
  } else {
    btn.textContent = "📊 全景";
    btn.classList.remove("mode-active");
    footer.classList.remove("overview-mode");
  }
  renderCurrent();
}

// ─── Map render ──────────────────────────────────────────────────────────────
function drawMap() {
  const svg = document.getElementById("map-svg");
  // Outer group flipped on Y (atlas y points up; SVG y points down)
  const wrap = document.createElementNS(SVG_NS, "g");
  wrap.setAttribute("transform",
    `translate(0, ${state.view.y + state.view.y + state.view.h}) scale(1, -1)`);
  svg.appendChild(wrap);

  // Background fill
  const bg = document.createElementNS(SVG_NS, "rect");
  bg.setAttribute("x", state.view.x);
  bg.setAttribute("y", state.view.y);
  bg.setAttribute("width", state.view.w);
  bg.setAttribute("height", state.view.h);
  bg.setAttribute("fill", "#1a1d2e");
  wrap.appendChild(bg);

  // Render outdoor first (background)
  const gOut = document.createElementNS(SVG_NS, "g");
  gOut.setAttribute("id", "g-outdoor");
  const gBld = document.createElementNS(SVG_NS, "g");
  gBld.setAttribute("id", "g-building");
  wrap.appendChild(gOut);
  wrap.appendChild(gBld);

  for (const loc of DATA.atlas.locations) {
    if (!loc.polygon.length) continue;
    const poly = document.createElementNS(SVG_NS, "polygon");
    const pts = loc.polygon.map(p => `${p[0]},${p[1]}`).join(" ");
    poly.setAttribute("points", pts);
    poly.setAttribute("fill", locColor(loc.subtype));
    poly.setAttribute("fill-opacity",
      loc.subtype === "street" ? "0.32" : "0.62");
    poly.setAttribute("stroke", "#0e1018");
    poly.setAttribute("stroke-width", "0.4");
    poly.setAttribute("data-id", loc.id);
    poly.style.pointerEvents = "auto";
    poly.addEventListener("mouseenter", (e) => showTooltip(e, loc));
    poly.addEventListener("mouseleave", hideTooltip);
    if (loc.kind === "building") gBld.appendChild(poly);
    else gOut.appendChild(poly);
  }

  // Agent layer on top
  const gAgent = document.createElementNS(SVG_NS, "g");
  gAgent.setAttribute("id", "g-agent");
  wrap.appendChild(gAgent);
}

function showTooltip(e, loc) {
  const tip = document.getElementById("tooltip");
  tip.style.display = "block";
  tip.innerHTML = `<b>${loc.name}</b><br>${loc.kind} · ${loc.subtype}`;
  tip.style.left = (e.clientX + 10) + "px";
  tip.style.top = (e.clientY + 10) + "px";
}
function hideTooltip() {
  document.getElementById("tooltip").style.display = "none";
}

// ─── Agent replay ────────────────────────────────────────────────────────────
// Per-agent history snapshot up to absTick: ordered list of location_ids.
// Used both for current-position lookup AND tail rendering.
function computeAgentHistories(absTick, tailLength = 8) {
  const histories = {};  // agent_id → [loc_id, ...] most recent last
  const changes = state.changesByAbsTick[state.variant] || [];
  for (const c of changes) {
    if (c.abs_tick > absTick) break;
    if (!histories[c.agent_id]) histories[c.agent_id] = [];
    const hist = histories[c.agent_id];
    // Skip consecutive duplicates (same location twice)
    if (hist.length && hist[hist.length - 1] === c.location_id) continue;
    hist.push(c.location_id);
    if (hist.length > tailLength) hist.shift();
  }
  return histories;
}

// Marker radius in atlas-meter units. Lane Cove ~4km wide; r=18m ≈ noticeable
// against typical 30-50m building footprints.
const AGENT_R = 18;

// Compute the rendered point for `loc`, biased toward `prev`/`next` so a
// polyline through a building exits at the polygon vertex nearest the
// neighbour (not at the polygon's geometric interior centroid).
//
// For outdoor areas the centre is fine; for buildings we snap to the
// closest polygon vertex relative to (prev.center + next.center) / 2.
function renderPoint(loc, prev, next) {
  if (loc.kind !== "building" || !loc.polygon || loc.polygon.length === 0) {
    return loc.center;
  }
  const tx = (prev.center[0] + next.center[0]) / 2;
  const ty = (prev.center[1] + next.center[1]) / 2;
  let best = loc.polygon[0];
  let bestD2 = Infinity;
  for (const v of loc.polygon) {
    const dx = v[0] - tx, dy = v[1] - ty;
    const d2 = dx * dx + dy * dy;
    if (d2 < bestD2) { bestD2 = d2; best = v; }
  }
  return best;
}

// ─── Overview (14-day synthesis) ─────────────────────────────────────────────
// Compute full per-agent trajectory over all changes, dedup consecutive
// same-location, return {agent_id: [loc_id, ...]}
function computeFullTrajectories() {
  const trajs = {};
  const changes = state.changesByAbsTick[state.variant] || [];
  for (const c of changes) {
    if (!trajs[c.agent_id]) trajs[c.agent_id] = [];
    const hist = trajs[c.agent_id];
    if (hist.length && hist[hist.length - 1] === c.location_id) continue;
    hist.push(c.location_id);
  }
  return trajs;
}

function drawOverview() {
  const g = document.getElementById("g-agent");
  if (!g) return;
  while (g.firstChild) g.removeChild(g.firstChild);

  // Pass 1: every agent's full 14-day trajectory as low-alpha spaghetti
  const trajs = computeFullTrajectories();
  const allAgents = Object.keys(trajs).sort();
  const protagCount = Math.max(1, Math.floor(allAgents.length / 10));
  const protagSet = new Set(allAgents.slice(0, protagCount));

  // Per-agent color palette so overlapping trails reveal structure
  // (16 distinct hues cycled through golden-angle for max separation)
  const palette = [];
  const golden = 137.508;
  for (let i = 0; i < 16; i++) {
    palette.push(`hsl(${(i * golden) % 360}, 65%, 60%)`);
  }
  for (const [agentId, hist] of Object.entries(trajs)) {
    if (hist.length < 2) continue;
    const locs = hist
      .map(lid => state.locationsById[lid])
      .filter(loc => loc);
    if (locs.length < 2) continue;
    const pts = locs.map((loc, i) => {
      const prev = locs[i - 1] || loc;
      const next = locs[i + 1] || loc;
      return renderPoint(loc, prev, next);
    });
    const pointsStr = pts.map(p => `${p[0]},${p[1]}`).join(" ");
    if (!pointsStr) continue;
    const path = document.createElementNS(SVG_NS, "polyline");
    path.setAttribute("points", pointsStr);
    path.classList.add("overview-trail");
    const hash = agentId.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
    const color = protagSet.has(agentId)
      ? "#ff5a5a"
      : palette[hash % palette.length];
    path.setAttribute("stroke", color);
    if (protagSet.has(agentId)) path.classList.add("protag");
    g.appendChild(path);
  }

  // Pass 2: dwell circles (top-N locations by total dwell ticks)
  const dwell = (DATA.metrics[state.variant] || {}).space_activation_top || [];
  if (dwell.length) {
    // Normalize to log scale for circle radius
    const maxDwell = dwell[0][1] || 1;
    for (const [locId, ticks] of dwell.slice(0, 80)) {
      const loc = state.locationsById[locId];
      if (!loc) continue;
      const radius = 8 + 50 * (Math.log(1 + ticks) / Math.log(1 + maxDwell));
      const c = document.createElementNS(SVG_NS, "circle");
      c.setAttribute("cx", loc.center[0]);
      c.setAttribute("cy", loc.center[1]);
      c.setAttribute("r", radius);
      c.setAttribute("fill", locColor(loc.subtype));
      c.classList.add("dwell-circle");
      c.addEventListener("mouseenter", (e) => showDwellTooltip(e, loc, ticks));
      c.addEventListener("mouseleave", hideTooltip);
      g.appendChild(c);
    }
  }
}

function showDwellTooltip(e, loc, ticks) {
  const tip = document.getElementById("tooltip");
  tip.style.display = "block";
  const hours = (ticks * 5) / 60;
  tip.innerHTML = `<b>${loc.name}</b><br>${loc.kind} · ${loc.subtype}<br>
    14-day dwell: <b>${Math.round(ticks).toLocaleString()}</b> ticks
    (~${hours.toFixed(0)} agent-hours)`;
  tip.style.left = (e.clientX + 10) + "px";
  tip.style.top = (e.clientY + 10) + "px";
}

function drawAgents() {
  const g = document.getElementById("g-agent");
  if (!g) return;
  while (g.firstChild) g.removeChild(g.firstChild);

  const absTick = state.day * TICKS_PER_DAY + state.tick;
  const histories = computeAgentHistories(absTick);

  // protagonist heuristic: agent_id sort first 10% (sample_population
  // convention) — position trace doesn't carry is_protagonist flag
  const allAgents = Object.keys(histories).sort();
  const protagCount = Math.max(1, Math.floor(allAgents.length / 10));
  const protagSet = new Set(allAgents.slice(0, protagCount));

  // Pass 1: tails (drawn first so dots overlay them).
  // For each polyline vertex, snap to polygon-edge point closest to its
  // neighbours so lines actually exit buildings at the perimeter, not from
  // the interior. (atlas.entrance_coord is mostly interior, not boundary.)
  for (const [agentId, hist] of Object.entries(histories)) {
    if (hist.length < 2) continue;
    const locs = hist
      .map(lid => state.locationsById[lid])
      .filter(loc => loc);
    if (locs.length < 2) continue;
    const pts = locs.map((loc, i) => {
      const prev = locs[i - 1] || loc;
      const next = locs[i + 1] || loc;
      return renderPoint(loc, prev, next);
    });
    const pointsStr = pts.map(p => `${p[0]},${p[1]}`).join(" ");
    if (!pointsStr) continue;
    const path = document.createElementNS(SVG_NS, "polyline");
    path.setAttribute("points", pointsStr);
    path.classList.add("agent-tail");
    if (protagSet.has(agentId)) path.classList.add("protag");
    g.appendChild(path);
  }

  // Pass 2: current-position dot at the building's polygon-edge point
  // facing the previous (incoming) location.
  for (const [agentId, hist] of Object.entries(histories)) {
    const locId = hist[hist.length - 1];
    const loc = state.locationsById[locId];
    if (!loc) continue;
    const prevId = hist.length >= 2 ? hist[hist.length - 2] : null;
    const prevLoc = prevId ? state.locationsById[prevId] : loc;
    const pt = renderPoint(loc, prevLoc || loc, loc);
    const c = document.createElementNS(SVG_NS, "circle");
    c.setAttribute("cx", pt[0]);
    c.setAttribute("cy", pt[1]);
    c.setAttribute("r", AGENT_R);
    c.classList.add("agent-dot");
    if (protagSet.has(agentId)) c.classList.add("protag");
    c.setAttribute("data-agent", agentId);
    g.appendChild(c);
  }
  state.agentLocation = Object.fromEntries(
    Object.entries(histories).map(([a, h]) => [a, h[h.length - 1]])
  );
}

function updateKPI() {
  const bar = document.getElementById("kpi-bar");
  const m = DATA.metrics[state.variant] || {};
  const trace = DATA.variants[state.variant] || {};
  bar.innerHTML = `
    <div class="kpi-item"><span class="label">DAY</span><span class="value">${state.day + 1} / 14</span></div>
    <div class="kpi-item"><span class="label">AGENTS</span><span class="value">${trace.n_agents || 0}</span></div>
    <div class="kpi-item"><span class="label">ENCOUNTERS</span><span class="value">${(m.encounter_total || 0).toLocaleString()}</span></div>
    <div class="kpi-item"><span class="label">WEAK TIES</span><span class="value">${m.weak_tie || 0}</span></div>
  `;
}

// ─── Controls ────────────────────────────────────────────────────────────────
function setupControls() {
  const daySlider = document.getElementById("day-slider");
  const tickSlider = document.getElementById("tick-slider");
  const dayReadout = document.getElementById("day-readout");
  const tickReadout = document.getElementById("tick-readout");
  const playBtn = document.getElementById("play-btn");
  const speedBtn = document.getElementById("speed-btn");
  const resetBtn = document.getElementById("reset-btn");

  function refresh() {
    dayReadout.textContent = `Day ${state.day + 1} / 14`;
    const hr = Math.floor(state.tick / 12);
    const min = (state.tick % 12) * 5;
    tickReadout.textContent =
      `${String(hr).padStart(2,"0")}:${String(min).padStart(2,"0")}`;
    renderCurrent();
    updateKPI();
  }

  daySlider.addEventListener("input", () => {
    state.day = parseInt(daySlider.value);
    refresh();
  });
  tickSlider.addEventListener("input", () => {
    state.tick = parseInt(tickSlider.value);
    refresh();
  });

  let playInterval = null;
  function play() {
    if (state.playing) return;
    state.playing = true;
    playBtn.textContent = "⏸ Pause";
    playBtn.classList.add("playing");
    playInterval = setInterval(() => {
      let nextTick = state.tick + 1;
      let nextDay = state.day;
      if (nextTick >= TICKS_PER_DAY) {
        nextTick = 0;
        nextDay = state.day + 1;
        if (nextDay > 13) {
          stop();
          return;
        }
      }
      state.day = nextDay;
      state.tick = nextTick;
      daySlider.value = nextDay;
      tickSlider.value = nextTick;
      refresh();
    }, 200 / state.speed);
  }
  function stop() {
    state.playing = false;
    playBtn.textContent = "▶ Play";
    playBtn.classList.remove("playing");
    if (playInterval) { clearInterval(playInterval); playInterval = null; }
  }
  playBtn.addEventListener("click", () => state.playing ? stop() : play());
  speedBtn.addEventListener("click", () => {
    const speeds = [1, 2, 5, 10];
    const idx = speeds.indexOf(state.speed);
    state.speed = speeds[(idx + 1) % speeds.length];
    speedBtn.textContent = `${state.speed}×`;
    if (state.playing) { stop(); play(); }
  });
  resetBtn.addEventListener("click", () => {
    stop();
    state.day = 0;
    state.tick = 0;
    daySlider.value = 0;
    tickSlider.value = 0;
    refresh();
  });

  // ─── Map pan + zoom ──────────────────────────────────────────────────
  const svg = document.getElementById("map-svg");
  let dragStart = null;
  svg.addEventListener("mousedown", (e) => {
    dragStart = { x: e.clientX, y: e.clientY,
                  vx: state.view.x, vy: state.view.y };
  });
  svg.addEventListener("mousemove", (e) => {
    if (!dragStart) return;
    const rect = svg.getBoundingClientRect();
    const scaleX = state.view.w / rect.width;
    const scaleY = state.view.h / rect.height;
    state.view.x = dragStart.vx - (e.clientX - dragStart.x) * scaleX;
    state.view.y = dragStart.vy + (e.clientY - dragStart.y) * scaleY;
    svg.setAttribute("viewBox",
      `${state.view.x} ${state.view.y} ${state.view.w} ${state.view.h}`);
  });
  window.addEventListener("mouseup", () => { dragStart = null; });
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect = svg.getBoundingClientRect();
    const factor = e.deltaY > 0 ? 1.15 : 1 / 1.15;
    const mx = state.view.x + (e.clientX - rect.left) / rect.width * state.view.w;
    const my = state.view.y + (e.clientY - rect.top) / rect.height * state.view.h;
    state.view.w *= factor;
    state.view.h *= factor;
    state.view.x = mx - (e.clientX - rect.left) / rect.width * state.view.w;
    state.view.y = my - (e.clientY - rect.top) / rect.height * state.view.h;
    svg.setAttribute("viewBox",
      `${state.view.x} ${state.view.y} ${state.view.w} ${state.view.h}`);
  }, { passive: false });
}

init();
</script>
</body>
</html>
"""


def build(suite_dir: Path, atlas_path: Path, out_path: Path) -> None:
    print(f"[build_2d_replay] Loading atlas geometry...")
    atlas_payload = _load_atlas_polygons(atlas_path)
    print(f"  → {len(atlas_payload['locations'])} polygons "
          f"({atlas_payload['bounds_max'][0] - atlas_payload['bounds_min'][0]:.0f}m × "
          f"{atlas_payload['bounds_max'][1] - atlas_payload['bounds_min'][1]:.0f}m bounds)")

    print(f"[build_2d_replay] Loading position traces...")
    variants_pos = _load_suite_positions(suite_dir)
    metrics = _load_suite_metrics(suite_dir)
    for v, payload in variants_pos.items():
        print(f"  → {v}: {payload['n_agents']} agents, {payload['n_changes']} changes")

    if not variants_pos:
        print(f"error: no seed_*_positions.json files found under {suite_dir}",
              file=sys.stderr)
        print(f"        (re-run the suite with the new position recorder)",
              file=sys.stderr)
        sys.exit(2)

    n_days = max(m.get("num_days", 14) for m in metrics.values()) if metrics else 14

    subtitle = f"{len(variants_pos)} variants · 14d × 5min ticks · 真实 Lane Cove 几何"

    viz_data = {
        "atlas": atlas_payload,
        "variants": variants_pos,
        "metrics": metrics,
        "n_days": n_days,
    }

    html = (
        HTML_TEMPLATE
        .replace("{{ subtitle }}", subtitle)
        .replace("{{ viz_data_json }}",
                 json.dumps(viz_data, ensure_ascii=False))
    )
    out_path.write_text(html, encoding="utf-8")
    size_mb = len(html.encode()) / 1024 / 1024
    print(f"✅ wrote {out_path} ({size_mb:.1f} MB)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("suite_dir", type=Path)
    p.add_argument("--atlas", type=Path,
                   default=Path("data/lanecove_atlas.json"))
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    if not args.suite_dir.is_dir():
        print(f"error: not a directory: {args.suite_dir}", file=sys.stderr)
        return 2

    out = args.out or args.suite_dir / "2d_replay.html"
    build(args.suite_dir, args.atlas, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
