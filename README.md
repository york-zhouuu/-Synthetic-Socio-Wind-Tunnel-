# Synthetic Socio Wind Tunnel

> *A simulation environment for testing hyperlocal social interventions — before deploying them in the real world.*

---

## Project Status (as of 2026-04-25)

**装置 100% / 实验产出 0%** — 11 capability 全部归档；全栈 smoke 跑通；
但 agent 拟真度不足，任何 publishable suite 当前都标
`[unpublishable preview]`，因为 8 项 pre-publication checklist 缺 ≥ 3 项。

| 维度 | 状态 |
|---|---|
| Capabilities archived | **11**（atlas / ledger / engine / perception / cartography / attention-channel / agent / orchestrator / memory / multi-day-run / policy-hack / metrics / suite-wiring 等） |
| 治理层 spec | **3** — thesis-focus / research-design / validation-strategy |
| Pytest | 506 passed, 2 skipped |
| Pre-publication checklist | **3 ✓ / 3 ✗ / 2 ⚠️** （详见 [`19-system-snapshot.md`](docs/agent_system/19-system-snapshot.md)） |
| 阻塞下一里程碑 | `agent-calibration`、`stereotype-audit`、`face-validity-protocol` 三个未做 |

完整快照（架构图、数据流、capability 矩阵、历史决策、候选路径）：
[`docs/agent_system/19-system-snapshot.md`](docs/agent_system/19-system-snapshot.md)

---

## The Problem

Modern high-density urban communities harbor a paradox:

**Physical distance has never been smaller. Social distance has never been greater.**

In places like Sydney's Zetland/Green Square or Lane Cove 2066, residents share corridors, elevators, and train exits — yet have near-zero social connection. The biggest barrier isn't a wall. It's **attention displacement**: algorithms route every glance toward global news and distant events, leaving a 1,000-metre blind spot around each person's actual life.

### Main boundary: Attention-induced Nearby Blindness

One **main boundary** sits at the centre of this phenomenon. Three further layers stack around it as an input → output → validation chain — not parallel boundaries, but positions on a single mechanism chain:

```
algorithmic-input  →  attention-main  →  spatial-output  →  social-downstream
   (source)             (MAIN)              (spatial        (downstream
                                             symptom)        validation)
```

| Chain position | What it is | Measurement |
|---|---|---|
| `algorithmic-input` | Recommender bias toward global over hyperlocal | feed content hyperlocal ratio |
| **`attention-main`** | **Phone gaze displaces the physical <500m environment** | `AttentionState`, notification reach |
| `spatial-output` | Commute paths ossify; public space reduced to transit | trajectory deviation, space activation |
| `social-downstream` | Serendipity and weak ties disappear | encounter → conversation conversion |

See [`docs/agent_system/00-thesis.md`](docs/agent_system/00-thesis.md) for the canonical thesis statement, mechanism chain, and `Chain-Position` gate that every Phase 2 change must cite.

---

## What This Is

A **synthetic wind tunnel for social experiments** — the same logic as aerodynamic testing. You don't bolt a new wing shape onto a plane and fly it; you run it through a wind tunnel first. Here, the "wing shape" is a hyperlocal digital intervention (a rerouted news feed, an unlocked courtyard door, a shared hidden task), and the "wind tunnel" is a simulated urban neighbourhood populated by ~1,000 AI agents.

The system runs three classes of experiment:

### Experiment 1 — Digital Lure
*Does hyperlocal information change physical movement?*
Push location-specific micro-news to agents. Measure trajectory deviation and space activation in formerly dead zones.

### Experiment 2 — Spatial Unlock
*Does a minimal rule change trigger an ecological chain reaction?*
Unlock a previously closed passage; place a bench in a dead zone. Measure emergent desire paths and dwell-time shifts.

### Experiment 3 — Shared Perception
*Does a shared hidden goal collapse psychological distance?*
Assign a common ambient task (e.g. find the lost cat) to otherwise isolated agents. Measure convergence across demographic clusters.

Each experiment produces a four-act output:

Updated five-act structure and the rival-hypothesis framing that organises
these experiments live in [`docs/agent_system/13-research-design.md`](docs/agent_system/13-research-design.md).
The four-act sketch above is preserved as historical shorthand.

---

## Research Posture

This is an **exploratory research instrument** — functionally closer to a
physics cloud chamber than to a deployable policy engine.

- **Exploratory instrument, not policy engine.** The goal is to make the
  phenomenon of attention-induced nearby blindness visible and navigable,
  not to produce deployable recommendations.
- **Dual-use explicit.** Every intervention we test has a paired "mirror"
  scenario that weaponises the same mechanism in the opposite direction;
  our primary deliverable includes at least one mirror at equal rigor.
- **No deployment endorsement.** We do not claim the tool is ready to run
  on real residents. Real deployment requires consent, governance, and
  feedback — all out of scope here.
- **Rigor: β standard.** Publishable effect sizes use 30-seed × 14-day
  runs reported as median + IQR/CI. Single-run numbers are preliminary.

Canonical thesis statement: [`docs/agent_system/00-thesis.md`](docs/agent_system/00-thesis.md).
Canonical research design + experimental protocol: [`docs/agent_system/13-research-design.md`](docs/agent_system/13-research-design.md).
Validity taxonomy + audit protocols + pre-publication checklist: [`docs/agent_system/18-validation-strategy.md`](docs/agent_system/18-validation-strategy.md).

---

## How It Works

The simulation is built in two layers.

### Layer 1 — Map Engine (adapted, open to modification)

A CQRS spatial engine that models urban geography with the fidelity needed for social simulation. Built around a "Theater Model":

```
┌──────────────────────────────────────────────────────────────────┐
│                        Agent Layer (actors)                      │
└───────────────────────────┬──────────────────────────────────────┘
                            │
        ┌───────────────────┼────────────────────┐
        ▼                   ▼                    ▼
┌───────────────┐  ┌────────────────┐  ┌──────────────────┐
│ Engine (WRITE)│  │Perception(READ)│  │Cartography(SETUP)│
│ movement      │  │ per-agent view │  │ OSM import       │
│ doors, items  │  │ filter chain   │  │ map builder      │
└───────┬───────┘  └───────┬────────┘  └──────────────────┘
        │                  │
        ▼                  ▼
┌─────────────────────────────────────────┐
│  Atlas (static map)  │  Ledger (state)  │
│  buildings, rooms,   │  positions,      │
│  doors, geometry     │  items, doors    │
└─────────────────────────────────────────┘
```

Key properties of the engine:
- **Atlas** — immutable geography (OpenStreetMap → GeoJSON → region)
- **Ledger** — mutable world state (where everyone and everything is)
- **Rashomon Effect** — same space, different subjective experiences per agent (skill, emotion, knowledge all filter perception)
- **Schrödinger Details** — room contents don't exist until an agent looks; generated on demand, constrained by spatial budget
- **Cognitive Map** — agents don't know the full layout; they discover it by moving

### Layer 2 — Agent System (in development)

1,000 agents with differentiated resolution:

| Tier | Count | Model | Memory |
|------|-------|-------|--------|
| Protagonists | 10 | Full LLM (Sonnet) | Full episodic memory |
| Supporting cast | ~200 | Mid-tier, context-triggered | Summary memory |
| Background crowd | ~790 | Rule-based + lightweight LLM | Pattern memory |

**Plan-based execution** keeps costs viable: each agent generates a daily plan in one LLM call (~$3–5/day for the full 1,000-agent run), then follows it — replanning only when interrupted by an intervention or social encounter.

---

## Project Structure

```
Synthetic_Socio_Wind_Tunnel/
├── synthetic_socio_wind_tunnel/     # Map engine (adapted)
│   ├── core/                        # Geometry primitives
│   ├── atlas/                       # Static map layer
│   ├── ledger/                      # Dynamic state layer
│   ├── engine/                      # Write operations (movement, doors)
│   ├── perception/                  # Read operations (per-agent views)
│   │   └── filters/                 # Environmental, audio, olfactory, skill
│   ├── cartography/                 # Map building from OSM/GeoJSON
│   └── agent/                       # Agent profile, planner, runtime
├── tests/                           # Test suite
└── docs/
    ├── 项目Brief.md                  # Full research brief
    ├── agent_system/                 # Agent architecture (01–06)
    └── map_pipeline/                 # Map building guide (01–03)
```

---

## Development Status

| Component | Status |
|-----------|--------|
| Map engine (Atlas + Ledger) | ✅ Complete |
| Simulation service (movement, doors, items) | ✅ Complete |
| Perception pipeline + filter chain | ✅ Complete |
| Navigation (door-aware pathfinding) | ✅ Complete |
| Cognitive map (exploration memory) | ✅ Complete |
| OSM/GeoJSON map import | ✅ Complete |
| Agent profile + daily planner | ✅ Complete |
| Orchestrator + simulation clock (single-day) | ✅ Complete |
| Multi-day orchestration (N-day runner + memory carryover) | ✅ Complete |
| Policy hack (4 rival-hypothesis variants + 1 paired mirror) | ✅ Complete |
| Metrics (rival contest scorer + 5-act Markdown report) | ✅ Complete |
| Suite wiring (variant → memory → replan → behavior causal chain) | ✅ Complete |
| Intervention engine (Policy Hack) | 📋 Designed |
| Model budget allocation (dynamic tiering) | 📋 Designed |
| Experiment visualisation (heatmaps, trajectories) | 📋 Designed |

---

## Getting Started

```bash
git clone git@github.com:york-zhouuu/-Synthetic-Socio-Wind-Tunnel-.git
cd -Synthetic-Socio-Wind-Tunnel-
pip install -e ".[dev]"

python -m pytest tests/ -v
```

## Fitness audit (Phase 1.5)

The `fitness-audit` capability checks whether the Phase 1 infrastructure actually
supports the three experiments described above. It is the gate that Phase 2
changes (memory / orchestrator / policy-hack / …) must reference before opening
implementation:

```bash
make fitness-audit          # quick: 100 agents × 72 ticks  (~5s)
make fitness-audit-full     # full:  1000 agents × 288 ticks (slower)
```

Output: `data/fitness-report.json` (not committed — it's a point-in-time snapshot).

Each audit result carries one of three statuses:

| status | meaning |
|---|---|
| `pass` | Phase 1 supports this check |
| `fail` | Phase 1 has a gap; `mitigation_change` points at which Phase 2 capability must fix it |
| `skip` | Expected gap (e.g. "no per-agent task store yet"); `mitigation_change` identifies the capability that will add it |

Phase 2 change proposals **SHALL** cite at least one `fail` or `skip` entry in
their `## Why` section so every capability has documented motivation tied back
to observed infrastructure gaps.

See `openspec/changes/realign-to-social-thesis/` for the design rationale and
`docs/agent_system/07-审计报告解读.md` for how to read the report.

---

## Context

This project responds to the design brief *Border Crossings: Instruments of Erasure and Infiltration* — exploring new forms of social boundary that emerge at the intersection of digital and physical space in contemporary cities, and designing tools to penetrate them.

**Disciplines:** Social Design · Computational Social Science · Interactive System Design

**Site:** High-density urban residential communities (reference case: Zetland/Green Square, Sydney)

---

## Data sources & attribution

The Lane Cove reference region is built from public geospatial data:

| Source | Role | License |
|---|---|---|
| **OpenStreetMap** (via Overpass) | Roads, buildings, land use | [ODbL 1.0](https://www.openstreetmap.org/copyright) — © OpenStreetMap contributors |
| **Overture Maps Foundation** — Buildings & Places themes | Building footprints + POI enrichment | [Overture attribution](https://docs.overturemaps.org/attribution/) — mixed ODbL / CDLA-P 2.0 |
| **Geoscape G-NAF** | Optional address-level resolution (not yet wired) | [Open G-NAF EULA](https://data.gov.au/data/dataset/geocoded-national-address-file-g-naf) — © Geoscape Australia |
| **Microsoft Global ML Building Footprints** | Reserved as fallback for geometry gaps | [CDLA-Permissive 2.0](https://github.com/microsoft/GlobalMLBuildingFootprints) |
| **NSW DCS Spatial Services — Geoscape Buildings** | *Not used* (public-sector only) | — |

Derived artifacts committed under `data/` (e.g. `lanecove_osm.geojson`,
`lanecove_enriched.geojson`, `lanecove_atlas.json`) are combinations of the
above; each downstream consumer must keep the attributions above intact.

## License

MIT (for project code).  Map data remains under the licences above.
