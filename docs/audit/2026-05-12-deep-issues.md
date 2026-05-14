# 项目深度问题清单 · 2026-05-12

> realism 11 维 audit 修完后做的"超越代码 bug 层"的反思——
> 看 thesis 机制、方法学、实验设计、架构层面是否站得住。
> 数据来自 50 agent × 1 day × 4 variant stub smoke (2026-05-12)。

---

## 🔥 A 类 · thesis 核心机制根本没建模（最致命）

> **2026-05-12 UPDATE · A1 RESOLVED**：`add-attention-induced-nearby-blindness`
> change 实现完成。1-day smoke (50 agent × 4 variants × stub) 实测 thesis 方向：
> - pf noticed_enc +21.2% / noticing_rate +4.45% (thesis 预期 ✓)
> - gd noticed_enc −7.7% / noticing_rate −0.27% (thesis 预期 ✓)
> - hp ~flat（推送量小，10 protag × 18 push 信号小）
>
> 实现细节：per-agent phone_attention ∈ [0, 1.5] 状态；
> notification 增 attention（urgency × responsiveness × openness）；
> per-tick decay (×0.85)；noticing gate `(1−max(a,b))×0.3` 决定 colocation
> 是否升级为 weak_tie。1334 test PASS / 0 regress.

### A1 · "Attention-induced nearby blindness" 是空壳 [RESOLVED 2026-05-12]

thesis 中心论断："手机注意力被夺 → 看不见附近邻居 → 不形成弱关系"。

**代码现实**：
- `phone_feed_proxy = delivered_notifications / (n_agent × n_day × 20)` —— 这是
  **推送频率代理**，不是"agent 在看屏幕"
- encounter detection (`_detect_encounters`) 是纯地理 co-location：
  同 `location_id` + 同 tick → encounter。**无 attention gate**
- agent 是否"低头看手机" → 是否"注意到旁边邻居" 链条**完全没建模**

**实测后果**：
```
                  encounters    weak_ties
baseline              13758            8
hyperlocal_push       13758            8   ← byte-equal to baseline
global_distraction    12864            5
phone_friction        13679            8
```

hp 推 18 次 local_news，但 encounter 数与 baseline **完全一致**。
phone_friction "减少手机吸力" 却让 encounter 只降 0.6%（13758→13679）。

**根因**：scripted agent 占 90%，他们的 routine 不受 push 影响；
push 只改变 10 protag，但 encounter 由 990 scripted agent 主导稀释。

**thesis 要测的现象不在模拟里发生**，跑 publishable 出的结果就是"什么都没发生"。

### A2 · 缺 social noticing 模型

两 agent 同 cafe，encounter += 1。但 thesis 关心：
- 看到了吗？（visual attention）
- 招呼了吗？（social initiative）
- 记住了吗？（memory consolidation）

current encounter 不区分"两人都低头刷手机"vs"两人面对面聊天"——但 thesis 论文写出来就是关于这区分的。

---

## ⚠️ B 类 · variant 效应弱到不可测

### B3 · paired mirror 失效

spec 要求 `hp.traj_dev < gd.traj_dev`（hp 拉近 target / gd 推远）。

**实测**：
- `hp.trajectory_deviation_m = 1639m`
- `gd.trajectory_deviation_m = 1688m`
- **差 49m，protag-only 也几乎一样**

paired mirror 设计要 hp/gd 在 trajectory 上方向相反——实际两者都"被推到远地"
(因为 stub LLM 强制改 plan 走向 target/distraction，无论哪边都偏离 baseline)。

### B4 · pf encounter 几乎不变

phone_friction 设计："减少手机吸力 → 推 agent 出门 → encounter 上升"。

scripted_plan 修完后 agent 本来就高频访问 POI (cafe / park / restaurant)。
pf 额外推送的"去 community" 不再是"打破"——是 redundant noise。

D1' 14-day 数据看到 pf 在 day 9-13 才出现 spike — 但 6 天 intervention 期可能不够。

---

## 📐 C 类 · 方法学 confound

### C1 · paired mirror 设计本身有问题

- hp、gd、pf **都** 额外推送 → 都增加 phone activity
- baseline 完全无推送 → 控制变量是"有无推送"而非"推送方向"
- 真正想测"hyperlocal vs distant"应该控制"推送量"——目前是
  "推 18 次 local vs 推 50 次 global"，量和方向同时变

### C2 · 14 天 × 6 天 intervention 太短

现实 "21-day habit formation" 经验法。D1' 数据 pf encounter spike 在 day 9-13。
6 天 intervention 不一定捕到 stable effect。

### C3 · 5-min tick 颗粒度风险

- agent 进 cafe → 1 tick → encounter detected
- 现实"在 cafe 坐 30min 跟邻居聊天" → 需要 6 tick 连续 co-presence + dialogue
- 当前 encounter 高估"擦肩而过"、低估"有意义社交"

### C4 · 1000 agent vs 100 agent scaling 未验证

所有 audit / test / smoke 在 100 agent。1000 agent 表现可能非线性：
- D1' 100 agent × 14 day = 513 weak_tie
- 按 50 agent × 1 day = 8 weak_tie 线性推 → 1000 × 14 应 ~2200
- 实际 513 → **非线性收敛/饱和**
- weak_tie 形成阈值未在 spec 明确，scale 转换不可预测

---

## 🚧 D 类 · 数据 / 校准

### D1 · ABS Census 是 COVID 锁城期间快照

`work_mode_distribution.remote = 0.55` 是 2021-08 ABS Census（Sydney Delta lockdown 期间）。
Lane Cove 稳态 remote ~18%。当前 sim 跑出来的"通勤 vs remote 比" 严重偏 remote。
但 LANE_COVE_PROFILE 直接用 ABS 值（spec 已 disclose 这是 publishable 数据流的一部分）。

### D2 · dwell_ticks 不分 agent

`location_dwell_ticks` 是 location → total ticks 聚合，不分 agent。
- 无法答"agent X 在 cafe 待多久"
- 限制了 per-agent realism analysis & individual-level claims

### D3 · weak_tie 形成阈值未公开

spec 提到 `WEAK_TIE_THRESHOLD` 但没说"经多少 co-presence tick 算一次 weak tie"。
跨 variant 比较时不知 weak_tie 数字差异是真社交差异还是阈值噪音。

---

## 🔬 E 类 · stub vs real LLM 路径分裂

### E1 · 整个 stub 路径行为 ≠ real LLM 路径

- **stub**: variant push → 强制 plan_changed → agent 走向 target
- **real**: LLM 真"看到"推送 → 可能拒绝 / partial accept
- D2 publishable 用 DeepSeek thinking-off + stub planner —— 即使 use_aitown=True，
  也只是 protag (10/100) 走 LLM 路径

**问题**：stub 路径产生的 hp/gd/pf 效应**不能预测**真 LLM 路径下的真实 user response。
publishable D2 结果只反映 stub 决策树，不能 generalize 到"真实用户对推送的反应"。

### E2 · protag 只占 10% (1000 agent → 10 Sonnet)

90% scripted agent 不会因 push 改变行为（除非 stub plan_changed）。
1000 agent 跑出来的"集体效应" = 10% LLM agent + 90% scripted agent。
publishable 应至少 50% LLM 才能让 emergent 社会效应被 LLM 推理 surface。

---

## 📊 F 类 · 推送语义不"hyperlocal"

### F1 · push 内容不个体化

`hyperlocal_push` 推送 "今天 cafe_main 有活动"，**所有** target agent 收到同样字符串。
thesis 中"超在地" 隐含"个性化匹配 (针对 agent 兴趣 / archetype)"。
当前实现是 bullhorn 广播 ≠ thesis 概念。

### F2 · 1000 米半径无 geographic filter 验证

`hyperlocal_radius=1000` 字段存在，但没看到 attention service 真"按距离过滤"。
**需查证**：agent 离 push 源 > 1000m 时是否真不收到推送？

---

## 🏗️ G 类 · 架构 / 工程

### G1 · `_pick_connected_destinations` 仍有 deprecation 调用方

audit / demo tools 仍走旧 outdoor-only 单池路径（emit warning 但产生不符合
thesis 的数据）：`run_stereotype_audit.py` / `smoke_experiment_demo.py`。

### G2 · `lanecove_atlas.json` cache 不带版本

`data/lanecove_atlas.json` 是 cartography importer 的 cache，但没 hash/version
metadata。我们改完 importer 后**手动 rm + rerun**——如果忘了，旧 cache 会 silently
provide 旧 building_type 数据。

需要 atlas cache 加 schema_version + importer_hash，加载时验证。

### G3 · 测试覆盖不到 multi-day variant interaction

`test_variant_smoke_e2e.py` 跑 3 day × 1 seed × 20 agent，但 phase 配置硬编 1,1,1。
真正 publishable 是 4,6,4 (14 day) — phase 边界 day 4/10 的过渡行为没 e2e test。

---

## 🤔 H 类 · 可解释性 / 报告诚实度

### H1 · variant 效应即使有，可能 attribution 错位

如果 D2 跑出 "pf 让 encounter +11%"，那 +11% 来自：
- (a) pf 真减少屏幕 (thesis 想说的)
- (b) pf 多推 50 个 community notification → 50 个 plan_changed → 50 次 forced 移动
- (c) scripted_plan 已让 90% agent 频繁访问 cafe → pf 推 community 是 noise

无法在结果中区分这三个 source —— publishable paper 需要 ablation：
"如果 pf 不推任何东西只改 attention model，效应是？"

### H2 · 报告里"附近"的 working definition 未定

thesis 主词"附近性盲区"（nearby blindness）—— "附近"是：
- 物理 1km 内？(hyperlocal_radius)
- 同 Lane Cove SAL? (suburb)
- 同 building? (cafe)
- walking distance? (300m / 5min walk)

代码里 1000m，但 thesis 论文不能既说"我们测了 1km 半径"又说"附近的咖啡馆邻居"——
1km 半径里 0 个 cafe 在某些 home 周边是真的。

---

## 优先级矩阵 · 建议

### 必修才能跑 publishable

| 问题 | 修复工作量 |
|---|---|
| **A1** attention model 不存在 | 大（新 capability：phone_attention_state） |
| **B3** scripted agent 把 variant 效应稀释 | 中（提高 protag 比例 + 改 scripted_plan 让 push 也影响 scripted） |
| **B4** paired mirror traj_dev 不发散 | 小（spec 实测阈值放宽 或 重设 paired control） |
| **E1** stub vs real LLM 路径分裂 | 中（publishable 必须 ≥ 50% Sonnet OR 用 real LLM 全栈） |

### 可在 publishable 后 disclose

| 问题 | 应对 |
|---|---|
| **C1** paired mirror confound | 在 §5 Limitations 段明确 |
| **C2** 6 天 intervention 短 | 在 §5 列限制；future work 用 21 天 |
| **C3** 5 min tick 粗 | 在 §5 列限制 |
| **C4** 100 vs 1000 scale 未验 | 跑 1000-agent sensitivity smoke 再说 |
| **D1** COVID census | 已 disclose (LANE_COVE_PROFILE docstring) |
| **F1** push 不个性化 | 在 §5 说"first-order intervention" |
| **G2** atlas cache 无版本 | 加 schema_version 字段 |
| **H1** 效应 attribution | 在 publishable 报告里加 ablation 表 |

### 项目方向决定

**核心问题：现在 thesis publishable 跑出来很可能是"variant 效应 < 噪音"。**

三条路：

1. **修 attention model + 提高 protag 比例 + 重跑 publishable**
   - 工作量 ~2 周
   - 风险：效应可能仍 weak（thesis hypothesis 可能本就 marginal）
   - 收益：能验证 thesis 主张

2. **承认实测限制，重新框 thesis**
   - 把 thesis 从"thesis 验证"改成"研究装置 + 方法学贡献"
   - 报告焦点："本系统能模拟 X，未来研究人员可用 Y 工具"
   - 不依赖 publishable 数据出 strong claim
   - 工作量 ~3 天（重写论文 framing）
   - 收益：诚实可发布

3. **本 publishable 跑 pre-registered exploratory** + future work
   - 跑 D2，结果当 pilot
   - paper 写"这是 1 次 pilot，effect size 估计在 [a, b]，未来 N=1000 confirmatory"
   - 工作量 ~1 周（修 attention model + 跑 + 写 framing）

我倾向 **2 or 3**，因为 1 假设效应存在（数据不支持）。需要你定夺。

---

## 相关文档

- 11 维 realism audit: `docs/audit/2026-05-12-realism-audit.md`
- home_location bug 修复: `openspec/changes/fix-population-uses-typed-locations/`
- realism systemic fix: `openspec/changes/fix-realism-systemic-gaps/`
- canonical thesis: `docs/agent_system/00-thesis.md`
- 局限与伦理: `docs/limitations-ethics.md`
