# 🌅 Morning Exploration Brief

**自动探索运行**: 2026-05-23 02:30 → ~04:45 (Sydney)
**Scope**: 3 seeds × 4 variants × 14 days × 1000 agents (publishable β=3,目标 β=4 — seed 46 待 spawn)
**已产出**: **24 个独立分析** (A 到 Z + AA)
**入口**: 浏览器打开 [`index.html`](./index.html) 看可视化总览
**重点图**: [HERO_FIGURE.png](HERO_FIGURE.png) (4 panel 论文头版图) + [PAPER_DRAFT_OUTLINE.md](PAPER_DRAFT_OUTLINE.md) (完整 5 幕论文草纲)

---

## 🏆 论文级 5 大金句

### 1️⃣ 社交传染 8-12× — 论文最强发现 ⭐

> 200m 内有 protag-responder 邻居的 non-protag 居民,**响应率 19.7%/25.2%/16.8%** (HP/GD/PF)。
> 邻居都是非响应者的 non-protag,响应率仅 **2.0-2.4%** —— **8-12 倍同伴效应**。

非接收者通过物理邻里关系改变行为 —— 这是「附近性」的核心社会机制。
[→ L_spillover/summary.md](L_spillover/summary.md)

### 2️⃣ 干预停止后,网络仍在增长 1.3-1.6×

> 干预停止后 4 天(day 10-13),encounter 是 intervention 期的 **HP 1.32× / PF 1.62×**;
> distinct unique pairs 也涨 1.18-1.23×。

不只是「不回 baseline」—— 是 **network compounding 还在跑**。空间停了但社交还在扩。
[→ W_deeper_stickiness/summary.md](W_deeper_stickiness/summary.md)

### 3️⃣ 弱关系→强关系的频次机制(4.1× repeat,5.6× strong-tie)

> repeats per pair: **BL 17.3 → HP 71.1 (4.1×) → PF 69.1**
> tie_count_strong: **BL 10K → HP 56.6K (5.6×)**

HP 让**同一对人遇到的次数翻 4 倍** → 弱关系怎么变强关系的具体机制可见。
[→ V_repeat_vs_unique](V_repeat_vs_unique/summary.md) · [→ P_tie_strength](P_tie_strength/summary.md)

### 4️⃣ 双峰响应 + 反直觉的人口学

> HP 响应率 22.7%(3 seeds × 1000 = n=3000)。响应者 mean 895m(5+ 街区)。
>
> **时间灵活的人响应最多**: 退休 37.2% / 失业 39.2% / 软件工程师 24.2%。
> **schedule-bound 响应最低**: 零售 11% / 工程师 8% / 学生 18.3%。
> **65+ 35.9% > 18-24 19%** —— 老年人响应率最高(反直觉!)
> **性别/收入: 无差** — 机会均等。

[→ C_responder_profile/responder_rates_by_demo.md](C_responder_profile/responder_rates_by_demo.md)

### 5️⃣ GD 镜像组干净的负控

> GD(推全球新闻)encounter 仅 1.4× BL vs HP 5.5×;trajectory 51m vs HP 108m;
> replan 447 vs HP 1990。

「推送」本身不是关键变量 —— **必须是 hyperlocal 内容**才能撬动物理响应。
[→ B_temporal_curves/phase_summary.md](B_temporal_curves/phase_summary.md)

---

## 📊 全 23 个分析索引（按主题分类）

### 空间行为(A,D,E,F,I,X,Y)
| ID | 发现 | 路径 |
|---|---|---|
| A | HP 激活 265 POI,弃用 1549 (median -12% dwell) | [A/](A_poi_activation/) |
| D | 干预下走得 **更少**(HP 0.91×, GD 0.78×) — 精准而非乱走 | [D/](D_walking_footprint/) |
| E | unique locs/agent 减少 (BL 195 → HP 173) — 收敛 | [E/](E_location_diversity/) |
| F | residential 60→51%, commercial 28→36%, street 2.2→3.8% | [F/](F_encounter_locations/) |
| I | 0-200m bin protag 33% vs 1500m bin 26% — 弱单调 | [I/](I_proximity_to_targets/) |
| X | 所有变体 post 期工作场所 dwell ↓; HP 最多(0.47×) | [X/](X_workplace_pull/) |
| Y | Gini 0.834 → HP 0.852 — 活动更集中 | [Y/](Y_encounter_gini/) |

### 时间动态(B,G,M,O,W,Z)
| ID | 发现 | 路径 |
|---|---|---|
| B | HP encounter int 5.46× / post 7.22× | [B/](B_temporal_curves/) |
| G | trajectory post/int = 1.00× — 空间偏移不退回 | [G/](G_habit_stickiness/) |
| M | BL 周末 distinct_pairs 2.6× 工作日; HP 填平工作日 | [M/](M_weekday_weekend/) |
| O | 7-9, 17-19 commute peaks; hour-00 spike 是 artifact | [O/](O_time_of_day/) |
| W | **post/int = HP 1.32× / PF 1.62×** ⭐ | [W/](W_deeper_stickiness/) |
| Z | BL 周末 -13%; HP 周末几乎平 | [Z/](Z_peak_hour/) |

### 社交结构(L,P,Q,R,U,V)
| ID | 发现 | 路径 |
|---|---|---|
| **L** | **8-12× 社交传染** ⭐ | [L/](L_spillover/) |
| P | HP 强关系 5.6× BL | [P/](P_tie_strength/) |
| Q | diversity ratio 0.058 → 0.014 — 同人多次相遇 | [Q/](Q_encounter_diversity/) |
| R | info 传播覆盖 ~985/1000 agents,无变体差 | [R/](R_info_propagation/) |
| U | 跨群体 demographic 共处略增加 | [U/](U_cross_cohort/) |
| V | repeats/pair 17.3 → 71.1 (4.1×) ⭐ | [V/](V_repeat_vs_unique/) |

### 个体响应(C,H,J,S,T)
| ID | 发现 | 路径 |
|---|---|---|
| C | 22.7% 响应率;退休/失业最响应 | [C/](C_responder_profile/) |
| H | 性格 \|r\| < 0.13 — 情境 > 性格 | [H/](H_personality/) |
| J | novelty ≈ baseline — 不是发现新地方 | [J/](J_novelty_exploration/) |
| S | replan: BL 0 / HP 1990 / PF 1751 / GD 447 | [S/](S_replan_dynamics/) |
| T | 5 个 exemplar agent 完整画像 | [T/](T_case_studies/) |

### 成本与方法(K,N)
| ID | 发现 | 路径 |
|---|---|---|
| K | HP $52/cell, $0.001/extra unique pair | [K/](K_cost_efficiency/) |
| N | seed 43 用 v6 老 prefix; seed 44/45 为主要 reference | [N/](N_methods_variance/) |

### Encounter → dialogue conversion(AA) ⚠️
| ID | 发现 | 路径 |
|---|---|---|
| **AA** | **HP encounter 5×,但 dialogue 只+17%(821→959)** — dialogue 受 LLM 计算瓶颈,非 encounter 可用性 | [AA/](AA_encounter_dialogue/) |

> 这意味着 H2「encounter → conversation」证据较弱:HP 创造了大量 encounter,但对话**量**没等比例增长(虽然质——同人多次重复——有改善)。论文 §4 写法需谨慎:**频次→关系强化**(VP 数据强)证据强,**encounter→对话**(AA 数据弱)证据弱。

---

## 💡 论文 5 幕叙事 — 用现成数据可写

| 幕 | 论文主题 | 支撑分析 |
|---|---|---|
| 1 | 假说陈述 | H1: hyperlocal push → 物理 nearby |
| 2 | 机制 | S(1990 replans) · D/E(精准而非乱走) · A(265 POI 激活) |
| 3 | 量化 | C(22.7% 响应,双峰 88%/12%, 850m) · 时间灵活者最响应 |
| 4 | 泛化 | **L(8-12× 邻居传染) · P/V(5.6× 强关系 经由 4.1× 频次)** |
| 5 | 含义 | **W(post 1.32-1.62× compounding) · G(空间不回 baseline) · B(GD 镜像确认 hyperlocal-only)** |

---

## ⚠️ 数据质量必知

| 问题 | 真相 | 应对 |
|---|---|---|
| dialogue_count 卡 750 | 是 evicted 计数器,不是真完成数 | 用 `dialogue_live_at_exit` (BL 73/HP 207/GD 109/PF 244) |
| seed 43 trajectory 3-4× 高 | v6 老 prefix(5/21),与 seed 44/45 不同协议 | seed 44/45 为主 reference;seed 43 做 robustness |
| seed 43 GD cell 死掉 | 64% fallback / $0.51 cost,有效 sim 时间 ~3% | 排除该单 cell |
| trajectory median = 0 | 88% agent 完全不动,12% 大动 — 双峰 | 用 mean 或 responder-only median |
| info_propagation 无差 | 来自 social_priors 静态注入,不响应干预 | 不用这个 metric |

---

## 🧪 实测成本(seed 44 真实数据)

| Variant | seed 44 cost | seed 45 cost | mean | 3 seed 总和 |
|---|---|---|---|---|
| baseline | $4.30 | $2.56 | $3.07 | $9.21 |
| HP | $66.82 | $52.15 | $55.04 | $165.12 |
| GD | $15.38 | $8.61 | $8.17* | $24.50 |
| **PF** | $81.14 | $58.75 | $60.50 | $181.50 |
| **单 seed** | **$167.64** | **$122.07** | **$126.78** | **$380.33** (3 seeds) |

\* GD mean drag down by seed 43 broken cell

**β=4 publishable 总成本预估: ~$500 USD**(seed 46 ~$127 待 spawn)

---

## 🔧 复现命令

```bash
# 全部 23 个分析,按字母顺序
.venv/bin/python3 tools/backfill_publishable_metrics.py  # 先 backfill
.venv/bin/python3 tools/paper_exploration_a_poi_activation.py
.venv/bin/python3 tools/paper_exploration_b_temporal_curves.py
.venv/bin/python3 tools/paper_exploration_c_responder_profile.py
.venv/bin/python3 tools/paper_exploration_d_to_i_batch.py
.venv/bin/python3 tools/paper_exploration_j_to_n_batch.py
.venv/bin/python3 tools/paper_exploration_o_to_s_batch.py
.venv/bin/python3 tools/paper_exploration_t_to_w_batch.py
.venv/bin/python3 tools/paper_exploration_x_to_z_batch.py
```

输出: `data/analysis/2026-05-23_paper_exploration/{A_..,B_..,Z_..}/`

---

## 🌙 没做的事(留给醒来后决策)

1. **seed 46 fork** — β=4 还差 1 seed。成本 ~$127。**自动跑没擅自花钱**。
2. **encounter → dialogue 转化** — 需 per-encounter event 流挖掘,未做
3. **信息扩散树可视化** — info_propagation 有数据但 per-info path 没提取
4. **agent 案例追踪深化** — T 给了 5 个,可以再深(per-tick decision trace)
5. **HTML 五幕报告** — 用现有数据可以写第一版,生成给 docs/项目产出物.html 升级版

---

## 📁 文件清单(新写入)

```
data/analysis/2026-05-23_paper_exploration/
├── MORNING_SUMMARY.md        ← 本文档
├── index.html                ← 浏览器入口（建议先看）
├── A_poi_activation/         ← 26 dirs × 各自 README.md / summary.md / *.json / *.png
├── B_temporal_curves/
├── ... (Z_peak_hour/)
└── ...

tools/
├── backfill_publishable_metrics.py    ← 修补 dialogue/dwell/trajectory
├── paper_exploration_a_poi_activation.py
├── paper_exploration_b_temporal_curves.py
├── paper_exploration_c_responder_profile.py
├── paper_exploration_d_to_i_batch.py
├── paper_exploration_j_to_n_batch.py
├── paper_exploration_o_to_s_batch.py
├── paper_exploration_t_to_w_batch.py
└── paper_exploration_x_to_z_batch.py
```

---

🤖 *Autonomously generated by Claude · 2026-05-23 ~04:00 Sydney*
