# Synthetic Socio Wind Tunnel · 合成社会风洞

> 一句话研究问题：**手机注意力在高密度城市制造"附近性盲区"——超在地推送能否反向把人带回附近？**

实验场景：悉尼真实街区 **Lane Cove**，1000 个 AI 智能体，14 天 4 对照变体（baseline / 超在地推送 / 镜像全球新闻 / 减少手机吸力）。

📖 **快速入口（先看这三份）**：
- **[`docs/项目产出物.html`](docs/项目产出物.html)** — 用日常语言讲项目在做什么、要产出什么（给没接触过项目的人看）
- **[`docs/四个对照组.html`](docs/四个对照组.html)** — 4 个对照实验各自在干啥、为什么 4 个不是 1 个
- **[`docs/项目状态.md`](docs/项目状态.md)** — 内部 status board：当前阶段、待办、时间线

🚨 **从新机器接管 (2026-05-15)**:
1. clone 完先读 **[`docs/HANDOFF_2026_05_15.md`](docs/HANDOFF_2026_05_15.md)** —— 当前 D1' 状态 / 3 个续跑选项 / 必须应用的 Gemini 修复
2. 事故根因复盘: **[`docs/sessions/2026-05-15-d1-gemini-incident.md`](docs/sessions/2026-05-15-d1-gemini-incident.md)**
3. **API key 没传到 GitHub** (`.env` 永远 gitignored),需要手动通过 AirDrop / Notes / 1Password 等私密方式从旧机拷过来。`.env.example` 列了需要哪几个变量

## Setup (新机器首次)

```bash
git clone git@github.com-york:york-zhouuu/-Synthetic-Socio-Wind-Tunnel-.git
cd Synthetic-Socio-Wind-Tunnel
pip install -e ".[full]"
cp .env.example .env   # 然后填 GEMINI_API_KEY / DEEPSEEK_API_KEYS 等
python3 -m pytest tests/ -q  # 应 1350+ passed,确认环境 OK
```

---

## Project Status (2026-05-12)

**装置已完成 + D2 publishable run 进行中**。round-1/round-2 修复（共 10 个 measurement bug）+ A1 perception-loop archive + B 全套（archetype / life-history / social-priors / conversation-topics）archive + A2/A3 minimum-viable ship + D1' DeepSeek smoke 通过。

| 维度 | 状态 |
|---|---|
| **测试基线** | **1267 passed / 3 skipped**（从 Phase 1 的 506 → Phase 2 + 修复后的 1267） |
| **OpenSpec archives** | **20+ 个 change**（含 A1 / B 整套 / round-1 fix-variant-measurement / round-2 fix-encounter-detection / DeepSeek tier client）|
| **运行中** | D2 publishable: 15 seed × 14 day × 100 agent × DeepSeek（启动 2026-05-11 17:26，预估 60-80 hr）|
| **D1' 验证结果** | hp encounter -1.2%（与 Gemini +4.4% 对比，需 D2 多 seed 确认）/ traj_dev hp 188m < gd 232m ✅ / pf +7.1% ✅ |
| **Provider 支持** | Gemini Flash + Anthropic Haiku/Sonnet + DeepSeek v4-pro/flash + stub（4 家 + 多 tier 路由）|
| **修复历史** | 2 轮 bug audit 共修 10 个 measurement bug，见 [`docs/audit/2026-05-09-bug-hunt.md`](docs/audit/2026-05-09-bug-hunt.md) |
| **局限与伦理** | [`docs/limitations-ethics.md`](docs/limitations-ethics.md) —— synthetic ≠ real / LLM bias / 单城市外推风险 / 15-seed < 30 publishable 门槛 |

仍 propose-only 待 implement：
- A2 §4-§6（scripted_plan household coordination + multi_day_run 集成）
- A3 §3-§7（move_entity overflow + orchestrator 集成 + metrics）
- D2 完成后的 v4 报告 HTML（基于真数据）

完整时间线 + 决策点 + 候选路径：[`docs/项目状态.md`](docs/项目状态.md) §3 + §5

### Quick visualize

```bash
# 跑完一个 suite 后渲染 trajectory heatmap（per-variant）
python3 tools/visualize_run.py --run-dir data/experiments/<ts>_<suite>/
```

输出 `<run-dir>/heatmap.png` —— 6 variant 各一张子图，颜色深浅 = 累计
dwell tick；可视化对比 hyperlocal_push（拉向 target_location）/
shared_anchor（聚集到 community）/ baseline（无明显热点）。

```bash
# Tick-级 replan 因果链 trace（debug 用；< 2s 跑完小 sim）
python3 tools/replan_trace.py --variant hyperlocal_push --max-events 30
python3 tools/replan_trace.py --variant baseline    # → 应 0 plan_changed
```

输出文本：feed_delivered → plan_changed → moved 的 tick 级序列；按
(day, agent) 分组。把"variant 真的影响行为"的因果链**可读化**。


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
