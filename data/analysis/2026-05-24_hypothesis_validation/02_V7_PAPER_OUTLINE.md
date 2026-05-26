# v7 大纲 · Mapping Nearby Blindness

**Date**: 2026-05-24
**Status**: 大纲, 等用户 review 后逐节推进
**Register**: 论文体 · 不娱乐化 · notice 口径全程

---

## 0. 这次重写的论文位置

**核心论点 (the One Sentence)**:
我们用一个全 instrumented 的虚拟悉尼小区, **直接测量** 了"物理 co-presence" 与"social
awareness"之间的 attention gap —— 学界以往只能通过 Bluetooth proximity / social media check-in
等 proxy 推断它的存在, 这是首次直接 quantify 它的结构(depth, spatial distribution, temporal
distribution, asymmetry), 并 comparatively 测试 4 类干预对结构的不同改写效果。

**为什么这个论文位置成立**:
- 文献(Misra 2016 / Brown McGill 2010 / Lu 2024 / Brueckner 2007 / PLOS ONE 2019 中国上海
  check-in study) 都 implicitly 假设或测量 co-presence,但 co-presence ≠ awareness。
- 引文里有原话: "co-presence in urban spaces creates opportunities for different groups to
  meet, serving as a precursor to social interaction. However, co-presence itself is
  insufficient to quantify the social interaction level."
- 但**没人在 1000 人小镇 14 天 × 4 干预 × per-event attention gate 这个分辨率下直接量过**。
- 我们的 contribution: <strong>把 awareness gap 从一个理论概念变成可测、可比、可结构化的现象</strong>。

**这是大叙事弧**:
1. 文献假设 co-presence ≈ awareness (Jacobs/Granovetter 经典)
2. 智能手机时代有 reason 怀疑 gap 拉大 (Misra 2016 已暗示)
3. 但 gap 是什么形状? 有多深? 分布在哪? 没人直接测过
4. 我们用虚拟仿真直接量, 发现 gap 不是 "总体上变小一点", 是有具体 5 层结构
5. 4 类干预对这 5 层结构的改写完全不同 — 这是 implication for intervention design

---

## 文档结构(13 节,大致按论文体)

### §0. Abstract (1 段, 200 字以内)
- 三层骨架: gap 是真的(9.5% baseline) → 它有结构(5 层) → 不同干预改写不同层
- 一句论文 punchline

### §1. Introduction · 从"看不见的边界"到"附近性盲区"
- broader: 21 世纪一类新边界 — 不挡身体, 挡 awareness
- specific: 附近性盲区是这种边界在物理近邻维度上的具体表现
- 研究问题: 这个 awareness gap 多深 / 什么形状 / 能不能 design out?
- 跟 broader 的连接(在 §11 收回来)

### §2. Background · 文献位置
- Jacobs 1961 / Granovetter 1973: 物理 proximity = social fabric 的经典假设
- 智能手机时代的怀疑: Misra 2016 (mere presence reduces empathy) / Brown McGill 2010
  (smartphone 改变 public space interaction) / Lu 2024 (eye tracker 实测 pedestrian
  attention 被 phone 占用)
- 现有测量手段的局限: Bluetooth/GPS/check-in 都是 co-presence proxy, 不是 awareness
  (引 Sevtsuk 2019 PLOS One 上海 check-in study 原话)
- 本研究位置: 首次在 fully instrumented synthetic environment 直接测 attention gate

### §3. Method · 虚拟悉尼小区与 attention gate
- Lane Cove SA2 · OpenStreetMap 地图 · 2021 census 人口分布
- 1000 个 AI agent · 完整生平/personality/routine · LLM 实时驱动
- 4 个 condition: control / hyperlocal-push / global-distraction / phone-friction
- attention gate: 仿真每次记录物理 co-presence (≤5m + 同 tick), 然后 attention model
  根据 phone-use / activity-focus / cognitive-load 决定是否升级为 noticed
- **关键**: noticed 是 attention gate 之后的事件子集, 是这个 paper 的核心 unit of
  measurement
- caveat: attention gate 的具体参数是 simulator 设计的, 没从真人 data 校准 — 我们呈现的
  是 **comparative** finding (4 condition 之间, 5 结构 layer 之间), 不是 absolute 校准过
  的 ground truth

### §4. Finding 1 · 附近盲区的深度 (Depth)
**问题**: baseline 状态下, 一个虚拟居民 14 天里"看见"的邻居占物理同框的多少?

**数据**:
- aggregate: 9.5% (BL pooled seed 44+45, 175,844 物理同框, 16,704 noticed)
- per-agent distribution (待跑): 1000 agent 的 individual notice rate 分布
- 有多少 agent < 5% (深度盲区)? 多少 > 20% (高 awareness)?
- distribution shape: normal / bimodal / long-tail?

**Punchline 候选**:
- 默认状态下 90.5% 的物理邻居在 awareness 之外 — 直接 falsify Jacobs/Granovetter 经典假设的现代版本
- 不是均匀分布的 — 某些 agent ≤ 2%, 某些 ≥ 40%, **这是个内生的不平等**

**待挖**:
- per-agent notice rate distribution histogram
- 这种 distribution 跟 agent 的什么特征相关 (personality / occupation / location density)?

### §5. Finding 2 · 盲区的地理 (Geography)
**问题**: 同一个人, 在 Plaza / 家门口 / 街角 / 公交站 — notice rate 哪里最高 / 最低?

**数据**:
- 每个 location_id 累计有多少 (encounter, noticed) 事件
- compute per-location notice rate
- top 20 "高可见 location" vs top 20 "深盲区 location"
- 按 building_type 分组 (residential / commercial / street / park / worship)

**Punchline 候选**:
- 盲区不均匀: residential 大堂 notice rate 可能 25%(熟人多), 街道路段 5%(过客匿名)
- 物理 attractor (Plaza / Library) 是高 awareness 锚点, 街道是盲区峡谷
- 这意味着 anchor location 不是"创造 visibility", 是"集中已有的 visibility"

**待挖**:
- 全 atlas 9979 location 的 per-loc notice rate (从 events.location_id 算)
- 按 building_type 分组的 boxplot

### §6. Finding 3 · 盲区的时间 (Chronology)
**问题**: 早高峰 / 通勤 / 周末 / 夜班 — 哪个时段 notice rate 最高 / 最低?

**数据**:
- 每个 encounter event 有 simulated_time, 可推 hour-of-day + day-of-week
- compute notice rate per hour bucket
- compute notice rate per day-of-week
- 工作日 vs 周末

**Punchline 候选**:
- 早高峰 7-9am 是盲区最深的时段(大家在赶路, attention 在 phone/podcast)
- 周末某些时段 (e.g. Saturday 10am 市集时间) notice rate 显著上升
- 时间结构跟空间结构耦合 — Plaza 的高 awareness 主要发生在周末/晚高峰

**待挖**:
- per-hour-of-day notice rate (24 bucket)
- per-day-of-week notice rate (7 bucket)
- 热力图: hour × location_type

### §7. Finding 4 · 不对称的看见 (Asymmetry)
**问题**: 当 A 物理同框 B, A noticed B. 同一时刻 B noticed A 吗? 看见是 mutual 还是 one-way?

**数据**:
- 每个 noticed event 有 (agent_id, actor_id, location, tick)
- 对每个 (a, b, tick) — 既找 (a noticed b) 也找 (b noticed a)
- compute mutual-notice rate vs one-way-notice rate
- 进一步: 是否某些 agent 一直被看见但不看见别人(invisible audience)? 反之?

**Punchline 候选**:
- 大多数 noticed 是 one-way: A 注意到 B, B 没注意到 A — **social fabric 是镜像破碎的**
- 某些 agent 是 "super-noticers" (注意到很多人, 但少被人注意到), 某些是 "ghost" (被很多人注意到, 但自己什么都没看到)
- 这种 asymmetry 对 social capital 理论有 implication: 弱关系的形成需要 mutual recognition, asymmetric awareness 不构成关系

**待挖**:
- pair-level mutual vs one-way breakdown
- per-agent: noticing rate vs noticed rate (散点图, 上下对角线分群)

### §8. Finding 5 · 干预对结构的改写
**问题**: 4 类干预对 §4-§7 的 4 层结构有什么不同效果?

**数据**(已经有, 整合):
- HP: aggregate notice rate +0.8 pp (9.5→10.3%); 但 0-100m 盲区扩大 (17.3→8.1% 看见率), 远 anchor 视野打开 (2-5km bucket 5.7→19.9%); 结构: **redistribution not reduction**
- PF: aggregate +5.1 pp (9.5→14.6%); 跨所有 distance bucket 看见率都涨; 结构: **uniform reduction**
- GD: aggregate ≈ BL (9.5 vs 9.6%); 几乎没改; 结构: **invisible preservation**
- compounding: PF post 期 1.62× / HP 1.32× / GD ≈ 1.0× — 改写效应的持久性

**Punchline 候选**:
- 不能用"notice rate 涨没涨"概括 4 类干预的差别 — 它们改写的是结构的不同层
- HP 是 spatial redistribution: 把 awareness 从近邻 transferto 中距离 anchor
- PF 是 attention floor 提升: 全方位增加抬头率
- GD 是 silent preservation: 数字几乎不动, 但 awareness 内容 (who's-noticed-whom) 完全换了
- 选哪种干预取决于你想改写哪一层结构

**待挖**:
- 4 condition × 4 distance bucket 的 notice rate heatmap (已经有, 重 plot)
- 4 condition 的 spatial redistribution map (跟 hero figure 配)

### §9. Finding 6 · 谁能被带回 awareness
**问题**: 4 个干预对 1000 个 agent 不是均匀作用的。 谁的盲区被打开, 谁打不开?

**数据**(已经有):
- BL ↔ HP/PF/GD 末态距离 >100m 的 ~30% "movable" agents
- 按 routine_adherence / age / occupation / household 拆分
- routine 程度低: 44.8% movable / 高: 14.3% (3.1× spread, 最强预测器)
- 年龄: ∩-shape, 25-34 + 65-74 双峰高
- extraversion / 收入 / 性别: 几乎 flat

**Punchline 候选**:
- 反盲区不是 personality 问题, 是 schedule autonomy 问题
- 70% 的人在 BL/HP 末态完全不动 — 干预对绝大多数人 awareness 末态无效
- 反盲区干预的 effective denominator 是 ~30%, 不是 1000

**待挖**:
- (基本上 done from N4), 重 frame 为 "blindness reach analysis"

### §10. Synthesis · 附近盲区的 5 层结构
**问题**: 上面 6 个 finding 综合起来, "附近盲区"是个什么形状的东西?

**论点**:
1. **Layer 1 — depth**: 默认 90.5% 物理邻居被屏蔽 (Finding 1)
2. **Layer 2 — geography**: 不均匀分布; 街道是盲区峡谷, anchor 是 awareness 凹陷岛 (Finding 2)
3. **Layer 3 — chronology**: 早高峰最盲, 周末活动时段最亮 (Finding 3)
4. **Layer 4 — asymmetry**: 大多数 awareness 是 one-way, social fabric 是镜像破碎的 (Finding 4)
5. **Layer 5 — receptivity**: 30% movable / 70% routine-locked, 干预空间结构性受限 (Finding 6)

**4 类干预对 5 层的不同改写**(配 §8 表):
- HP: reshape Layer 2 (redistribute geography)
- PF: lift Layer 1 (deepest reduction in floor)
- GD: silent preservation of all 5 layers (most insidious)
- BL: 是 5 层的自然形状

**论文 punchline (the One Sentence,呼应 §0 abstract)**:
附近性盲区不是一个单一的"看见与否" — 是一个有 5 层结构的现象。
任何 invisible-border 类型的干预都必须先 diagnose 它要 reshape 哪一层, 然后选工具,
不能一概用"提升曝光度"这种粗粒度 KPI。

### §11. Discussion · 对其他 invisible borders 的 implication
- 把 5 层结构 generalize 到其他 invisible border (algorithmic feed, recommendation, search)
- 比如 algorithmic feed 也有 depth (你只看到 1% 的可发现内容) / geography (某些类目深盲)
  / chronology (新内容很快沉底) / asymmetry (你看不到他们但他们看到你) /
  receptivity (algorithm 死忠 vs algorithm-skeptic)
- 5 层框架可以原样移植做其他 border 的 diagnostic
- limitation: 我们在 spatial nearby 这一个域里做了 deep dive, 其他 borders 需要类似工具

### §12. Method Appendix
- 仿真规模数字
- attention gate 的参数(从代码反推)
- 4 condition 的精确推送量/频率/内容
- 数据 footprint
- 复现命令

---

## 让 Finding 紧密咬合 thesis 的检查

每条 finding 都应该能回答: "这告诉我们附近盲区的什么?"

| Finding | 跟 thesis 的咬合 |
|---|---|
| F1 Depth | 盲区**有多深** |
| F2 Geography | 盲区**分布在哪** |
| F3 Chronology | 盲区**何时最深** |
| F4 Asymmetry | 盲区是**单向**还是**双向**的 |
| F5 Intervention | 盲区**能不能被改** |
| F6 Reach | **谁的**盲区能被改 |

6 条都直接锚在 thesis, 没有偏离。

---

## 跟之前 21H + 7N + 5 conclusion 的关系

旧的 21 H 里:
- H1-H7 (因果链/用户特征) → 大部分被收编进 F5 Intervention 和 F6 Reach
- H8-H11 (用户特征 + 时间) → 部分进 F6 Reach, 部分被砍 (跟 thesis 弱相关)
- H12-H14 (设计) → 部分进 F5 Intervention
- H15-H21 → 全部并入对应 finding (push topic 进 F5, 衰减进 F5, drift 进 F5, etc.)

旧 7 个反直觉:
- N1 (hyperlocal paradox) → F5 重点之一
- N2 (PF 新关系工厂) → F5 重点之一
- N3 (时间衰减) → F3 / F5 之间
- N4 (routine_adherence) → F6 核心
- N5 (70% 不动) → F6 核心
- N6 (虹吸 hub) → F2 / F5 之间
- N7 (GD silent) → F5 重点之一

**砍掉的旧 finding** (跟 thesis 弱相关, 进附录 or 不要):
- 推送 saturation ceiling — 偏推送设计, 不偏盲区结构
- 跨职业桥 — 偏社会网络, 不偏 awareness
- 信息传播跳数 — 跟 info diffusion 偏, 不跟 awareness

---

## 还需要跑的新分析

| Finding | 需要新跑 | 工作量 |
|---|---|---|
| F1 per-agent notice rate distribution | YES | 30 min |
| F2 per-POI notice rate (top hot / top cold) | YES | 1 hour (需要 join location_dwell + noticed events) |
| F3 per-hour-of-day notice rate (24 bucket) | YES | 30 min |
| F4 mutual vs one-way notice analysis | YES | 1 hour (pair-level walk) |
| F5 | 主要已有, 整合 | 30 min |
| F6 | 已有 (N4) | done |

总计 ~3.5 小时 fresh 数据挖掘后才能开始正文写作。

---

## 推进节奏建议

1. **你 review 这个大纲** — 是否结构对、 是否漏了什么、 是否多了什么
2. **review 后开始** Finding 1: 我先跑 distribution 数据 + 出 1 张图 + 写 ~400 字 finding 1 给你看
3. 你 react Finding 1, 改完后 Finding 2: 跑 spatial 数据 + 1 张图 + ~400 字
4. ……
5. 全部 6 个 finding 写完后, 拼装 §0 abstract / §10 synthesis / §11 discussion
6. 最后 §1 §2 §3 + footer 一气补

每个 finding 一次只生产 (a) 数据 + (b) 1 图 + (c) ~400 字, 不一把生成全文。

