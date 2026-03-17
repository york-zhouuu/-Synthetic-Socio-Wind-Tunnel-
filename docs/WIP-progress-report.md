# WIP：Hyperlocal Border Simulator

## 项目进展汇报结构

---

## Page 1: Project Framing

### 我们关注的核心问题

**边界如何影响：**

- **人的流动（Movement）**
  - 物理路径的选择与限制
  - 通勤轨迹的固化
  - 空间可达性的不平等

- **社会关系（Social Relations）**
  - 邻里连接的建立与断裂
  - 陌生人之间的信任门槛
  - 社区归属感的形成

- **信息传播（Information Flow）**
  - 本地信息的可见性
  - 全球vs在地的注意力分配
  - 信息茧房与认知边界

### 我们的目标

> 通过一个 **instrument（工具/装置）** 去测试和重新理解边界——它如何被强化、如何被削弱、如何被打破。

---

## Page 2: Border Survey / Precedent Research

### 边界分类框架

我们将边界分为三种类型：

| 边界类型 | 定义 | 示例 |
|---------|------|------|
| **Physical Borders** | 物理空间中可见的阻隔 | 墙、围栏、封闭的门、道路分割、地形障碍 |
| **Institutional / Social Borders** | 制度或社会习惯形成的隐性边界 | 社区规约、阶层区隔、文化差异、社交规范 |
| **Informational Borders** | 信息流动中的屏障与过滤 | 算法推荐、信息茧房、本地新闻缺失、注意力垄断 |

### Precedent Research

#### Precedent 1: Schelling's Segregation Model（谢林隔离模型）

- **来源**：Thomas Schelling, 1971（诺贝尔经济学奖得主）
- **核心做法**：
  - 用极简的Agent-based模型模拟城市居住隔离现象
  - 每个Agent只有一条简单规则："如果邻居中同类少于某个比例，就搬走"
  - 即使这个"偏好阈值"设得很低（如30%），最终也会涌现出严重的种族/阶层隔离
- **关键发现**：
  - 微观层面的温和偏好 → 宏观层面的极端隔离
  - 边界不是被"建造"的，而是从个体行为中"涌现"的
- **与我们的关联**：
  - 证明了Agent-based模拟可以揭示社会边界的形成机制
  - 启发我们思考：如果微小规则变化能产生隔离，那反向的微小干预是否能打破隔离？
  - 为我们的"边界强化/减弱/拆除"测试提供理论基础

#### Precedent 2: Stanford Generative Agents（斯坦福小镇）

- **来源**：Stanford University & Google, 2023
- **论文**：*"Generative Agents: Interactive Simulacra of Human Behavior"*
- **核心做法**：
  - 在一个虚拟小镇中部署25个由大语言模型（LLM）驱动的Agent
  - 每个Agent拥有完整的记忆系统、日常计划、社交关系
  - Agent能够自主生成行为：起床、工作、社交、传播信息、组织活动
  - 研究者可以注入事件（如"有人要办派对"），观察信息如何在社区中扩散
- **关键发现**：
  - LLM驱动的Agent可以产生高度拟真的社会行为
  - 记忆、反思、计划三层架构让Agent具备持续的人格一致性
  - 信息在Agent网络中的传播呈现真实的社会动力学特征
- **与我们的关联**：
  - 直接的技术先例——证明了LLM+Agent+空间模拟的可行性
  - 为我们的Agent系统设计（Memory、Goals、Movement）提供参考架构
  - 启发我们的"Local News"机制——通过信息注入观察社区行为变化

#### Precedent 3: Sidewalk Labs / Replica

- **来源**：Sidewalk Labs（Google/Alphabet旗下城市创新实验室）
- **产品**：Replica —— 城市级人口流动模拟平台
- **核心做法**：
  - 基于匿名化的手机位置数据、人口普查、土地使用数据
  - 生成城市人口的"合成副本"（Synthetic Population）
  - 模拟每个合成居民的日常出行：家→工作→购物→娱乐→回家
  - 城市规划者可以测试"如果新建一条地铁线/关闭一条道路"会发生什么
- **关键发现**：
  - 城市是可以被模拟的——通过足够细粒度的Agent行为建模
  - 政策干预的效果可以在虚拟环境中预测
  - 空间变化（交通、土地使用）直接影响人的流动和聚集模式
- **与我们的关联**：
  - 证明了基于真实地理数据（GeoJSON）构建模拟器的可行性
  - 启发我们的"边界条件测试"——改变空间参数，观察行为变化
  - 提供了城市规模模拟的技术思路，我们将其聚焦到Hyperlocal尺度

### Key Insight

从三个先例中，我们提炼出核心洞察：

> **边界不是静态的墙，而是动态涌现的系统属性。**
>
> - Schelling证明：边界可以从微观行为中"涌现"
> - Stanford小镇证明：LLM-Agent可以模拟真实的社会行为与信息传播
> - Replica证明：空间变化可以在模拟中被测试和预测
>
> **我们的机会**：结合三者——用LLM驱动的Agent，在真实地理空间中，模拟边界如何影响人的流动、社交与信息，并测试打破边界的干预手段。

---

## Page 3: Methodology / Stingray Model

### 我们的方法论框架

我们采用 **Stingray Model** 作为项目推进的方法论框架：

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│     TRAIN                 DEVELOP                 ITERATE        │
│       │                      │                       │           │
│       ▼                      ▼                       ▼           │
│   理解问题  ───────────►  构建概念  ───────────►  测试迭代       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Train（训练/理解阶段）

| 步骤 | 内容 |
|-----|------|
| Understand the brief | 理解任务书要求，明确"边界"与"渗透"的课题框架 |
| Survey border types | 调研并分类三种边界类型（物理/制度社会/信息） |
| Analyse precedents | 分析2-3个相关先例项目 |
| Define the research question | 明确研究问题：边界如何影响人的流动、社会关系、信息传播？ |

### Develop（开发/构建阶段）

| 步骤 | 内容 |
|-----|------|
| Form the simulator concept | 形成模拟器的核心概念 |
| Define agents, local news, and boundary conditions | 定义智能体属性、本地新闻机制、边界条件参数 |
| Explore possible intervention scenarios | 探索可能的干预场景设计 |

### Iterate（迭代/测试阶段）

| 步骤 | 内容 |
|-----|------|
| Test baseline and changed border conditions | 测试基准状态与边界变化后的状态 |
| Compare behavioural and spatial changes | 对比行为模式与空间使用的变化 |
| Refine the concept through visualisation | 通过可视化输出迭代优化概念 |

---

## Page 4: Our Concept / Instrument

### 核心定位

> 我们的 instrument **不是一个单一的物理装置**，而是一个 **Hyperlocal Simulator（超在地模拟器）**。

### 技术基础

基于 **真实 GeoJSON 逻辑** 构建一个小镇系统：
- 真实地理数据作为底图
- 可配置的空间元素（道路、建筑、边界）
- 支持边界条件的动态调整

### Agent 系统

地图中的 Agents 具备以下属性：

| 属性 | 说明 |
|-----|------|
| **Memory** | 记忆系统——记住去过的地方、遇到的人、经历的事件 |
| **Goals** | 目标系统——日常任务、社交需求、探索欲望 |
| **Movement** | 移动系统——路径规划、轨迹生成、空间行为 |
| **Local News Context** | 本地新闻上下文——接收并响应Hyperlocal信息刺激 |

### 模拟器测试能力

这个模拟器可以帮助我们测试：

| 测试场景 | 研究问题 |
|---------|---------|
| **边界被强化时** | 当物理/社会/信息边界加强，人的流动、社交、信息获取如何被限制？ |
| **边界被减弱时** | 当边界变得更具渗透性，会产生怎样的行为变化？ |
| **边界被拆除时** | 当边界完全消失，原本隔离的群体如何实现"激进共存"？ |

### 系统示意

```
┌──────────────────────────────────────────────────────────┐
│                  Hyperlocal Simulator                     │
├──────────────────────────────────────────────────────────┤
│                                                           │
│   ┌─────────────┐                                        │
│   │  GeoJSON    │◄──── 真实地理数据                       │
│   │  Map Layer  │                                        │
│   └──────┬──────┘                                        │
│          │                                                │
│          ▼                                                │
│   ┌─────────────────────────────────────┐                │
│   │         Boundary Conditions          │                │
│   │  ┌─────────┬─────────┬─────────┐    │                │
│   │  │Physical │ Social  │  Info   │    │                │
│   │  │ Borders │ Borders │ Borders │    │                │
│   │  └─────────┴─────────┴─────────┘    │                │
│   └──────────────────┬──────────────────┘                │
│                      │                                    │
│                      ▼                                    │
│   ┌─────────────────────────────────────┐                │
│   │              Agents                  │                │
│   │  ┌────────┐ ┌────────┐ ┌────────┐   │                │
│   │  │ Memory │ │ Goals  │ │Movement│   │                │
│   │  └────────┘ └────────┘ └────────┘   │                │
│   │        ┌──────────────┐             │                │
│   │        │Local News Ctx│             │                │
│   │        └──────────────┘             │                │
│   └──────────────────┬──────────────────┘                │
│                      │                                    │
│                      ▼                                    │
│   ┌─────────────────────────────────────┐                │
│   │            Outputs                   │                │
│   │  • Trajectory Maps                   │                │
│   │  • Behavioral Heatmaps               │                │
│   │  • Agent Narratives                  │                │
│   │  • Before/After Comparisons          │                │
│   └─────────────────────────────────────┘                │
│                                                           │
└──────────────────────────────────────────────────────────┘
```

---

## Page 5: What We Will Test Next

### 下一阶段工作计划

| 阶段 | 任务 | 产出 |
|-----|------|------|
| **1. Select** | 选择一个真实小镇作为Hyperlocal案例 | 确定研究场地 |
| **2. Research** | 进行场地调研与边界映射（Site research & border mapping） | 场地分析报告 |
| **3. Identify** | 识别关键的物理边界与信息边界 | 边界清单与分类 |
| **4. Develop** | 开发第一版模拟器结构 | 可运行的原型系统 |
| **5. Define** | 定义Agents、本地新闻机制、干预场景 | 实验设计文档 |

### 详细说明

#### 1. Select a real town as our hyperlocal case
- 选择标准：规模适中、边界类型多样、数据可获取
- 候选场地：[待确定]

#### 2. Conduct site research and border mapping
- 收集GeoJSON地理数据
- 绘制物理边界地图
- 调研社会/制度边界
- 分析信息流动模式

#### 3. Identify key physical and informational boundaries
- 标记关键的物理隔断点
- 识别信息盲区与注意力黑洞
- 分析边界对人流、社交、信息的具体影响

#### 4. Develop the first simulator structure
- 搭建基础地图系统
- 实现Agent基本行为逻辑
- 构建边界条件控制模块

#### 5. Define agents, local news, and intervention scenarios
- 设计Agent类型与属性分布
- 定义本地新闻的内容类型与触发机制
- 规划3-5个核心干预场景

---

## 附：时间线（可选）

| 周次 | 主要任务 |
|-----|---------|
| Week 1-2 | 场地选择与初步调研 |
| Week 3-4 | 边界映射与分类 |
| Week 5-6 | 模拟器原型开发 |
| Week 7-8 | Agent与场景定义 |
| Week 9-10 | 测试与迭代 |

---

*文档版本：WIP v1.0*
*整理日期：2026年3月10日*
