"""F1 · 2.5D map of Lane Cove blindness topology

Each location is a column:
  - height = baseline notice rate (% of physical co-presence converted to noticed)
  - color = building_type (residential/worship warm, street cold)

Reuses pattern from tools/build_25d_findings_dashboard.py — maplibre + deck.gl,
single-file standalone HTML, but ONE scene only (focused F1 viz).

Output: docs/figures_v4/f1_blindness_topology_25d.html
"""
import json
from pathlib import Path
import pyproj

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
ATLAS = REPO / "data/lanecove_atlas.json"
PROJ_CENTER = REPO / "data/lanecove_proj_center.json"
F1_DATA = REPO / "data/analysis/2026-05-24_hypothesis_validation/F1_shape/f1_shape_baseline.json"
OUT_HTML = REPO / "docs/figures_v4/f1_blindness_topology_25d.html"


print("Loading projection + atlas...", flush=True)
with open(PROJ_CENTER) as f:
    cfg = json.load(f)
proj = pyproj.Proj(proj="aeqd", lat_0=cfg["center_lat"], lon_0=cfg["center_lon"], units="m")

with open(ATLAS) as f:
    atlas = json.load(f)

loc_geo = {}  # location_id -> {lat, lng, type, name, kind}
for bid, b in atlas["buildings"].items():
    poly = b.get("polygon", {}).get("vertices", [])
    if not poly: continue
    if isinstance(poly[0], dict):
        xs = [v["x"] for v in poly]; ys = [v["y"] for v in poly]
    else:
        xs = [v[0] for v in poly]; ys = [v[1] for v in poly]
    cx, cy = sum(xs)/len(xs), sum(ys)/len(ys)
    lng, lat = proj(cx, cy, inverse=True)
    loc_geo[bid] = {
        "name": b.get("name") or bid,
        "type": b.get("building_type", "unknown"),
        "kind": "building",
        "lat": lat, "lng": lng,
    }

outdoor = atlas.get("outdoor_areas", {})
out_iter = outdoor.items() if isinstance(outdoor, dict) else [(o["id"], o) for o in outdoor]
for oid, o in out_iter:
    poly = o.get("polygon", {}).get("vertices", [])
    if not poly: continue
    if isinstance(poly[0], dict):
        xs = [v["x"] for v in poly]; ys = [v["y"] for v in poly]
    else:
        xs = [v[0] for v in poly]; ys = [v[1] for v in poly]
    cx, cy = sum(xs)/len(xs), sum(ys)/len(ys)
    lng, lat = proj(cx, cy, inverse=True)
    loc_geo[oid] = {
        "name": o.get("name") or oid,
        "type": o.get("area_type", "outdoor"),
        "kind": "outdoor",
        "lat": lat, "lng": lng,
    }

print(f"  {len(loc_geo)} locations geocoded", flush=True)

print("Loading F1 notice-rate data...", flush=True)
f1 = json.load(open(F1_DATA))
loc_rates = f1["all_location_rates"]  # list of {loc, name, type, enc, noticed, rate}

# Build column data
cols = []
for x in loc_rates:
    lid = x["loc"]
    if lid not in loc_geo:
        continue
    g = loc_geo[lid]
    cols.append({
        "lat": g["lat"], "lng": g["lng"],
        "name": x["name"] or g["name"] or lid,
        "type": x["type"],
        "rate": x["rate"],
        "enc": x["enc"],
        "noticed": x["noticed"],
    })

print(f"  {len(cols)} columns to render", flush=True)

# Center the map
mean_lat = sum(c["lat"] for c in cols) / len(cols)
mean_lng = sum(c["lng"] for c in cols) / len(cols)

# Color by type — same palette family as build_25d_findings_dashboard.py
# But here we want residential bright (high awareness island), street dim (canyon)
# Use a single color whose ALPHA tracks notice rate, OR distinct colors per type

# Decision: distinct color per type — easier to read the topology
TYPE_COLOR = {
    # awareness islands
    "residential": [200, 85, 61, 230],     # red — homes
    "worship": [220, 130, 60, 230],        # orange — churches
    "playground": [123, 201, 123, 230],    # green — playgrounds
    "hotel": [220, 150, 80, 230],
    # mid pool
    "office": [180, 130, 200, 220],
    "commercial": [180, 130, 200, 220],
    "cafe": [232, 160, 74, 220],
    "restaurant": [232, 160, 74, 220],
    "shop": [232, 160, 74, 220],
    "entertainment": [200, 100, 180, 220],
    "park": [123, 180, 123, 220],
    "hospital": [120, 180, 180, 220],
    # the canyon
    "street": [120, 160, 200, 200],
}
DEFAULT_COLOR = [160, 160, 160, 200]

for c in cols:
    c["color"] = TYPE_COLOR.get(c["type"], DEFAULT_COLOR)

# Stats for legend
import statistics
rates = [c["rate"] * 100 for c in cols]
print(f"  rates: min {min(rates):.1f}% median {statistics.median(rates):.1f}% max {max(rates):.1f}%", flush=True)

# Build HTML
html = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<title>F1 · The Topology of Nearby Blindness · Lane Cove baseline (notice口径)</title>
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet"/>
<script src="https://unpkg.com/deck.gl@9.0.34/dist.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif; background: #0a0d12; color: #eee; overflow: hidden; }
  #map-container { position: fixed; inset: 0; }
  #map, #deck-canvas { position: absolute; inset: 0; }

  .panel {
    background: rgba(15, 15, 22, 0.92);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    padding: 16px 20px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.4);
  }
  #info {
    position: fixed; top: 18px; left: 18px;
    max-width: 420px; z-index: 100;
  }
  #info .label { font-size: 11px; letter-spacing: 0.15em; color: #888; text-transform: uppercase; margin-bottom: 6px; }
  #info h1 { font-size: 20px; font-weight: 600; line-height: 1.35; margin-bottom: 10px; }
  #info .desc { font-size: 13px; color: #c8c8c8; line-height: 1.6; margin-bottom: 10px; }
  #info .takeaway {
    background: rgba(200, 85, 61, 0.25);
    border: 1px solid #c8553d;
    border-radius: 6px;
    padding: 10px 14px;
    font-size: 13px;
    color: #ffddd5;
    font-weight: 500;
    line-height: 1.55;
  }
  #legend {
    position: fixed; top: 18px; right: 18px;
    width: 240px;
    z-index: 100;
  }
  #legend .label { font-size: 11px; letter-spacing: 0.15em; color: #888; text-transform: uppercase; margin-bottom: 10px; }
  .legend-row { display: flex; align-items: center; gap: 10px; margin: 5px 0; font-size: 12px; color: #ccc; }
  .legend-dot { width: 16px; height: 16px; border-radius: 3px; flex-shrink: 0; }
  .legend-row.divider { border-top: 1px dashed #444; margin-top: 10px; padding-top: 10px; }
  #stats {
    position: fixed; bottom: 18px; left: 18px;
    z-index: 100; max-width: 320px;
    font-size: 12px;
  }
  #stats .stat-row { display: flex; justify-content: space-between; margin: 4px 0; color: #ccc; }
  #stats .stat-row .v { font-family: -apple-system, monospace; color: #fff; }
  #tooltip {
    position: absolute;
    background: rgba(0,0,0,0.92);
    border: 1px solid #c8553d;
    border-radius: 6px;
    padding: 10px 14px;
    font-size: 12px;
    pointer-events: none;
    z-index: 200;
    max-width: 280px;
    display: none;
    color: #fff;
    line-height: 1.5;
  }
  #tooltip b { color: #ffddd5; }
</style>
</head>
<body>
<div id="map-container">
  <div id="map"></div>
  <canvas id="deck-canvas"></canvas>
</div>

<div id="info" class="panel">
  <div class="label">FIGURE 1B · 2.5D · Blindness topology</div>
  <h1>The shape of nearby blindness</h1>
  <div class="desc">
    Each column is a Lane Cove location. <b>Height = notice rate</b> — the fraction of physical co-presences
    that cross the attention gate to register as mutual perception. <b>Color = building_type</b>.
    Tall residential columns are <em>awareness islands</em>; the flat blue street segments are
    <em>blindness canyons</em>. Lane Cove baseline (no app).
  </div>
  <div class="takeaway">
    Streets carry the largest absolute encounter pool, yet convert the lowest share to awareness (7%).
    Residential lobbies (19%) sustain the older proximity-equals-awareness regime that the street fabric
    no longer supports.
  </div>
</div>

<div id="legend" class="panel">
  <div class="label">Color = building type</div>
  <div class="legend-row"><div class="legend-dot" style="background:#c85539"></div>residential <span style="color:#aaa;margin-left:auto;">19.4%</span></div>
  <div class="legend-row"><div class="legend-dot" style="background:#dc823c"></div>worship <span style="color:#aaa;margin-left:auto;">17.2%</span></div>
  <div class="legend-row"><div class="legend-dot" style="background:#7bc97b"></div>playground <span style="color:#aaa;margin-left:auto;">14.0%</span></div>
  <div class="legend-row"><div class="legend-dot" style="background:#b482c8"></div>office / commercial <span style="color:#aaa;margin-left:auto;">~14%</span></div>
  <div class="legend-row"><div class="legend-dot" style="background:#e8a04a"></div>cafe / restaurant / shop <span style="color:#aaa;margin-left:auto;">~13%</span></div>
  <div class="legend-row"><div class="legend-dot" style="background:#78c8c8"></div>park / hospital <span style="color:#aaa;margin-left:auto;">~12%</span></div>
  <div class="legend-row divider"><div class="legend-dot" style="background:#78a0c8"></div><b style="color:#fff">street</b> <span style="color:#aaa;margin-left:auto;"><b>7.1%</b></span></div>
  <div class="legend-row" style="margin-top:14px; color:#888; font-size:11px; font-style:italic;">Height = notice rate × 5,000</div>
</div>

<div id="stats" class="panel">
  <div style="font-size: 11px; letter-spacing: 0.1em; color: #888; text-transform: uppercase; margin-bottom: 8px;">Baseline · 1000 agents · 14 days · seed 44+45</div>
""" + f"""
  <div class="stat-row"><span>Locations with ≥40 encounters</span><span class="v">{len(cols):,}</span></div>
  <div class="stat-row"><span>Population mean notice rate</span><span class="v">9.5%</span></div>
  <div class="stat-row"><span>Highest column (residential)</span><span class="v">45%</span></div>
  <div class="stat-row"><span>Lowest column (street)</span><span class="v">0%</span></div>
""" + """
</div>

<div id="tooltip"></div>

<script>
  const COLUMNS = """ + json.dumps(cols, ensure_ascii=False) + f""";
  const CENTER = [{mean_lng}, {mean_lat}];

  // Init map (CartoDB Dark)
  const map = new maplibregl.Map({{
    container: 'map',
    style: 'https://basemaps.cartocdn.com/gl/dark-matter-no-labels-gl-style/style.json',
    center: CENTER,
    zoom: 14.5,
    pitch: 55,
    bearing: -20,
    antialias: true,
  }});
""" + """

  // deck.gl overlay
  const deckCanvas = document.getElementById('deck-canvas');
  const tooltip = document.getElementById('tooltip');

  function showTooltip(o, x, y, fn) {
    if (!o) { tooltip.style.display = 'none'; return; }
    tooltip.style.display = 'block';
    tooltip.style.left = x + 12 + 'px';
    tooltip.style.top = y + 12 + 'px';
    tooltip.innerHTML = fn(o);
  }

  const deckgl = new deck.Deck({
    canvas: 'deck-canvas',
    initialViewState: {
      longitude: CENTER[0], latitude: CENTER[1],
      zoom: 14.5, pitch: 55, bearing: -20,
    },
    controller: true,
    layers: [
      new deck.ColumnLayer({
        id: 'blindness-cols',
        data: COLUMNS,
        getPosition: d => [d.lng, d.lat],
        getElevation: d => d.rate * 5000,  // 0.45 rate -> 2250m, dramatic
        getFillColor: d => d.color,
        radius: 12,
        extruded: true,
        pickable: true,
        material: { ambient: 0.5, diffuse: 0.7, shininess: 32 },
        elevationScale: 1,
        onHover: ({object, x, y}) => showTooltip(object, x, y,
          o => `<b>${o.name}</b><br>type: ${o.type}<br>notice rate: <b style="color:#ffd">${(o.rate*100).toFixed(1)}%</b><br>encounters: ${o.enc}<br>noticed: ${o.noticed}`),
      }),
    ],
    onViewStateChange: ({viewState}) => {
      map.jumpTo({
        center: [viewState.longitude, viewState.latitude],
        zoom: viewState.zoom,
        pitch: viewState.pitch,
        bearing: viewState.bearing,
      });
    },
  });

  map.on('move', () => {
    const c = map.getCenter();
    deckgl.setProps({initialViewState: {
      longitude: c.lng, latitude: c.lat,
      zoom: map.getZoom(), pitch: map.getPitch(), bearing: map.getBearing(),
    }});
  });
</script>
</body></html>
"""

OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
OUT_HTML.write_text(html, encoding="utf-8")
print(f"\n✓ {OUT_HTML} ({OUT_HTML.stat().st_size//1024} KB)")
print(f"  open with: open {OUT_HTML}")
