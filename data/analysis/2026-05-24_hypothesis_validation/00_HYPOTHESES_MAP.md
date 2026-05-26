# 猜想图谱 · Hypotheses Map

**Date**: 2026-05-24
**Purpose**: 在 v4 项目实验结果重写之前,先把所有「项目开始时的自然猜想」对账一遍。

每条 H 给:
- 自然猜想原文
- 数据真相
- 判定(✅ Confirmed / 🟡 Partially / ❌ Disconfirmed / ⚡ Counter-intuitive)
- 证据来源

---

## A · 因果机制链(从推送到关系)

### H1: hyperlocal push 会让人去推送地点
- **数据**: A_poi_activation — HP 激活 265 POI,弃用 1549 POI(平均 -12% dwell);Mary 真去了真如苑
- **判定**: ✅ Confirmed

### H2: 去了同一地点 → 更多偶遇
- **数据**: B_temporal_curves — HP encounter intervention 期 5.46× BL,post 期 7.22×
- **判定**: ✅ Confirmed

### H3: 偶遇增多 → 新增**弱关系**
- **数据**: 🟡 错向了 — 弱关系几乎没多,**强关系反而 5.6× (P)**。HP 不是制造新人,是把已有弱连接变密。
- **判定**: 🟡 Partially / ⚡ 方向意外

### H4: 弱关系 → 强关系(需要时间累积)
- **数据**: V — repeats per pair BL 17.3 → HP 71.1 (**4.1×**)。机制是"同一对人遇到 4 倍多"
- **判定**: ✅ Confirmed,但机制 surprising — 不是新人变熟,是熟人变更熟

### H13: encounter ↑ → dialogue ↑(简单成比例)
- **数据**: ❌ AA — encounter 5×,dialogue 只 +17%(821→959)。卡 LLM 计算瓶颈
- **判定**: ❌ Disconfirmed

### H14: 推送增加 → 信息传播更广
- **数据**: ❌ R — info 传到 985/1000 全覆盖,4 variant 无差(static social_priors 注入 artifact)
- **判定**: ❌ Disconfirmed (metric 不可用)

---

## B · 用户特征(谁会响应)

### H8: 性格外向 / 高 openness 的人响应更强
- **数据**: H — 性格各维度 |r| < 0.13,性格不解释响应
- **判定**: ❌ Disconfirmed

### H9: **年轻人**响应高(用 app 多)
- **数据**: ⚡ **65+ 35.9% > 18-24 19%** — 完全反过来
- **判定**: ⚡⚡ Counter-intuitive

### H10: 高收入 / 高教育响应更强(科技接受度)
- **数据**: C — 性别 / 收入无显著差,机会均等
- **判定**: ❌ Disconfirmed

### H12: 距离 push target 近的人响应更强(距离梯度)
- **数据**: I — 0-200m bin 33% vs 1500m bin 26%,有梯度但很弱
- **判定**: 🟡 Partially(梯度比预期 flat)

---

## C · 干预设计(推送怎么设计才有效)

### H6: 推送越多越有效(volume = impact)
- **数据**: ❌ 海报已抓: push #1 全效 / #8 半效 / #15 ≈ 0(saturation ceiling)
- **判定**: ❌ Disconfirmed

### H7: 全球新闻也能"激活"本街(都是推送,都消耗注意力)
- **数据**: ❌ GD encounter 1.4× BL vs HP 5.5×;trajectory 51m vs 108m
- **判定**: ❌ Disconfirmed — **内容必须 hyperlocal**

### H5: phone_friction(让手机难刷) → 抬头 → 偶遇
- **数据**: ❌ 单 PF 没自动制造连接 ("phones aren't the bottleneck"),但 PF 在 post 期 compounding 最强(见 H11)
- **判定**: ❌→⚡ 部分反转

---

## D · 持续性(推送停止后会怎样)

### H11: 推送停止 → 回 baseline
- **数据**: ⚡⚡ 反过来: W — post 期 encounter HP **1.32×** intervention / **PF 1.62×** intervention;G — 空间偏移不退回
- **判定**: ⚡⚡ **最强反直觉**

---

## Emergent 发现(没人事先猜的,数据自己冒出来的)

### E1: 8-12× 邻居传染
- 200m 内有 protag-responder 的非接收者,响应率 19.7%/25.2%/16.8% vs 邻居全非响应者的 2.0-2.4%
- 来源: L_spillover
- 含义: "附近性"是社会机制 — 物理邻里关系把行为外溢

### E2: 时间灵活性 > 任何性格/年龄/收入因子
- 退休 37.2% / 失业 39.2% 响应,零售 11% / 工程师 8% / 学生 18.3% 不响应
- 来源: C
- 含义: 推送的"门槛"是日程自主权,不是态度

### E3: 干预下走得**更少**
- HP walking 0.91× BL,GD 0.78×
- 来源: D
- 含义: "推送→乱走"是错觉。精准而非乱走

### E4: unique locations/agent **下降**
- BL 195 → HP 173
- 来源: E
- 含义: HP 让人收敛到推送地点,不是发散探索

### E5: residential dwell ↓ (60%→51%) / commercial ↑ (28%→36%)
- 来源: F
- 含义: 推送本质上是把人从家里**拽出来**

### E6: GD attention drift → physical drift
- Mary 从 Lane Cove 漂去 Chatswood 4.5km 外 12 楼陌生公寓
- 来源: 案例 + B
- 含义: 注意力漂移会带身体漂移,即使没 location prompt

---

## 7 大反直觉点(论文/v4 报告应该放大)

按打脸强度排序:

1. **⚡⚡ 65+ 比 18-24 响应高 90%**
2. **⚡⚡ 推送停止后网络继续涨 1.3-1.6×**
3. **⚡ encounter 5× 但 dialogue 只 +17%** — 物理见面 ≠ 社交连接
4. **⚡ HP 不是创造新弱关系,是把已有弱连接变密** — Granovetter 需修正
5. **⚡ 性格 |r| < 0.13** — 情境 >> 性格
6. **⚡ HP 走得更少**(0.91× BL)— "推送→更多探索"是错觉
7. **⚡ 时间灵活性是唯一显著 demographic 因子**

---

## 新一轮挖掘 · H15-H21(本次任务)

下面 7 条都是 24 个已有分析未覆盖的角度,数据全在,本次逐一挖出。

| # | 猜想 | 状态 |
|---|---|---|
| H15 | 不同推送 *主题* 响应率不同 | 待挖 |
| H16 | 接到推送多久内响应是峰值?衰减曲线 | 待挖 |
| H17 | HP 增加的是已认识人 vs 陌生人? | 待挖 |
| H18 | 同 agent 4 宇宙间物理距离 = attention drift 耦合度 | 待挖 |
| H19 | GD 让人"忘记本街"? | 待挖 |
| H20 | 推送 delivered → consumed → follow_up trip 漏斗 | 待挖 |
| H21 | HP 创造了"孤独的 hub"? | 待挖 |

输出位置: `data/analysis/2026-05-24_hypothesis_validation/H15_topic/ ...` 同目录每个 H 一个子文件夹,统一 summary.md + data json。
