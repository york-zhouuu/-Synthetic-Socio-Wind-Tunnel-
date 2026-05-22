# Synthetic Socio Wind Tunnel · 合成社会风洞

> **你认识住你楼上的邻居吗?**
>
> 在悉尼 Lane Cove 这样的高密度城区,人和人之间的物理距离只剩几米,社会距离却被一面看不见的墙隔开——那面墙是手机里的全球资讯流。
>
> 这个项目造了一个 **AI 多智能体城市模型**,在虚拟世界里测试一件事:**把推送的注意力从"全球远处"拉回到"楼下街角",人会不会真的走出门、抬起头、看见附近?**

[🇨🇳 中文版](#中文版) · [🇬🇧 English](#english) · [📜 License & Data](#数据来源与许可)

---

## 中文版

### 1. 一句话讲清楚

我们在电脑里造了一个 **悉尼 Lane Cove 的虚拟街区**,放进 **1000 个 AI 居民**,让他们过 **14 天**。然后给他们的"手机"换不同的内容,看人的走路路线、谁会跟谁相遇、谁会跟谁聊上几句——**哪些变了,哪些没变**。

这是一个研究**注意力 → 物理行为**的"风洞"。就像飞机上天前要先放进风洞里吹一遍,城市级的数字干预放到真居民身上之前,可以先在这个虚拟城市里跑一遍。

### 2. 我们想回答的问题

**核心问题**:手机注意力的"全球化",是不是在物理上的高密度社区里制造了一片 **1000 米半径的盲区**?

> *"我每天通勤路过 Cowper 街,知道地球另一端的政治新闻,却不知道楼下咖啡馆昨天换了老板。"*

这种**"近处的盲"**(Attention-induced Nearby Blindness)是一个**研究假说**——不是已经证明的事实。我们用这个虚拟城市去测它存不存在、能不能逆转。

### 3. 四个对照组(日常语言版)

我们没有只跑一个"实验组",而是同时跑了 4 组,因为单组数据无法回答"是这个干预起的作用,还是别的什么":

| 对外白话名 | 在做什么 | 想回答的问题 |
|---|---|---|
| **对照组:什么都不推** | 居民正常生活,手机不收任何推送 | 不干预时,人本来是什么样? |
| **实验组(核心):超在地推送** | 推送只关于楼下 1000 米内的事——咖啡馆活动、社区议题、邻居动态 | "把注意力拉回附近"真的能让人走出去吗? |
| **镜像组:推全球新闻** | 推送的是远方的新闻——选举、地震、明星 | 反过来"把注意力推向远方"会让人更宅吗? |
| **反技术组:减少手机吸引力** | 推送频率降下来、通知不响——直接减少手机这一项 | 是手机本身吸走了注意力,还是推送内容? |

**为什么 4 组而不是 1 组**:研究界叫"对手假说框架"(rival hypothesis framing)。任何一组单独看都不能证明因果——必须把"和它长得很像但机制不同"的候选解释一个个排除掉,剩下的才可信。

### 4. 项目能拿出什么(6 大产出物)

每个产出物都有"是什么 / 解决什么问题 / 意义"三段说明。详细版在 [`docs/项目产出物.html`](docs/项目产出物.html)。

| 产出物 | 一句话 |
|---|---|
| 📊 **实验答案** | 4 个对照组的可量化结果——超在地推送在多大程度上把人拉回附近 |
| 📖 **研究故事** | 五幕报告:从"我们假设了什么"到"虚拟城市里发生了什么"到"这对真实城市意味着什么" |
| 🗺️ **地图与图表** | 把"走路路线变了"、"偶遇密度涨了"画在 Lane Cove 真实街区上的热力图 |
| 🏙️ **可运行的虚拟城市** | 完整的模拟系统代码——任何人都能 clone 下来,换条街、换组干预,自己跑 |
| 🔒 **可验证的研究记录** | 每次跑都留下种子数(seed)、配置、内存峰值、日志——别人能完全复现 |
| 📚 **研究知识库** | 完整的设计文档:为什么这么做、踩过哪些坑、哪些不变量必须守 |

### 5. 怎么跑起来

**前置条件**:Python 3.11、≥ 16GB RAM(完整 publishable 跑需要 ≥ 48GB)、DeepSeek 或 Anthropic 或 Gemini API key 任一即可。

```bash
# 安装
git clone git@github.com:york-zhouuu/-Synthetic-Socio-Wind-Tunnel-.git
cd -Synthetic-Socio-Wind-Tunnel-
pip install -e ".[full]"
cp .env.example .env  # 填入 DEEPSEEK_API_KEYS / GEMINI_API_KEY / ANTHROPIC_API_KEY 之一

# 跑测试确认环境 OK(应 1350+ 测试通过)
python3 -m pytest tests/ -q

# 跑一个 smoke(100 agent × 1 day,~10 min,验证打通整个流程)
python3 tools/run_variant_suite.py --variants baseline hyperlocal_push \
  --seeds 1 --num-days 1 --agents 100 --num-protagonists 50 \
  --mode smoke --use-aitown --aitown-provider deepseek

# 看结果(热力图 + Markdown 报告 + JSON 数据)
ls data/experiments/<最新时间戳>_<suite>/
```

**完整规模运行**(1000 agent × 14 day × 4 variant × 4 seed)需要 ~20-30 小时单机、约 50GB 磁盘——这是论文级的"publishable run",不是日常验证。

### 6. 项目结构(技术维度)

主代码在 `synthetic_socio_wind_tunnel/`,按 CQRS 架构分层:

```
synthetic_socio_wind_tunnel/
├── atlas/          🎭 静态地图(只读:墙、门、容器)
├── ledger/         📋 动态状态(读写:位置、物品)
├── engine/         ⚙️  写操作(移动、开门、生成细节)
├── perception/     📷 读操作(每个 agent 的主观视角渲染)
├── agent/          🧠 agent 的决策栈(感知 → 规划 → 行动)
├── memory/         💾 长期记忆(ai-town 端口:reflection、importance、retrieval)
├── orchestrator/   🎬 主控:时钟、变体、resume、snapshot
├── observability/  📡 埋点(memstat / events / llm.jsonl 三通道)
└── run_resilience/ 🛡️  断点续跑、watchdog、graceful-stop
```

支持系统在 `tools/`(运行脚本、可视化、监控、preflight gate)和 `tests/`(1350+ tests)。

### 7. 文档导航

| 想知道什么 | 看哪份 |
|---|---|
| 项目对外讲解 | [`docs/项目产出物.html`](docs/项目产出物.html) |
| 当前进度 / 待办 | [`docs/项目状态.md`](docs/项目状态.md) |
| 研究假说 + 实验设计 | [`docs/agent_system/00-thesis.md`](docs/agent_system/00-thesis.md) + [`docs/agent_system/13-research-design.md`](docs/agent_system/13-research-design.md) |
| Agent 系统架构 | [`docs/agent_system/01-overview.md`](docs/agent_system/01-overview.md) ~ `18-validation-strategy.md` |
| 地图构建 | [`docs/map_pipeline/`](docs/map_pipeline/) |
| 工程规范 + 不变量 | [`CLAUDE.md`](CLAUDE.md)(LLM 协作指南,人类同样可读) |
| 已知局限 + 伦理 | [`docs/limitations-ethics.md`](docs/limitations-ethics.md) |

### 8. 学术立场(必读)

这是一个**探索性研究工具**——更接近物理学里的"云室"(让看不见的粒子留下轨迹的设备),而不是"可部署的政策引擎"。

- **不是政策引擎**:目标是让"附近性盲区"这个现象**变得可见、可讨论**,不是产出可以直接拿去推的方案。
- **双向暴露**:每个干预都跑了"镜像版"(用同样机制做反向的事),双手都摊开放在桌上。
- **没有部署背书**:虚拟城市里的有效干预 ≠ 真城市里可用——真部署需要居民同意、治理框架、反馈机制,这些都不在本项目里。
- **严谨度门槛**:发表级的效应量用 **4 seed × 14 day** runs,报告中位数 + 区间。单跑数字只能算预实验。

权威说法见 [`docs/agent_system/13-research-design.md`](docs/agent_system/13-research-design.md) 和 [`docs/agent_system/18-validation-strategy.md`](docs/agent_system/18-validation-strategy.md)。

---

## English

### 1. In One Sentence

We built a **virtual neighborhood modeled on Sydney's Lane Cove**, populated it with **1,000 AI residents**, ran them for **14 days**, then tested what happens when you change what their "phones" feed them — and watched their walking routes, who runs into whom, who actually talks to whom. **What changes. What doesn't.**

This is a **wind tunnel for attention → physical-behavior dynamics**. Same logic as the wind tunnel a plane goes through before flying: city-scale digital interventions should run through a simulation like this before touching real residents.

### 2. The Research Question

**Core question**: Has phone-borne attention "globalization" carved out a **1,000-metre blind spot** of social invisibility around each person in dense urban areas?

> *"I commute past Cowper Street every day, know political news from the other side of the planet, but don't know the café below my apartment changed owners last week."*

We call this **Attention-induced Nearby Blindness**. It's a **research hypothesis** — not a proven fact. The virtual city is where we test whether it exists, and whether it can be reversed.

### 3. The Four Comparison Groups (Plain-Language Names)

We didn't just run one "treatment group" — we ran 4 comparison conditions, because a single condition can't tell you whether the intervention or some other confound did the work:

| Plain name | What happens | Question it answers |
|---|---|---|
| **Control: nothing pushed** | Residents live normally, phones receive nothing | What's the baseline? |
| **Treatment (core): hyperlocal push** | Pushes only about things within 1,000m — café events, neighborhood issues, neighbor activity | Does refocusing attention on the nearby actually pull people out? |
| **Mirror: global news push** | Pushes are distant news — elections, earthquakes, celebrities | Does *pushing attention away* make people more reclusive? |
| **Anti-tech: reduce phone pull** | Fewer notifications, quieter alerts — reduces phones as a category | Is it the phone itself, or the content of pushes? |

**Why 4 groups, not 1**: This is called the *rival hypothesis framing*. No single group proves causation — you have to systematically rule out near-identical alternative explanations. What survives is credible.

### 4. What the Project Produces (6 Deliverables)

Each deliverable has a "what is it / what problem it solves / why it matters" explanation. The full public-facing version is in [`docs/项目产出物.html`](docs/项目产出物.html).

| Deliverable | One-liner |
|---|---|
| 📊 **Experimental Answers** | Quantified comparison across 4 groups — how much hyperlocal push pulled attention to "nearby" |
| 📖 **Research Story** | Five-act report: hypothesis → simulation events → implications for real cities |
| 🗺️ **Maps & Charts** | "Walking routes shifted" / "encounter density rose" rendered as heatmaps on real Lane Cove streets |
| 🏙️ **The Runnable Virtual City** | Full simulation code — clone, swap the street, swap the intervention, run your own variant |
| 🔒 **Verifiable Research Record** | Every run logs seeds, configs, memory peaks, full event traces — fully reproducible by others |
| 📚 **Research Knowledge Base** | Complete design docs: why decisions were made, what we hit, what invariants hold |

### 5. Quick Start

**Prerequisites**: Python 3.11, ≥ 16GB RAM (≥ 48GB for full publishable runs), one of: DeepSeek / Anthropic / Gemini API key.

```bash
# Install
git clone git@github.com:york-zhouuu/-Synthetic-Socio-Wind-Tunnel-.git
cd -Synthetic-Socio-Wind-Tunnel-
pip install -e ".[full]"
cp .env.example .env  # Fill in DEEPSEEK_API_KEYS / GEMINI_API_KEY / ANTHROPIC_API_KEY

# Verify environment (should pass 1350+ tests)
python3 -m pytest tests/ -q

# Run a smoke test (100 agents × 1 day, ~10 min, validates the whole pipeline)
python3 tools/run_variant_suite.py --variants baseline hyperlocal_push \
  --seeds 1 --num-days 1 --agents 100 --num-protagonists 50 \
  --mode smoke --use-aitown --aitown-provider deepseek

# See outputs (heatmap + markdown report + JSON data)
ls data/experiments/<latest_timestamp>_<suite>/
```

**Full-scale publishable runs** (1000 agents × 14 days × 4 variants × 4 seeds) take ~20-30 hours on a single machine and ~50 GB of disk. That's the paper-grade run, not the daily verification path.

### 6. Project Structure

Main code lives in `synthetic_socio_wind_tunnel/`, sliced via CQRS:

```
synthetic_socio_wind_tunnel/
├── atlas/          🎭 Static map (read-only: walls, doors, containers)
├── ledger/         📋 Dynamic state (read-write: positions, items)
├── engine/         ⚙️  Write ops (movement, door interactions, detail generation)
├── perception/     📷 Read ops (per-agent subjective view rendering)
├── agent/          🧠 Agent decision stack (perceive → plan → act)
├── memory/         💾 Long-term memory (ai-town port: reflection, importance, retrieval)
├── orchestrator/   🎬 Master control: clock, variants, resume, snapshot
├── observability/  📡 Instrumentation (memstat / events / llm.jsonl)
└── run_resilience/ 🛡️  Mid-run resume, watchdog, graceful-stop
```

Tooling in `tools/` (run scripts, viz, monitors, preflight gates) and tests in `tests/` (1350+ tests).

### 7. Documentation Map

| You want to know | Look here |
|---|---|
| Public-facing overview | [`docs/项目产出物.html`](docs/项目产出物.html) |
| Current status / WIP | [`docs/项目状态.md`](docs/项目状态.md) |
| Research hypothesis + experimental design | [`docs/agent_system/00-thesis.md`](docs/agent_system/00-thesis.md) + [`docs/agent_system/13-research-design.md`](docs/agent_system/13-research-design.md) |
| Agent system architecture | [`docs/agent_system/01-overview.md`](docs/agent_system/01-overview.md) through `18-validation-strategy.md` |
| Map pipeline | [`docs/map_pipeline/`](docs/map_pipeline/) |
| Engineering conventions + invariants | [`CLAUDE.md`](CLAUDE.md) (LLM-collaboration guide, also human-readable) |
| Known limitations + ethics | [`docs/limitations-ethics.md`](docs/limitations-ethics.md) |

### 8. Research Posture (Important)

This is an **exploratory research instrument** — closer to a physics cloud chamber (a device that lets invisible particles leave visible tracks) than to a deployable policy engine.

- **Not a policy engine**: The goal is to make *attention-induced nearby blindness* **visible and discussable**, not to ship deployable recommendations.
- **Dual-use explicit**: Every intervention has a "mirror" version (same mechanism, opposite direction). Both hands on the table.
- **No deployment endorsement**: An effective intervention in simulation does *not* mean it's ready for real residents. Real deployment requires consent, governance, feedback — all out of scope here.
- **Rigor threshold**: Publishable effect sizes use **4 seeds × 14 days**, reported as median + interval. Single-run numbers are preliminary.

Canonical statements: [`docs/agent_system/13-research-design.md`](docs/agent_system/13-research-design.md) and [`docs/agent_system/18-validation-strategy.md`](docs/agent_system/18-validation-strategy.md).

---

## 数据来源与许可 · Data Sources & Attribution

Lane Cove 参考区域的地图数据来自公开地理数据集 · The Lane Cove reference region is built from public geospatial data:

| 来源 Source | 用途 Role | 许可 License |
|---|---|---|
| **OpenStreetMap** (via Overpass) | Roads, buildings, land use | [ODbL 1.0](https://www.openstreetmap.org/copyright) — © OpenStreetMap contributors |
| **Overture Maps Foundation** — Buildings & Places themes | Building footprints + POI enrichment | [Overture attribution](https://docs.overturemaps.org/attribution/) — mixed ODbL / CDLA-P 2.0 |
| **Geoscape G-NAF** | Optional address-level resolution (not yet wired) | [Open G-NAF EULA](https://data.gov.au/data/dataset/geocoded-national-address-file-g-naf) — © Geoscape Australia |
| **Microsoft Global ML Building Footprints** | Reserved as fallback for geometry gaps | [CDLA-Permissive 2.0](https://github.com/microsoft/GlobalMLBuildingFootprints) |

衍生 artifact(`data/lanecove_*.json`)是多份数据的组合;下游使用者需保留以上署名。
Derived artifacts under `data/` are combinations of the above; downstream consumers must keep the attributions intact.

## 引用 · Citation

如果本项目对你的研究有启发,请引用 · If this work informs yours, please cite:

```bibtex
@misc{synthetic_socio_wind_tunnel_2026,
  title = {Synthetic Socio Wind Tunnel: A Multi-Agent Urban Simulation
           for Attention-induced Nearby Blindness},
  author = {Zhou, York},
  year = {2026},
  url = {https://github.com/york-zhouuu/-Synthetic-Socio-Wind-Tunnel-}
}
```

## License

代码:MIT(见 [LICENSE](LICENSE))。地图数据保留各自许可(见上表)。
Code: MIT (see [LICENSE](LICENSE)). Map data remains under the licenses above.

API keys(DeepSeek / Anthropic / Gemini)永远不进 git——见 `.env.example` 列出所需变量。
API keys are never committed; see `.env.example` for the variables you'll need.
