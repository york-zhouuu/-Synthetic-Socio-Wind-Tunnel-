# Synthetic Socio Wind Tunnel — System Architecture

```mermaid
graph TB
    subgraph INPUT["🌆 Input Layer"]
        OSM["OpenStreetMap\nGeoJSON"]
        PROG["Programmatic\nBuilder"]
    end

    subgraph INFRA["🏗️ Infrastructure Layer"]
        direction LR
        ATLAS["🎭 Atlas\n静态地图\n(Read-Only)\n──────────\nRegion / Building\nRoom / Door\nContainer"]
        LEDGER["📋 Ledger\n动态状态\n(Read-Write)\n──────────\nEntityState\nItemState\nDoorState"]
        CART["🗺️ Cartography\nGeoJSON Importer\nMap Builder"]
    end

    subgraph ENGINE["⚙️ Simulation Engine"]
        SIM["SimulationService\nmove / interact"]
        NAV["NavigationService\n路径规划"]
        COL["CollapseService\n薛定谔细节生成"]
        PER["PerceptionPipeline\n主观视角渲染\n罗生门效应"]
    end

    subgraph AGENTS["🧠 Agent Layer  ×1000"]
        direction TB
        ORCH["Orchestrator\n模拟时钟 · tick推进\n──────────\nModelBudget\n动态模型等级分配"]

        subgraph PROTO["Protagonist ×10\n(Claude Sonnet)"]
            P1["完整三层记忆\n多轮社交对话\n第一人称叙事"]
        end

        subgraph DYN["Dynamic Agents ×990\n(Haiku / Sonnet-mini)"]
            D1["计划制LLM决策\n基础记忆流\n按场景动态升级"]
        end

        BRAIN["Agent Brain\n──────────\nPlanner  日程生成\nMemory   三层记忆\nSocial   关系网络\nProfile  性格习惯"]
    end

    subgraph HACK["🔬 Experiment Layer"]
        direction LR
        INT["Policy Hack\nIntervention Engine\n──────────\n💬 Info Injection\n🚪 Space Unlock\n🎹 Object Placement\n🐱 Task Assignment\n👁️ Perception Mod"]
        EXP["Experiment Config\n──────────\nBaseline Day 1-3\nIntervention Day 4\nObservation Day 5-10\n──────────\nControl Group\nTreatment Group"]
    end

    subgraph OUTPUT["📊 Output Layer"]
        TRAJ["Trajectory\n轨迹偏离度\n弯曲度分析"]
        SOC["Social Graph\n弱连接数量\n网络密度变化"]
        SPACE["Space Activation\n空间激活热力图\n多样性指数"]
        NARR["Narrative\n罗生门叙事\n第一人称日记"]
    end

    OSM --> CART
    PROG --> CART
    CART --> ATLAS
    CART --> LEDGER

    ATLAS --> SIM
    LEDGER --> SIM
    SIM --> NAV
    SIM --> COL
    SIM --> PER

    PER --> BRAIN
    NAV --> BRAIN
    BRAIN --> SIM

    BRAIN --> PROTO
    BRAIN --> DYN
    ORCH --> BRAIN
    ORCH --> INT

    INT --> EXP
    EXP --> AGENTS

    ORCH --> TRAJ
    ORCH --> SOC
    ORCH --> SPACE
    PROTO --> NARR

    style INPUT fill:#1a1a2e,stroke:#e94560,color:#eee
    style INFRA fill:#16213e,stroke:#0f3460,color:#eee
    style ENGINE fill:#0f3460,stroke:#533483,color:#eee
    style AGENTS fill:#533483,stroke:#e94560,color:#eee
    style HACK fill:#e94560,stroke:#ff6b6b,color:#fff
    style OUTPUT fill:#1a1a2e,stroke:#4ecdc4,color:#eee
```

## Legend

| Layer | Role |
|-------|------|
| **Atlas** | Frozen stage set — walls, doors, rooms (never mutates) |
| **Ledger** | Live prop table — positions, items, states |
| **SimulationService** | The only writer to Ledger |
| **PerceptionPipeline** | Subjective rendering — same scene, different views |
| **Policy Hack** | Experimental variable — injects stimuli into the simulation |
| **ModelBudget** | Dynamic LLM grade allocation — 1000 agents, ~$3-5/simulated day |
