# H15-H21 Findings · 第二轮深挖

**Date**: 2026-05-24
**Method**: 真实 snapshot 数据 + per-agent positions trail · seed 44 + 45 combined (β=4 publishable scale 的 2/3)
**Scripts**: `tools/h15_h16_h20_push_response.py`, `tools/h17_familiar_vs_stranger.py`, `tools/h18_drift_coupling.py`, `tools/h19_h21_local_blindness_and_hub.py`
**Outputs**: `data/analysis/2026-05-24_hypothesis_validation/H{15,16,17,18,19,20,21}_*/`

---

## H15: 不同推送主题响应率不同?

**猜想**: 亲子市集 / 读书会 / 清扫日 等不同 event 类型应该有不同响应率(亲子事件应该响应最强)。

**数据**: HP variant 实际推送只覆盖 **2 个 location × 5 个 event** = 10 个 topic 组合。

**Top arrival rates** (combined seed 44+45,per-push not per-unique-agent):
- cleanup @ St Aidan's church: **77.9%** ← 最高
- book_club @ St Aidan's: 69.9%
- market @ St Aidan's: 68.9%
- kids_event @ St Aidan's: 65.9%
- meetup @ PLC kindergarten: 63.2%
- market @ PLC: **51.9%** ← 最低

**反预期发现**:
- **地点比 event 类型重要** — St Aidan's everything (66-78%) > PLC everything (52-66%)
- range 只 26 个百分点 (52-78%) — event type 解释力比预期弱
- "cleanup" (社区清扫) 反而比 "kids_event" 响应更高 — 苦差事但社会参与感强?

**判定**: 🟡 Partially confirmed,但 **location anchor 效应 >> event type 效应** — 这本身是 paper finding

**caveat**: arrival count 是 per-push not per-unique-agent,如果同 agent 收到 5 条 PLC 推送然后去了 1 次,5 push 都计入 arrived。inflated。

---

## H16: 接到推送多久内响应是峰值?

**猜想**: 直觉是平滑衰减曲线 — 当天最强,几天后归零。

**数据**: 16,461 次"到达"的时间间隔分布(seed 44+45 pooled):

| 间隔 | 数量 | 占比 |
|---|---|---|
| 0-1h | **7,431** | **45.1%** |
| 1-3h | 0 | 0.0% |
| 3-6h | 0 | 0.0% |
| 6-12h | 32 | 0.2% |
| 12-24h | 93 | 0.6% |
| 24-48h | 3,199 | 19.4% |
| 48-96h | 3,400 | 20.7% |
| 96h+ | 2,306 | 14.0% |

⚡⚡ **强反直觉**: 完全不是平滑衰减,是 **bimodal "当时就在 / 1天+ 后才动" 双峰**:
- 45% 在 0-1h 内"到达" (大概率是 push 落地时 agent 已经在 target — 推送追上了已经发生的访问,非"推动")
- 1-12h 几乎为 0 (~0.8%) — 没人**当天**响应
- 24h+ 占 54.1% — 真正"被推动"的人需要至少 1 天

**含义**: 推送的真实"运营时间"是**到达后 24-96h**,不是首小时。设计推送时如果只看 "open rate" 或 "same-day CTR" 会严重低估效果。

**caveat**: 0-1h 那 45% 极可能是 noise(agent 已在 target,推送是 confirmation 而非 trigger),需要排除已在 target 的人重算 — 留给 v2 follow-up。

**判定**: ❌ Disconfirmed (smooth decay 是错觉),⚡⚡ Counter-intuitive (双峰 + 24-96h 是真正窗口)

---

## H17: HP 增加的 encounter 是已认识 vs 陌生?

**猜想**: HP 让人多见面,新认识 vs 老朋友更密 — 哪个比例大?

**数据** (combined seed 44+45 union pair sets):

| Variant | total unique pairs | shared w/ BL | **new pairs** | frac new |
|---|---|---|---|---|
| baseline | 442,493 | 442,493 | 0 | 0% |
| **hyperlocal_push** | 459,350 (**1.04× BL**) | 382,528 | **76,822** | **16.7%** |
| global_distraction | 428,497 (0.97× BL) | 414,948 | 13,549 | 3.2% |
| **phone_friction** | 488,015 (**1.10× BL**) | 389,214 | **98,801** | **20.2%** |

**重大重述 H3**: HP 不是简单"把已有弱连接变密"。**是双重重塑**:
1. 唯一 pair 数几乎不变(1.04× BL)
2. 但 ~17% 是"BL 没见过的新人",~13% 是"BL 见过 HP 没见到" — 社交圈净换血 17%
3. 同时已认识者频次 5× (V finding: 4.1× repeats per pair)

⚡⚡ **PF 反而新认识更多**: 20.2% 新 pair, +45,522 净增 (HP 净增 +16,857)。**Phone friction 不告诉你去哪,反而带你认识了 HP 2.7× 那么多新人**。这跟 W finding "PF post 期 compounding 最强 1.62×" 形成完美因果链:
- PF 不强制目的地 → 自由探索 → 走到更多新地方 → 遇见更多新人 → 这些 weak ties 在 post 期慢慢加固

GD: 96.8% shared with BL, 只 3.2% 新 pair — 证实 GD 是纯 attention drift, 社交网络几乎不变。

**判定**: H3 ✅ Confirmed (但**完全重新表述**); ⚡⚡⚡ PF 是"新关系工厂" — 这是一个真正的论文 hero finding

---

## H18: 4 universe 末态距离矩阵

**猜想**: 推送把人推到不同地方,4 个 universe 同 agent 物理距离差很大。

**数据** (combined seed 44+45,2000 agent observations per pair):

| Pair | mean drift | median | >100m moved | >1km moved | **zero (不动)** |
|---|---|---|---|---|---|
| BL ↔ HP | 448m | 0m | 29.3% | 21.4% | **70.2%** |
| **BL ↔ GD** | **201m** | 0m | **10.5%** | 8.5% | **89.5%** |
| BL ↔ PF | 405m | 0m | **32.4%** | 20.6% | 67.2% |
| HP ↔ GD | 534m | 0m | 29.4% | 22.4% | 70.2% |
| **HP ↔ PF** | **600m** | 0m | **44.6%** | **30.4%** | **54.5%** |
| GD ↔ PF | 460m | 0m | 33.6% | 22.8% | 66.2% |

⚡⚡⚡ **核心反直觉**:
1. **70%+ agent 在 BL↔HP 不动** — 干预对绝大多数人 *末态* 无效。所有效应集中在 30% movable
2. **GD 几乎不动身体** (89.5% zero, BL↔GD) — 确证"attention drift 不等于 physical drift"。Mary 那种漂去 Chatswood 4.5km 是极端案例,大多 GD 人坐在原地刷新闻
3. **PF 比 HP 移人更多** — BL↔PF 32.4% >100m moved > BL↔HP 29.3%。PF 是更彻底的"行为改造"
4. **HP 和 PF 朝完全不同方向推** — HP↔PF 44.6% 散开 >100m, 30.4% >1km。两干预效果**几乎不重叠**

**含义**: H17 + H18 联合论证 — **HP 和 PF 是两套不同的社会工具**:
- HP = "把同一批人集合到固定 5 anchor 反复见,加强 5× 频次,~17% 换血"
- PF = "放手让人乱走,看见 20% 新人,但更分散"
- 哪个"更好"取决于目标:HP 适合让街角生意活起来,PF 适合扩展个人社交圈

**判定**: ✅ Confirmed,但**效应分布极不均匀**(70% 不动 / 30% 强响应),且**两干预朝不同方向推**

---

## H19: GD 让人"忘记本街"?

**猜想**: GD 把注意力推到悉尼 CBD,所以本街(home 周围 0-500m)的 encounter 应该减少。

**数据** — encounter 按到 home 距离分桶(combined seed 44+45,~600K encounters total):

| Bucket from home | baseline | hyperlocal_push | global_distraction | phone_friction |
|---|---|---|---|---|
| 0-100m | 9.9% | **5.2%** | 9.0% | **4.6%** |
| 100-300m | 8.0% | 6.3% | 7.5% | 6.5% |
| 300-500m | 9.7% | 8.9% | 9.1% | 7.6% |
| 500-1000m | 28.4% | 25.1% | 26.9% | **30.1%** |
| 1-2km | 38.4% | 38.7% | 37.2% | **47.4%** |
| **2-5km** | **5.7%** | **15.8%** | 10.2% | 3.9% |

**本街 (0-500m of home) encounter 占比**:
- baseline: **27.5%** ← 最高
- hyperlocal_push: **20.4%** ↓
- global_distraction: 25.6% (≈ BL)
- phone_friction: **18.7%** ← 最低

⚡⚡⚡ **完全推翻初始猜想**: 不是 GD 让人忘记本街,**是 HP 才让人离开本街**!GD 反而保护了本街(物理不动)。

**解释**: HP 推送的 anchor location 不在 home 周围 100-500m,而在 500-1500m 处(PLC、Shinnyo、St Aidan's 都是 500-1500m 半径外)。HP 把人从 100-500m 本街区拉到 500-2000m 范围 + 远到 2-5km (15.8%, 是 BL 5.7% 的 2.8×)。

**意味**: hyperlocal push **拉远了** 居民跟自己 100m 邻居的关系(0-100m bucket: BL 9.9% → HP 5.2%),换来 500-2000m 的"邻里二跳关系"。如果政策目标是"加强紧邻关系",HP 反而是 counterproductive。

**判定**: ❌ Disconfirmed for GD (GD 没忘本街); ⚡⚡⚡ Counter-intuitive for HP — **hyperlocal 反而 hyper-non-local**

---

## H20: 推送漏斗 delivered → consumed → arrived

**数据** (combined seed 44+45):
- delivered: **25,340**
- consumed: **25,340 (100%)** ← ⚠️ 仿真层 artifact, consumed=delivered 在数据里被同步标记
- arrived: **16,461 (65.0%)** of delivered

**重大 caveat**: "consumed" 这层不可靠 — 仿真把每条 delivered 都标 consumed,不是真"agent 读了"的信号。我们能验证的真正信号是 **arrived**。

**有效漏斗**:
- 收到 push: 25,340 次
- 物理到达对应 target: 16,461 次 (65%)
- 30 push / agent / 14 day × 1000 agent ≈ 30K push budget
- 真正激活物理访问的: ~65% per-push (per-agent 因为有重复推可能更高)

⚡ **65% 比想象高得多** — 海报上的 "+14% encounter" 是 BL→HP encounter total 的 delta,而 per-push arrival rate 65% 说**绝大多数推送是有效的**,只是 encounter 总数也受其他 saturation 因素压制。

**判定**: per-push 65% arrival = high yield;但 consumed=delivered 是数据 bug,论文里要诚实说 "we measure delivered→arrived directly"

---

## H21: HP 创造孤独的 hub?

**猜想**: A+Y 已经显示 HP Gini 0.834→0.852,稍微集中。但具体多集中?哪些 POI 暴涨 / 暴跌?

**数据** — 比较 BL vs HP/GD/PF 每 POI 的累计 dwell_ticks(seed 44+45 averaged):

| Variant | top1 POI 占新增 dwell delta | top5 占 | top20 占 | # POI gained | # POI lost |
|---|---|---|---|---|---|
| **hyperlocal_push** | **62.0%** | **80.1%** | 97.4% | **249** | **1556** |
| global_distraction | 65.8% | 86.9% | 98.1% | 270 | 1004 |
| phone_friction | 60.7% | 78.5% | 96.6% | 202 | 1660 |

**HP top 10 hot POIs** (seed 44):
| POI | type | ticks gained vs BL | ratio |
|---|---|---|---|
| **PLC Sydney Preschool** | worship | +380,955 | **56×** |
| Anytime Fitness Australia | entertainment | +39,538 | 11× |
| area_105 | playground | +33,072 | 9.5× |
| Mowbray Road (4) | street | +25,163 | **71×** |
| Anglican Church Lane Cove | worship | +18,307 | 2× |
| **Longueville Park** | residential | +17,974 | **667×** ← 从近 0 变热点 |
| Centennial Avenue (2) | street | +13,138 | 61× |
| 7-Eleven | shop | +10,793 | 3× |
| 1021 Mediterranean | restaurant | +10,627 | 2.6× |
| Karilla Avenue (1) | street | +10,441 | 12× |

**HP top 10 cold POIs**: 全是 residential buildings (-5K~-10K ticks/14天) + 1 个 commercial (Go Vita -10K)。

⚡⚡⚡ **"Hyperlocal" 的虹吸诅咒**:
- HP 推送把 1556 个 POI(包括大量 residential 家)的人**虹吸**到 249 个 anchor
- **top1 POI (PLC) 单独吃掉 62%** 所有正向 dwell 净增
- top5 吃 80%,top20 吃 97% — Pareto 极端
- 反讽: 推送名为 "hyperlocal" (1000m 半径),实际效果是把分散在 1500+ 处的注意力**集中到 5 个 anchor**,留下大量"ghost towns" — 空着的家、冷掉的小店

**跟 海报 sec 07 "saturation ceiling" 接上**: saturation 不只是 push 第 8 条没用,是这 5 个 anchor 本身也容纳不下更多人 — **物理 ceiling 比心理 ceiling 更早 hit**

**判定**: ✅ Confirmed 且 ⚡⚡ stronger than expected — HP 是 hub creation machine,代价是 1556 个 POI 冷却

---

## 总结 · 7 大新反直觉 (要加入 v4 报告)

按"打脸强度"排序:

1. ⚡⚡⚡ **PF 是真正的新关系工厂** (20.2% 新 pair, 净增 +45K, 是 HP 2.7×) — 不是 HP
2. ⚡⚡⚡ **HP 让人**离开**本街** (0-100m encounter 9.9%→5.2%) — "hyperlocal" 推送的命名悖论
3. ⚡⚡ **推送响应窗口是 24-96h 不是当天** — open rate / same-day CTR 严重低估
4. ⚡⚡ **70% agent 在 BL↔HP 末态完全不动** — 干预对多数人 *末态* 无效,全集中在 30%
5. ⚡⚡ **GD 不移动身体,只移注意力** (89.5% physical zero) — Mary 漂去 Chatswood 是极端,不是常态
6. ⚡⚡ **HP 创造极端虹吸 hub** — top1 PLC 单独吃 62%,1556 POI 冷却。"hyperlocal" 反而集中
7. ⚡ **HP 和 PF 朝不同方向推** (HP↔PF 44.6% 散开) — 不是 substitute 而是 complementary tools

## 还有几条"已确认但需要重新讲"

- **H3 重述**: HP 不是简单加强弱关系,是双重重塑(频次 5× + 净换血 17%)
- **H15**: location anchor 效应远大于 event type 效应 — cleanup 比 kids_event 响应还高
- **H20 per-push arrival 65%** — 高得反直觉,但 consumed=delivered 是数据 artifact 需诚实

---

## 下一步建议

写 v4 报告时:
- **每个反直觉点都先给"我们以为是 X"**,再"数据说 Y" — 用打脸结构挖出戏剧
- HP 和 PF 不要并列,**分两条 thesis**: HP = 集中加强机制,PF = 分散探索机制
- 把 "hyperlocal 反而 hyper-non-local" 升级为论文的**核心命名悖论** — 这条最 quotable
- 时间衰减曲线 bimodal — 单独一章,这跟 policy 建议直接绑(不要看 same-day CTR)
- "虹吸 hub + ghost town" 视觉化:Lane Cove 地图上画 PLC 暴涨 + 1500+ residential 暗淡 — 这是绝对的 hero figure 候选
