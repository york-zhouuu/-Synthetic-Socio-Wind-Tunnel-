/**
 * Map Explorer — Agent-perspective map viewer.
 *
 * Core idea: The map shows what EACH AGENT KNOWS.
 * - Switch agent → the map literally changes (unknown locations go grey with "?")
 * - Click a location → see what THAT AGENT knows about it
 * - Familiarity level drives info depth (HEARD_OF vs VISITED vs REGULAR)
 *
 * No numeric social scores. The LLM agent interprets observable facts.
 */

// ─── State ───────────────────────────────────────────────────────────────────

const state = {
  mapData: null,
  contextLayers: null,
  agentKnowledge: null,
  currentAgent: "none",
  selectedLocId: null,
  showPerception: true,
  showConnections: false,
  showBorders: true,
  showLabels: false,       // labels hidden by default
  perceptionData: null,
  viewBox: { x: 0, y: 0, w: 420, h: 305 },
  dragging: false,
  dragStart: null,
};

// ─── DOM refs ─────────────────────────────────────────────────────────────────

const svg         = document.getElementById("map-svg");
const loading     = document.getElementById("loading");
const regionName  = document.getElementById("region-name");
const agentSelect = document.getElementById("agent-select");
const infoPH      = document.getElementById("info-placeholder");
const infoContent = document.getElementById("info-content");
const btnPerception  = document.getElementById("btn-perception");
const btnConnections = document.getElementById("btn-connections");
const btnBorders     = document.getElementById("btn-borders");
const btnLabels      = document.getElementById("btn-labels");

let layerBg, layerConn, layerBorder, layerLoc, layerPoi, layerLabel;

// ─── Type colors ──────────────────────────────────────────────────────────────

const TYPE_COLOR = {
  residential:      "#90b8d8",
  cafe:             "#e8a070",
  restaurant:       "#e8a070",
  bar:              "#d88060",
  market:           "#e09050",
  community_center: "#70c090",
  community:        "#70c090",
  coworking:        "#9088cc",
  shop:             "#e0d060",
  commercial:       "#c8b860",
  office:           "#8898c0",
  school:           "#80c8b0",
  hospital:         "#f08080",
  worship:          "#b0a0e0",
  hotel:            "#98a8d0",
  entertainment:    "#d888b8",
  government:       "#8898b8",
  industrial:       "#888890",
  utility:          "#707078",
  street:           "#586070",
  park:             "#58b870",
  garden:           "#68c080",
  playground:       "#78c068",
  outdoor:          "#58b870",
  generic:          "#8090a0",
  building:         "#8090a0",
};
function locColor(subtype) { return TYPE_COLOR[subtype] || TYPE_COLOR.building; }

// ─── Familiarity ──────────────────────────────────────────────────────────────

const FAM_ORDER  = ["unknown", "heard_of", "seen_exterior", "visited", "regular"];
const FAM_LABEL  = { unknown: "未知", heard_of: "听说过", seen_exterior: "见过外观", visited: "去过", regular: "常去" };
const FAM_COLOR  = { unknown: "#333648", heard_of: "#5a4a80", seen_exterior: "#5a6080", visited: "#6c8ef7", regular: "#a0c4ff" };
const FAM_OPACITY = { heard_of: 0.32, seen_exterior: 0.55, visited: 0.78, regular: 0.94 };

function famRank(f) { return FAM_ORDER.indexOf(f); }

// ─── Bootstrap ────────────────────────────────────────────────────────────────

async function init() {
  const [data, ctx] = await Promise.all([
    fetch("/api/map").then(r => r.json()),
    fetch("/api/context-layers").then(r => r.json()),
  ]);
  state.mapData = data;
  state.contextLayers = ctx;

  const bmin = data.region.bounds_min, bmax = data.region.bounds_max;
  const w = bmax[0] - bmin[0], h = bmax[1] - bmin[1];
  const pad = Math.max(w, h) * 0.03;
  state.viewBox = { x: bmin[0] - pad, y: bmin[1] - pad, w: w + pad * 2, h: h + pad * 2 };
  applyViewBox();

  regionName.textContent = data.region.name;
  loading.style.display = "none";

  layerBg     = svgGroup("layer-bg");
  layerConn   = svgGroup("layer-conn");
  layerBorder = svgGroup("layer-border");
  layerLoc    = svgGroup("layer-loc");
  layerPoi    = svgGroup("layer-poi");
  layerLabel  = svgGroup("layer-label");

  updateAgentLegend();
  renderAll();
  setupEvents();
}

// ─── Render ───────────────────────────────────────────────────────────────────

function renderAll() {
  [layerBg, layerConn, layerBorder, layerLoc, layerPoi, layerLabel].forEach(clearLayer);
  renderContextLayers();  // water + landuse background
  if (state.showConnections) renderConnections();
  if (state.showBorders)     renderBorders();
  renderLocations();
  renderPOIs();
}

function renderContextLayers() {
  const ctx = state.contextLayers;
  if (!ctx) return;

  const LANDUSE_COLORS = {
    residential:        "#2a3848",
    grass:              "#1e3528",
    village_green:      "#1e3528",
    recreation_ground:  "#1e3528",
    retail:             "#3a2a25",
    commercial:         "#352838",
    industrial:         "#2a2a30",
    construction:       "#302820",
    religious:          "#28203a",
    depot:              "#252530",
  };

  // Landuse (background fill)
  for (const item of (ctx.landuse || [])) {
    if (item.type !== "polygon") continue;
    const pts = item.points.map(p => `${p[0]},${p[1]}`).join(" ");
    const el = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
    el.setAttribute("points", pts);
    const luColor = LANDUSE_COLORS[item.subtype] || "#1e2030";
    el.setAttribute("fill", luColor);
    el.setAttribute("stroke", luColor);
    el.setAttribute("stroke-width", "2");
    el.style.fillOpacity = "0.85";
    el.style.pointerEvents = "none";
    layerBg.appendChild(el);
  }

  // Water — widths in meters (map units)
  const WATER_WIDTH = {
    river: 80,        // Lane Cove River ~60-100m wide
    stream: 20,
    creek: 15,
    drain: 8,
    ditch: 5,
    flowline: 10,
    canal: 15,
  };
  const WATER_COLOR = "#1a3858";
  const WATER_STROKE = "#305878";

  for (const item of (ctx.water || [])) {
    if (item.type === "polygon") {
      const pts = item.points.map(p => `${p[0]},${p[1]}`).join(" ");
      const el = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
      el.setAttribute("points", pts);
      el.setAttribute("fill", WATER_COLOR);
      el.setAttribute("stroke", WATER_STROKE);
      el.setAttribute("stroke-width", "2");
      el.style.fillOpacity = "0.9";
      el.style.pointerEvents = "none";
      layerBg.appendChild(el);
    } else if (item.type === "line") {
      const pts = item.points.map(p => `${p[0]},${p[1]}`);
      if (pts.length < 2) continue;
      const width = WATER_WIDTH[item.subtype] || 15;
      const el = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      el.setAttribute("points", pts.join(" "));
      el.setAttribute("fill", "none");
      el.setAttribute("stroke", WATER_COLOR);
      el.setAttribute("stroke-width", String(width));
      el.setAttribute("stroke-linecap", "round");
      el.setAttribute("stroke-linejoin", "round");
      el.style.opacity = "0.85";
      el.style.pointerEvents = "none";
      layerBg.appendChild(el);
      // Add a brighter edge
      const edge = el.cloneNode();
      edge.setAttribute("stroke", WATER_STROKE);
      edge.setAttribute("stroke-width", String(width + 4));
      edge.style.opacity = "0.3";
      layerBg.insertBefore(edge, layerBg.firstChild);
    }
  }
}

const POI_COLORS = {
  cafe:             "#e8a060",
  restaurant:       "#e89050",
  fast_food:        "#d88040",
  bar:              "#d07050",
  pub:              "#d07050",
  bank:             "#80a0c0",
  pharmacy:         "#60c080",
  clinic:           "#f08080",
  dentist:          "#f08080",
  doctors:          "#f08080",
  place_of_worship: "#a090d0",
  library:          "#80b0d0",
  post_office:      "#c0a050",
  "shop:supermarket":"#c0c050",
  "shop:convenience":"#b0b050",
  "shop:bakery":    "#d0a060",
  "shop:butcher":   "#c07060",
  "shop:hairdresser":"#c080a0",
  "shop:alcohol":   "#a08060",
  "shop:clothes":   "#a090c0",
};

function renderPOIs() {
  const pois = state.contextLayers?.pois;
  if (!pois || !pois.length) return;

  for (const poi of pois) {
    const [x, y] = poi.point;
    const color = POI_COLORS[poi.type] || "#c0b870";
    const r = 8;  // radius in map units (meters)

    // Dot
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", x);
    circle.setAttribute("cy", y);
    circle.setAttribute("r", r);
    circle.setAttribute("fill", color);
    circle.setAttribute("stroke", "#000");
    circle.setAttribute("stroke-width", "1.5");
    circle.style.fillOpacity = "0.9";
    circle.style.cursor = "pointer";
    circle.classList.add("poi-dot");
    layerPoi.appendChild(circle);

    // Label (always visible for POIs — they're the semantic info)
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", x);
    label.setAttribute("y", y - r - 4);
    label.textContent = poi.name;
    label.classList.add("poi-label");
    label.setAttribute("fill", color);
    layerPoi.appendChild(label);
  }
}

function renderLocations() {
  const { mapData, agentKnowledge, currentAgent, selectedLocId, showPerception, perceptionData } = state;
  if (!mapData) return;

  const knowledgeMap = {};
  if (agentKnowledge) {
    for (const k of agentKnowledge.known_locations) knowledgeMap[k.loc_id] = k;
  }

  // Z-order: streets (bottom) → parks → buildings (top)
  // Without sorting, streets render ON TOP of buildings and hide them
  const Z_ORDER = { street: 0, outdoor: 1, park: 2, garden: 2, playground: 2, building: 3 };
  const sorted = [...mapData.locations].sort((a, b) =>
    (Z_ORDER[a.type] ?? Z_ORDER[a.subtype] ?? 1) - (Z_ORDER[b.type] ?? Z_ORDER[b.subtype] ?? 1)
  );
  for (const loc of sorted) {
    const isGod = currentAgent === "none";
    const k = knowledgeMap[loc.id];
    const fam = k ? k.familiarity : "unknown";
    const isKnown = isGod || fam !== "unknown";
    const isSelected = loc.id === selectedLocId;

    // Perception overlay class
    let perc = "";
    if (!isGod && showPerception && perceptionData && selectedLocId) {
      if (loc.id === selectedLocId)               perc = "sel";
      else if (perceptionData.visible.includes(loc.id)) perc = "visible";
      else if (perceptionData.audible.includes(loc.id)) perc = "audible";
      else                                              perc = "dim";
    }

    const poly = makePoly(loc, isGod, isKnown, fam, perc, isSelected);
    layerLoc.appendChild(poly);

    // Labels — only when showLabels is on, and only for named features
    if (state.showLabels && (isKnown || isGod)) {
      const cx = loc.center[0], cy = loc.center[1];
      const hasRealName = loc.name && !loc.name.startsWith("building_") && !loc.name.startsWith("area_") && !loc.name.match(/^\w+_\d+$/);
      if (hasRealName) {
        const displayName = k?.known_name || loc.name;
        const label = makeLabel(cx, cy, displayName, loc.type === "building");
        if (!isGod && fam === "heard_of") {
          label.setAttribute("fill", "rgba(160,140,220,0.6)");
          label.textContent = "? " + displayName;
        }
        layerLabel.appendChild(label);
      }
    }
  }
}

function makePoly(loc, isGod, isKnown, fam, perc, isSelected) {
  const pts = loc.polygon.map(([x, y]) => `${x},${y}`).join(" ");
  const el = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
  el.setAttribute("points", pts);
  el.setAttribute("data-loc-id", loc.id);
  el.classList.add("loc-polygon");

  if (!isKnown) {
    // Completely unknown
    el.setAttribute("fill", "#181922");
    el.setAttribute("stroke", "#252630");
    el.setAttribute("stroke-width", "0.5");
    el.style.cursor = "default";
    el.style.pointerEvents = "none";
    return el;
  }

  const color = locColor(loc.subtype);
  el.setAttribute("fill", color);
  el.setAttribute("stroke", color);

  // Perception styling
  if (!isGod) {
    if (perc === "sel" || isSelected) {
      el.setAttribute("stroke", "white");
      el.setAttribute("stroke-width", "3");
      el.style.fillOpacity = "0.95";
    } else if (perc === "visible") {
      el.classList.add("perception-visible");
      el.style.fillOpacity = FAM_OPACITY[fam] || "0.78";
    } else if (perc === "audible") {
      el.classList.add("perception-audible");
      el.style.fillOpacity = String((FAM_OPACITY[fam] || 0.78) * 0.75);
    } else if (perc === "dim") {
      el.classList.add("perception-dim");
    } else {
      el.style.fillOpacity = String(FAM_OPACITY[fam] || "0.78");
    }
  }

  if (isSelected) el.classList.add("selected");
  el.addEventListener("click", () => onLocClick(loc.id));
  return el;
}

function makeLabel(cx, cy, text, isBuilding) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", "text");
  el.setAttribute("x", cx); el.setAttribute("y", cy);
  el.classList.add("loc-label");
  if (isBuilding) el.classList.add("building");
  el.textContent = text;
  el.style.pointerEvents = "none";
  return el;
}

function renderConnections() {
  for (const conn of state.mapData.connections) {
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", conn.from_center[0]); line.setAttribute("y1", conn.from_center[1]);
    line.setAttribute("x2", conn.to_center[0]);   line.setAttribute("y2", conn.to_center[1]);
    line.classList.add("conn-line");
    if (conn.path_type === "entrance") line.classList.add("entrance");
    layerConn.appendChild(line);
  }
}

function renderBorders() {
  const locs = {};
  for (const loc of state.mapData.locations) locs[loc.id] = loc;
  const COLOR = { physical: "#e05252", social: "#e0a832", informational: "#7b52e0" };

  for (const border of state.mapData.borders) {
    for (const aid of border.side_a) {
      for (const bid of border.side_b) {
        const a = locs[aid], b = locs[bid];
        if (!a || !b) continue;
        const dx = a.center[0] - b.center[0], dy = a.center[1] - b.center[1];
        if (Math.sqrt(dx*dx + dy*dy) > 130) continue;
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("x1", a.center[0]); line.setAttribute("y1", a.center[1]);
        line.setAttribute("x2", b.center[0]); line.setAttribute("y2", b.center[1]);
        line.classList.add("border-divider");
        line.setAttribute("stroke", COLOR[border.border_type] || "#888");
        layerBorder.appendChild(line);
      }
    }
  }
}

// ─── Click ────────────────────────────────────────────────────────────────────

async function onLocClick(locId) {
  state.selectedLocId = locId;
  state.perceptionData = null;

  const perc = await fetch(`/api/perception/${locId}`).then(r => r.json());
  state.perceptionData = perc;
  renderAll();

  if (state.currentAgent === "none") {
    await showGodEyeInfo(locId);
  } else {
    await showAgentInfo(state.currentAgent, locId);
  }
}

async function showGodEyeInfo(locId) {
  const loc = state.mapData.locations.find(l => l.id === locId);
  if (!loc) return;
  // Try to get detail via a pseudo-agent fetch (god mode shows all physical facts)
  const detail = await fetch(`/api/agent/god/location/${locId}`)
    .then(r => r.ok ? r.json() : null).catch(() => null);
  showInfo(renderGodPanel(loc, detail));
}

async function showAgentInfo(agentId, locId) {
  const r = await fetch(`/api/agent/${agentId}/location/${locId}`);
  if (!r.ok) {
    const loc = state.mapData.locations.find(l => l.id === locId);
    showInfo(renderUnknownPanel(loc));
    return;
  }
  showInfo(renderAgentPanel(agentId, await r.json()));
}

// ─── Info Panels ──────────────────────────────────────────────────────────────

function showInfo(html) {
  infoPH.style.display = "none";
  infoContent.style.display = "block";
  infoContent.innerHTML = html;
}
function hideInfo() {
  infoPH.style.display = "";
  infoContent.style.display = "none";
  infoContent.innerHTML = "";
}

function renderUnknownPanel(loc) {
  return `
    <div class="info-header">
      <div class="info-type-badge" style="background:#22243a;color:#555870">未知地点</div>
      <div class="info-name" style="color:#444760">${esc(loc?.name || "")}</div>
    </div>
    <div class="info-section">
      <div class="unknown-block">
        <div class="unknown-q">?</div>
        <div>
          <div style="font-size:12px;color:#555870;margin-bottom:4px">当前 Agent 对此地一无所知</div>
          <div style="font-size:10px;color:#3d3f56;line-height:1.6">
            信息边界：此地点不在该 Agent 的认知地图中。<br>
            Agent 需要亲身经过、或听人提起、或收到干预通知，才能知道此地存在。
          </div>
        </div>
      </div>
    </div>`;
}

function renderGodPanel(loc, detail) {
  const typeLabel = loc.subtype.replace(/_/g, " ");
  let html = `
    <div class="info-header">
      <div class="info-type-badge type-${loc.subtype}">${esc(typeLabel)}</div>
      <div class="info-name">${esc(loc.name)}</div>
      <div style="font-size:10px;color:#555870;margin-top:3px">上帝视角 · 全量物理事实</div>
    </div>`;

  if (!detail) {
    html += `<div class="info-section"><div class="info-description" style="color:#555870">暂无详细数据</div></div>`;
    return html;
  }

  html += sectionDescription(detail.description);
  html += sectionEntrySignals(detail.entry_signals, true);
  html += sectionAffordances(detail.affordances);
  html += sectionSensory(detail.typical_sounds, detail.typical_smells, detail.active_hours);
  html += sectionTrace(detail.recent_activity);
  html += sectionConnections(detail.connections);
  return html;
}

function renderAgentPanel(agentId, detail) {
  const NAMES = { chen_daye: "陈大爷", alex: "Alex", mei: "Mei", aisha: "Aisha" };
  const agentName = NAMES[agentId] || agentId;
  const fam = detail.familiarity;
  const famLabel = FAM_LABEL[fam] || fam;
  const famColor = FAM_COLOR[fam] || "#6b6e87";
  const typeLabel = detail.subtype.replace(/_/g, " ");

  let html = `
    <div class="info-header">
      <div style="display:flex;gap:6px;align-items:center;margin-bottom:5px;flex-wrap:wrap">
        <div class="info-type-badge type-${detail.subtype}">${esc(typeLabel)}</div>
        <div style="background:${famColor}22;color:${famColor};border:1px solid ${famColor}55;font-size:9px;font-weight:700;padding:2px 8px;border-radius:10px;letter-spacing:0.05em">${famLabel}</div>
      </div>
      <div class="info-name">${esc(detail.name)}</div>
      <div style="font-size:10px;color:#7b7f9e;margin-top:3px">${agentName} 的视角</div>
    </div>`;

  if (fam === "heard_of") {
    html += `<div class="info-section">
      <div class="heard-block">
        <div style="font-size:11px;color:#b8bbd0;line-height:1.7">
          ${agentName} 只是听说过这里，从未亲自到访。<br>
          <span style="font-size:10px;color:#555870">细节未知，信息可能不准确。</span>
        </div>
      </div>
    </div>`;
    return html;
  }

  html += sectionEntrySignals(detail.entry_signals, famRank(fam) >= famRank("seen_exterior"));

  if (famRank(fam) >= famRank("visited")) {
    html += sectionDescription(detail.description);
    html += sectionAffordances(detail.affordances);
    html += sectionSensory(detail.typical_sounds, detail.typical_smells, detail.active_hours);
  }

  html += sectionTrace(detail.recent_activity);
  html += sectionConnections(detail.connections);
  return html;
}

// ─── Section builders ─────────────────────────────────────────────────────────

function sectionDescription(desc) {
  if (!desc) return "";
  return `<div class="info-section">
    <div class="info-section-title">场所描述</div>
    <div class="info-description">${esc(desc)}</div>
  </div>`;
}

function sectionEntrySignals(es, show) {
  if (!show || !es) return "";
  const hasSomething = es.facade_description || es.signage?.length || es.price_visible || es.visible_from_street?.length;
  if (!hasSomething) return "";
  let h = `<div class="info-section"><div class="info-section-title">外部可观察到的</div>`;
  if (es.facade_description) h += `<div class="info-description" style="margin-bottom:6px">${esc(es.facade_description)}</div>`;
  if (es.signage?.length) h += `<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:5px">${es.signage.map(s => `<span class="signal-tag">${esc(s)}</span>`).join("")}</div>`;
  if (es.price_visible) h += `<div style="font-size:10px;color:#b5a040;margin-bottom:3px">💰 ${esc(es.price_visible)}</div>`;
  if (es.visible_from_street?.length) h += `<div style="font-size:10px;color:#7b7f9e">可见：${es.visible_from_street.map(esc).join("、")}</div>`;
  return h + `</div>`;
}

function sectionAffordances(affordances) {
  if (!affordances?.length) return "";
  let h = `<div class="info-section"><div class="info-section-title">在这里可以做什么</div>`;
  for (const a of affordances) {
    const reqTags = (a.requires || []).map(r => `<span class="signal-tag req-tag">${esc(r)}</span>`).join("");
    const langTags = (a.language_of_service || []).map(l => `<span class="signal-tag lang-tag">${esc(l)}</span>`).join("");
    h += `<div class="affordance-item">
      <div class="affordance-header">
        <span class="affordance-type">${esc(a.activity_type.replace(/_/g, " "))}</span>
        <span class="affordance-time">${esc(a.time_range || "")}</span>
      </div>
      ${a.description ? `<div class="affordance-desc">${esc(a.description)}</div>` : ""}
      ${reqTags || langTags ? `<div class="affordance-tags">${reqTags}${langTags}</div>` : ""}
    </div>`;
  }
  return h + `</div>`;
}

function sectionSensory(sounds, smells, activeHours) {
  if (!sounds?.length && !smells?.length && !activeHours) return "";
  let h = `<div class="info-section"><div class="info-section-title">感官环境</div><div class="info-meta">`;
  if (sounds?.length)  h += `<div class="info-meta-row"><span class="label">声音</span><span class="value">${sounds.map(esc).join("、")}</span></div>`;
  if (smells?.length)  h += `<div class="info-meta-row"><span class="label">气味</span><span class="value">${smells.map(esc).join("、")}</span></div>`;
  if (activeHours)     h += `<div class="info-meta-row"><span class="label">时间</span><span class="value">${activeHours.open}:00 – ${activeHours.close}:00</span></div>`;
  return h + `</div></div>`;
}

function sectionTrace(events) {
  if (!events?.length) return "";
  return `<div class="info-section">
    <div class="info-section-title">近期活动记录</div>
    <div class="trace-list">${events.map(e => `<div class="trace-item">${esc(e)}</div>`).join("")}</div>
  </div>`;
}

function sectionConnections(connections) {
  if (!connections?.length) return "";
  let h = `<div class="info-section"><div class="info-section-title">相邻地点</div>`;
  for (const c of connections) {
    h += `<div class="conn-item">
      <div class="conn-type-dot" style="background:${locColor("street")}"></div>
      <span class="conn-name">${esc(c.to_name)}</span>
      <span class="conn-type">${esc(c.path_type)}</span>
      <span class="conn-dist">${c.distance_m}m</span>
    </div>`;
  }
  return h + `</div>`;
}

// ─── Agent selector ───────────────────────────────────────────────────────────

agentSelect.addEventListener("change", async () => {
  const agent = agentSelect.value;
  state.currentAgent = agent;
  state.selectedLocId = null;
  state.perceptionData = null;
  state.agentKnowledge = null;
  hideInfo();

  if (agent !== "none") {
    const data = await fetch(`/api/agent/${agent}/knowledge`).then(r => r.json());
    state.agentKnowledge = data;
  }

  updateAgentLegend();
  renderAll();
});

function updateAgentLegend() {
  const legend = document.getElementById("perception-legend");
  const agentLegend = document.getElementById("familiarity-legend");
  if (state.currentAgent === "none") {
    legend.style.display = "none";
    if (agentLegend) agentLegend.style.display = "none";
  } else {
    legend.style.display = "";
    if (agentLegend) agentLegend.style.display = "";
  }
}

// ─── Toggle buttons ───────────────────────────────────────────────────────────

btnPerception.addEventListener("click", () => {
  state.showPerception = !state.showPerception;
  btnPerception.classList.toggle("active", state.showPerception);
  renderAll();
});
btnConnections.addEventListener("click", () => {
  state.showConnections = !state.showConnections;
  btnConnections.classList.toggle("active", state.showConnections);
  renderAll();
});
btnBorders.addEventListener("click", () => {
  state.showBorders = !state.showBorders;
  btnBorders.classList.toggle("active", state.showBorders);
  renderAll();
});
btnLabels.addEventListener("click", () => {
  state.showLabels = !state.showLabels;
  btnLabels.classList.toggle("active", state.showLabels);
  renderAll();
});

// ─── Pan / Zoom ───────────────────────────────────────────────────────────────

function applyViewBox() {
  const { x, y, w, h } = state.viewBox;
  svg.setAttribute("viewBox", `${x} ${y} ${w} ${h}`);
}

function setupEvents() {
  svg.addEventListener("mousedown", e => {
    if (e.button !== 0) return;
    state.dragging = true;
    state.dragStart = { x: e.clientX, y: e.clientY, vb: { ...state.viewBox } };
  });
  window.addEventListener("mousemove", e => {
    if (!state.dragging) return;
    const dx = (e.clientX - state.dragStart.x) * (state.viewBox.w / svg.clientWidth);
    const dy = (e.clientY - state.dragStart.y) * (state.viewBox.h / svg.clientHeight);
    state.viewBox.x = state.dragStart.vb.x - dx;
    state.viewBox.y = state.dragStart.vb.y - dy;
    applyViewBox();
  });
  window.addEventListener("mouseup", () => { state.dragging = false; });

  svg.addEventListener("wheel", e => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 1.12 : 0.89;
    const rect = svg.getBoundingClientRect();
    const mx = (e.clientX - rect.left) / rect.width;
    const my = (e.clientY - rect.top) / rect.height;
    const px = state.viewBox.x + mx * state.viewBox.w;
    const py = state.viewBox.y + my * state.viewBox.h;
    state.viewBox.w *= factor;
    state.viewBox.h *= factor;
    state.viewBox.x = px - mx * state.viewBox.w;
    state.viewBox.y = py - my * state.viewBox.h;
    applyViewBox();
  }, { passive: false });
}

// ─── Utils ────────────────────────────────────────────────────────────────────

function svgGroup(id) {
  const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
  g.setAttribute("id", id); svg.appendChild(g); return g;
}
function clearLayer(g) { while (g.firstChild) g.removeChild(g.firstChild); }
function esc(str) {
  return String(str || "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ─── Start ────────────────────────────────────────────────────────────────────
init();
