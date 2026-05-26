# Paper Draft Outline · 五幕叙事 with data-backed sections

> Auto-generated outline based on 23 analyses + project's 5-act structure (`docs/agent_system/13-research-design.md`).
>
> Each section comes with: (a) target message, (b) supporting data analyses, (c) sample copy / paragraph draft user can adapt.

---

## 🎬 Title (working)

**Hyperlocal Push as Attention Reweighting: Evidence from a 1000-agent Synthetic Wind Tunnel of Lane Cove**

Alt: 「附近性盲区 vs 超在地推送:一座虚拟悉尼街区的注意力重权实验」

---

## Abstract (~250 words target)

**Sample draft**:

> 高密度城市的"附近性盲区"——居民物理上紧邻却社会上疏离——常被归咎于手机注意力的"全球化"。本文用一个 1000-agent 多智能体合成系统(悉尼 Lane Cove 真实街区,14 天 sim)定量测试"超在地推送"反向干预的有效性。
>
> 4 个对照变体(对照 / 超在地推送 HP / 镜像全球新闻 GD / 反技术减推送 PF)各跑 3 个随机种子。结果显示:
>
> - HP 在 6 天干预期内使 **22.7% 的居民物理位移**(中位数 850m),响应模式呈双峰(88% 不动 / 12% 大动);
> - 干预停止后 4 天里,encounter 数继续以 **1.32× 速度** 增长(network compounding),空间偏移不退回 baseline;
> - **200m 物理邻居间出现 8-12× 同伴效应**——非接收者通过邻里关系传染响应;
> - 镜像全球新闻组 GD 仅 1.4× encounter 增长,证实「推送」本身不是关键变量——必须是 hyperlocal 内容才能撬动物理响应;
> - 响应者画像反直觉:**老年(65+) 35.9% 响应率 > 年轻(18-24) 19%**,**时间灵活的人(退休/失业) 响应最多**,性别/收入无差。
>
> 我们由此提出"附近性盲区"可逆性的 3 个机制证据(空间重锚 / 频次→关系强化 / 邻里传染),并将之与现实城市级数字政策的潜在风险与潜力对接。

---

## §1 Introduction (~3 pages)

### 1.1 The puzzle
- High-density urban paradox: physical proximity has never been smaller, social distance has never been greater
- Lane Cove as case study (give 1-2 paragraphs of vivid texture)

### 1.2 Hypothesis (H1)
- Attention-induced Nearby Blindness: phone attention displaces the ~1000m physical environment
- Sample sentence: *"Modern recommender systems route every glance toward global news and distant events, leaving a 1,000-metre blind spot around each person's actual life."*

### 1.3 Why a wind tunnel (synthetic instrument)
- Argument: real-city A/B testing of hyperlocal-push interventions is infeasible at this scale (consent, regulatory, cost). A simulation with 1000 cognitively-modeled agents + real Lane Cove geometry allows treatment & 3 distinct counter-controls (rival hypothesis framing).
- Compare to physical "cloud chamber" analogy.

### 1.4 Contribution preview
- 5 paper-headline findings (refer reader to Discussion)

**Supporting**: `docs/项目产出物.html` (公开 5 deliverables) + Lane Cove 真实地图引用

---

## §2 Method (~4 pages)

### 2.1 Synthetic environment
- Lane Cove atlas: 5,722 buildings (residential 93%) + 4,257 outdoor areas (95% street); coords from OSM + Overture
- 1000 LLM-cognitively-modeled agents (500 protagonist + 500 background)
- Agent profile: 40+ dimensions (age, occupation, household, personality {big5+curiosity+routine_adherence+risk_tolerance}, walking_speed, work_mode, …)

### 2.2 Experimental design (4 variants + share-baseline-prefix)
- Phase A (day 0-3): all variants share same baseline run (frozen prefix; identical RNG seed)
- Phase B (day 4-9): intervention applied per variant
- Phase C (day 10-13): post-period, intervention removed; measure persistence

| Variant | Mechanism | Mirror? |
|---|---|---|
| baseline | no push | — |
| hyperlocal_push (HP) | push: local events within 1000m | — |
| global_distraction (GD) | push: distant news / global events | mirror to HP |
| phone_friction (PF) | reduce push frequency, quiet notifications | anti-tech mirror |

- **3 random seeds** (43, 44, 45). seed 46 spawn pending (β=4 target).

### 2.3 LLM backbone
- DeepSeek v4-pro (sonnet-tier decisions) + v4-flash (haiku-/nano-tier supporting tasks)
- Volces Doubao Seed Lite (dialogue text generation, off the DeepSeek queue)
- Total LLM cost per seed: ~$127 USD (seed 44 measured); β=4 budget: ~$500

### 2.4 Metric ontology
- Spatial: dwell ticks by location type, trajectory deviation from baseline, walking footprint, POI activation
- Social: distinct encounter pairs, dialogue events (live + evicted), weak/strong tie counts
- Behavioral: replan events (push acceptance), info propagation hops

**Supporting**: `N_methods_variance/summary.md`, `K_cost_efficiency/summary.md`

---

## §3 Results — H1: Spatial response (~3 pages)

### 3.1 Bimodal response distribution
- **22.7% of agents physically respond** to HP push (n=3000 pooled, threshold > 20m mean dev/tick during intervention)
- Responders shift by **median 850m / mean 895m** (5+ city blocks)
- 77.3% of agents show 0 baseline deviation (anchored to routine)
- **Insert: Panel 3 of HERO_FIGURE.png** (or [`C_responder_profile/deviation_histogram.png`](C_responder_profile/deviation_histogram.png))

### 3.2 Mechanism: not "more walking", "different walking"
- HP induces 0.91× total walking distance vs BL (D) — **less wandering, more directed motion**
- HP induces 0.89× unique locations visited vs BL (E) — **focus, not exploration**
- POI activation: HP activates 265 locations >10%, deactivates 1549 (A) — concentrating attention, not diffusing
- **Insert: [`A_poi_activation/heatmap_hyperlocal_push.png`](A_poi_activation/heatmap_hyperlocal_push.png)**

### 3.3 Where do encounters happen
- HP: residential 60→51%, commercial 28→36%, street 2.2→3.8% (F) — **OUT of home, INTO commercial/street**
- PF nearly identical pattern — distinct mechanism (less phone) reaches same spatial outcome
- GD: residential 60→57.5%, commercial unchanged — global news doesn't physically displace

### 3.4 Counter-control validates mechanism
- GD encounter 1.4× BL vs HP 5.5× BL (B)
- GD trajectory 51m vs HP 108m mean deviation
- GD replan 447 vs HP 1990
- → "Just any notification" is not the active ingredient. The content type matters.

---

## §4 Results — H2: Social response (~3 pages)

### 4.1 Re-encounter density → tie strength
- HP: **repeats per pair 17.3 → 71.1 (4.1×)** vs BL (V)
- HP: **strong ties 10K → 56.6K (5.6×)** vs BL (P)
- HP: weak ties remain similar (already-existing weak ties consolidate to strong)
- → **Mechanism: HP makes same people meet 4× more often → weak ties become strong.**

### 4.2 Diversity vs concentration
- Encounter diversity ratio (unique pairs / total): BL 0.058 → HP 0.014 (Q)
- Gini coefficient of location dwell: BL 0.834 → HP 0.852 (Y)
- → HP **concentrates** rather than **diversifies**. It deepens existing neighborhood, doesn't widen it.

### 4.3 The Mirror (GD) on social dimension
- GD: weak ties identical to BL, strong ties +13% only
- → Confirms: hyperlocal-content, not push-action, drives social bonding

**Supporting**: `P_tie_strength/tie_strength_curves.png`, `V_repeat_vs_unique/summary.md`

---

## §5 Results — H3: Network spillover (~2 pages)

### 5.1 The 8-12× peer effect
- Non-protagonist agents (n=1400 per variant pooled): they receive **NO direct pushes**
- Their response rate depends sharply on **whether protagonist neighbors (200m) responded**:

| Group | n | Responder rate (HP) |
|---|---|---|
| Non-protag with ≥1 protag-responder neighbor | 1170 | **19.7%** |
| Non-protag with only non-responder protag neighbors | 207 | **2.4%** |
| Non-protag with no protag neighbor at all | 15 | 13.3% (small n) |

- → **8× difference** depending on whether you have any responding neighbor.
- → The intervention propagates through physical neighborhood ties, even to non-targets.

### 5.2 Implication
- "Hyperlocal" intervention is not a per-recipient mechanism. It's a **community-level mechanism via social diffusion through co-presence**.
- Has direct policy implication: a small subset of "activatable" residents amplifies citywide.

**Supporting**: [`L_spillover/summary.md`](L_spillover/summary.md), Panel 1 of HERO_FIGURE.png

---

## §6 Results — H4: Temporal dynamics (~2 pages)

### 6.1 Post-period network compounding
- Encounter count (per day, mean across 3 seeds):
  - BL: ~585K (baseline), ~584K (intervention), ~552K (post) — slight decline
  - HP: ~585K → ~3.20M → **4.22M** (intervention 5.46× BL; **post 7.22× BL**)
  - PF: ~585K → ~2.75M → **4.47M** (intervention 4.70× BL; **post 7.64× BL**)
  - GD: ~585K → ~813K → ~882K (intervention 1.39× BL; post 1.51× BL)

- **Post-period > intervention-period for HP/PF.**

### 6.2 Spatial vs social dynamics differ
- Trajectory deviation: post/intervention ratio = **1.00×** across all cells (G) — **spatial position freezes** at new equilibrium
- Encounters: post/intervention ratio = **1.32× HP / 1.62× PF** (W) — **social activity compounds**

- → Geometric arrangement settles, but social outcomes (encounters, ties) continue to bloom.

### 6.3 Interpretation
- Once a critical mass of agents reaches a new spatial equilibrium, the **network effect** (re-encounter density) compounds independently of push reinforcement.
- This is the most policy-relevant finding: **interventions don't need to run forever**; once the network re-anchors, it sustains.

**Supporting**: [`B_temporal_curves/`](B_temporal_curves/), [`W_deeper_stickiness/`](W_deeper_stickiness/), Panel 2 of HERO_FIGURE.png

---

## §7 Results — Who responds (~2 pages)

### 7.1 Counter-intuitive demographics
- **Older respond more**: 65+: 35.9% vs 18-24: 19.0%
- **Time-flexibility wins**: retired 37.2%, unemployed 39.2%, software developer 24.2%
- **Schedule-bound respond least**: retail worker 11.0%, engineer 8.0%, construction 17.4%
- **Gender**: 22.3% female, 23.2% male — no difference
- **Income tier**: 21.9-23.2% across tiers — no gradient
- **Protagonist effect**: 29.3% vs 16.1% non-protag (direct push receipt) — +13pp

### 7.2 Personality matters less than circumstance
- All Big-5 traits: |Pearson r| < 0.13 vs deviation_m
- Strongest: routine_adherence -0.123 (weak negative), curiosity +0.111 (weak positive)
- → **Circumstance > personality.** Free-time-having is the dominant predictor.

### 7.3 Spatial inequality
- 0-200m bin protagonist responder rate: 33.2%
- 1500m+ bin: still 26.1%
- → Mild monotonic but not steep — within Lane Cove (~2km diameter), proximity is not the dominant factor.

**Supporting**: [`C_responder_profile/responder_rates_by_demo.md`](C_responder_profile/responder_rates_by_demo.md), [`H_personality/summary.md`](H_personality/summary.md), [`I_proximity_to_targets/summary.md`](I_proximity_to_targets/summary.md)

---

## §8 Discussion (~3 pages)

### 8.1 Three mechanisms of nearby-blindness reversal
1. **Spatial re-anchoring** (§3, G): once agent's daily path includes push-target, they revisit even without pushes (1.0× post/int)
2. **Re-encounter strengthening** (§4): same people meet 4× more often → weak ties become strong (5.6× strong ties)
3. **Neighborhood diffusion** (§5): 8-12× peer effect propagates response through 200m physical neighborhood

### 8.2 Mirror confirmation: it's the content, not the push
- GD shows ~1.4× encounter ↑ (vs HP 5.5×) — push action insufficient
- PF shows ~4.7× encounter ↑ (similar magnitude as HP) — reduction of phone counterforce also works
- → **Mechanism is attention reallocation toward physical environment**, regardless of whether achieved through push (HP) or reduction (PF)

### 8.3 Distributive justice angle
- No gender / income gradient → opportunity-equal intervention (in our simulation)
- Older / time-flexible benefit MORE → may align with goals of reducing senior isolation
- Schedule-bound workers benefit LEAST → not a substitute for labor policy

### 8.4 Limitations
- Synthetic ≠ real. LLM agents are not human (the wind-tunnel framing — exploratory instrument, not deployable policy)
- 1 city × 4 variants × 3 seeds < publishable β=4 target (seed 46 pending)
- 14-day window may not capture multi-week saturation / regression
- No measure of dialogue topic / quality (only completion count)
- See `docs/limitations-ethics.md`

### 8.5 Future work
- Encounter→dialogue conversion analysis (data exists, not analyzed here)
- Information cascade tree depth (data exists, not extracted)
- Replicate in different city geography (currently Lane Cove only)
- Real-resident pilot with consent + governance scaffolding

---

## §9 Conclusion (~1 page)

> The "nearby blindness" carved by attention globalization is, in our synthetic wind tunnel, **reversible at the network level**:
>
> 1. 22.7% of residents physically respond to hyperlocal push (median shift 850m).
> 2. Their response triggers an 8-12× peer-effect spillover through 200m physical neighborhood.
> 3. Once shifted, the network keeps compounding (1.32-1.62× post-period encounter growth) without further intervention.
>
> Whether this maps onto real residents is an empirical question requiring consent-based deployment, not the simulation alone. But the wind-tunnel evidence makes the physical-attention-reweighting hypothesis **specific, testable, and falsifiable**.

---

## Appendix A: Reproducibility

- All 23 analyses regeneratable via:
  `tools/paper_exploration_{a..z}*.py`
- Raw run data: `data/experiments/20260522_*_publishable_v7_day4to13_fork_seed{43,44,45}`
- Population caches: `data/population_cache/v1/`
- Atlas: `data/lanecove_atlas.json` (~13MB, OSM + Overture derived)
- Cost log: total ~$380 (3 seeds × 4 variants); per-seed ~$127

## Appendix B: Data quality notes

(see [`N_methods_variance/summary.md`](N_methods_variance/summary.md) for full detail)

- seed 43 baseline-prefix is from v6 (May 21), seeds 44/45 from v7 (May 22) — use 44/45 as primary, 43 as robustness.
- `dialogue_count` is evicted-counter (saturates ~750 across variants); use `dialogue_live_at_exit` for variant comparison.
- `trajectory_median` = 0 reflects bimodality, not measurement error.
- `info_propagation` derived from static social_priors, not intervention-sensitive — exclude from variant comparison.

---

🤖 *Outline auto-generated 2026-05-23 ~04:30 by Claude. Adapt freely.*
