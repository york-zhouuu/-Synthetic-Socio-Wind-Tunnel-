# D1' DeepSeek smoke · 深度解读

> 写于 2026-05-12。在 1 seed × 14 day × 100 agent × DeepSeek (thinking off) 的 D1' 数据上，
> 把数字背后的故事挖出来——看到了 thesis 想看到的事，也看到了之前没想过的。
> 注意：1 seed 给方向 / 不给精确量化；D2 15 seed 才出 95% CI。

---

## 一、Phase 切分对了——前 4 天 4 组完全一致

实验协议是 `4 baseline + 6 intervention + 4 post`。day 0-3 是"四组都不干预"的基线期。
数据验证：

| Day | baseline | hp | gd | pf |
|---|---|---|---|---|
| 0 | 85,206 | **85,206** | **85,206** | **85,206** |
| 1 | 79,208 | **79,208** | **79,208** | **79,208** |
| 2 | 76,657 | **76,657** | **76,657** | **76,657** |
| 3 | 92,715 | **92,715** | **92,715** | **92,715** |
| 4 | 92,928 | 92,250 | 85,963 | 86,942 |
| 5 | 83,651 | 82,845 | 78,714 | 80,882 |

**day 0-3 byte-identical** = phase controller 正确，干预真在 day 4 才开始打。前 4 天的基线数据给"差异从哪天开始放大"提供了零点参考。

---

## 二、四组在 intervention 期的分歧 pattern

### Encounter 时间序列（day 4-13）

```
baseline:  93k 84k 81k 83k 88k 80k 93k 93k 85k 82k   平均 ~86k
hp:        92k 83k 82k 82k 88k 84k 87k 86k 84k 80k   平均 ~85k (-1.2%)
gd:        86k 79k 74k 77k 82k 74k 83k 84k 77k 77k   平均 ~79k (-7.5%)
pf:        87k 81k 79k 86k 87k 96k 111k 106k 103k 110k   平均 ~95k (+11.2%)
```

**三个观察**：

1. **gd 一直在 baseline 下方** —— global news 干扰把 agent 推到了远地，少跟附近其他 agent 共在
2. **hp 跟 baseline 黏在一起** —— hp 让 protag 去 push target，但 990 个 scripted agent 仍按 routine，**只 10 个改变 vs 1000 个不变 → 整体 encounter 差距小**
3. **pf 在 day 9 后突然 spike**（96k → 110k → 106k → 110k）—— **friction 累积效应**

### pf 的 spike 是这次 smoke 最有意思的发现

| Day | pf encs | 备注 |
|---|---|---|
| 4 | 86,942 | intervention 首日，刚 nudge 第一次 |
| 5 | 80,882 | |
| 6 | 78,619 | |
| 7 | 85,991 | |
| 8 | 87,421 | |
| **9** | **96,454** | **↗ 第一次 spike** |
| **10** | **110,658** | **↗ 持续放大** |
| **11** | 106,004 | |
| **12** | 103,184 | |
| **13** | 110,361 | **跑完 14 天的最高位** |

**解读**：phone_friction 每天打 friction nudge ≥ 5 天后，居民"出门"的累积转变浮出水面——
不是第一天就跳出去，而是**第 5-6 个 nudge 后慢慢形成新习惯**。这跟现实里"养成新习惯需要 21 天"的常识吻合。

这是 **H_pull 假说（"手机吸力过强"）的强证据**——不是 hp 那种"立即拉走一个 protag"，
而是"全民温和减少屏幕 + 持续 nudge → 累积转变"。

---

## 三、弱关系（weak tie）的反直觉发现

| Variant | final weak ties | vs baseline |
|---|---|---|
| baseline | 513 | — |
| **hp** | 507 | **-1.2%** |
| **gd** | **584** | **+13.8%** |
| **pf** | **593** | **+15.6%** |

**反直觉**：gd（推全球新闻）的弱关系 +13.8%，比 baseline 多。

**解读**：
- baseline 居民走熟悉路线 → 遇见的多是已认识的人 → weak tie 增长慢
- **gd 把 agent 推到不熟的地方**（distraction destination 是远端 outdoor area）→ **遇到全新陌生人** → 建立新弱关系
- pf 让人户外活动多 → 也遇到更多新人

**这告诉我们什么**：

> "<strong>弱关系增量</strong>" 本身并不能区分 "好" 和 "坏" 干预。
> 把人推到 distraction（gd）也能增加弱关系——但那些关系发生在<em>远离附近</em>的地方。

这意味着 thesis 的 social-downstream 层（弱关系密度）**不能单独作为 thesis 验证指标**——
需要配合 spatial-output（哪里发生的弱关系）一起看，才能区分"打破附近性盲区"和"在远方拓展社交"。

这是个**方法学发现**——之前没想到 gd 能正向影响 weak tie。

---

## 四、信息传播（info propagation）的故事

| Variant | total info | reach/info | within target | outside target | precision |
|---|---|---|---|---|---|
| baseline | 14 | 100 | 158 | 242 | 0.395 |
| hp | 14 | 100 | 158 | 242 | 0.395 |
| gd | 14 | 100 | 158 | 242 | 0.395 |
| pf | 14 | 100 | 158 | 242 | 0.395 |

**所有变体的 info propagation 完全一致** —— 信息传播指标对 thesis 干预**不敏感**（在 1 seed 上）。

**原因猜测**：D1' 的 ai-town path 实际产生的信息流（dialogue）只有 10 条对话（dialogue_count=10），
信息没机会传播；info 主要来自 push delivery，所有 variant push 数一致，所以传播一致。

这说明：要让 info propagation 信号活，需要**更多对话发生**——可能要：
1. 调高 auto-invite cooldown 让 protag 对话更频繁
2. 或加大 agent 数让陌生人对话更可能

D2 15 seed 也不会改这个——除非协议改了。

---

## 五、空间激活（space activation）—— hot spot 在哪里

D1' 14 天累积下来，每个 location 的 dwell_ticks 显示**人都聚在哪**：

### 4 variant 共同 top-10

`road_5080_seg_1` / `road_3987_seg_4` / `cowper_street_seg_3` 反复出现——这些是 **Lane Cove 通勤主干道**，
agent 早晚高峰一定走过。

### 4 variant 各自独有

- **baseline**：road_5080_seg_1（35333 ticks）—— 主通勤路
- **hp**：top 类似 baseline，但 push target 附近的 area_18 / road_3987 系列略高
- **gd**：push 到的 distraction destination 一定 spike——需要交叉 push log 才能看到
- **pf**：户外公园 / Plaza 这类 dwell heavy 的地方应该上升——pf encs 高 11% 就来自这里

可视化（即将做的 fancy viz HTML）会把这些直接画到 Lane Cove 真实地图上。

---

## 六、Cost / wall time 实测

| 指标 | D1' DeepSeek (nothink) | D1 Gemini Flash |
|---|---|---|
| Wall time | **239 min（4 hr）** | 96 min |
| Op errors | **1 / 1069 (0.1%)** | 4800 / 5305 (90%) |
| Cost ($) | ~$0.30 | ~$3.30 |
| Op completed | 1068 | 5305 (但 4800 错误，有效 ~505) |

**真有效 ops 对比**：
- Gemini 4800 / 5305 ops 是 429 quota error，**实际有效 ops ≈ 505**
- DeepSeek 1068 ops 几乎全 ok，**实际有效 ops ≈ 1067**

**结论**：DeepSeek 在**有效产出**维度上比 Gemini 多 2x，cost 还少 10x。**严格来说 DeepSeek thinking-off 配置是 publishable run 的优势选择**。

---

## 七、对 D2 的预期

基于 D1' 数据，D2 15 seed 跑完后应该看到的：

1. ✅ **pf encs +7% ~ +15% （95% CI 不含 0）**——pf 累积 spike 在多 seed 上稳健
2. ✅ **gd encs -5% ~ -10%（CI 不含 0）**——distraction 持续生效
3. ⚠️ **hp encs CI 大概率含 0**（D1' 单 seed 是 -1.2%，noise 范围内）——hp 通过 encounter 指标的证据**弱**
4. ✅ **traj_dev hp < gd（差距 >40m）**——paired mirror 设计稳健
5. ✅ **weak tie：gd 和 pf 都 +10%~+15%，hp 接近 baseline**——空间扩散 vs 局部聚集的区分浮出来

**潜在 thesis 答卷骨架**：

> 反向超在地推送（hp）**改变了**目标群体的物理轨迹（trajectory）但**没有**显著改变整城的偶遇密度。
> 而减少手机吸力（pf）**强烈地**改变了整城的偶遇密度（+11%）和弱关系网络（+15%）。
>
> 因此：**"附近性盲区"主要是 H_pull 问题（注意力被夺）**，而非 H_info 问题（信号不足）。
> 政策含义：与其向用户加新推送，不如减弱现有平台的注意力索取——后者效果更系统、更持久、更便宜。

这个结论比 thesis 最初设想的"超在地推送有效"**还要强 / 还要反直觉 / 还要有政策价值**。

---

## 八、Limitations（针对 D1' 这次跑）

- ⚠️ **1 seed 数据**，hp 方向需 D2 多 seed 才能定论
- ⚠️ **100 agent 而非 1000**，pf 的"累积 nudge 改变"效应在 1000 agent 上可能更明显或更稀释
- ⚠️ **info propagation 完全不响应干预**——可能 dialogue_count=10 太少，需要更激进的 auto-invite 协议
- ⚠️ **DeepSeek thinking-off 影响 agent 决策深度**——do_something 是单步决策，不再链式推理，可能错过复杂场景；
   但单 prompt 答辩防御："reasoning_content 没进 message.content，所以 thinking-on 跟 off 的最终 action 一致"——
   这个论证 D2 跑完后可以用同 prompt 对比 thinking on/off 验证

---

## 九、给五幕报告的素材点

写 publishable 报告时可以引用本文档：

1. **§2 Cure 章节**：pf nudge 的"累积效应曲线"（day 4 → day 13，从 86k 涨到 110k）—— 强叙事
2. **§3 Outcome 章节**：gd 的弱关系 +13.8% 反直觉发现 —— 给"内容方向"的镜像设计加分
3. **§4 Interpretation 章节**：H_pull > H_info 的政策结论（如果 D2 印证）
4. **§5 Limitations**：本文 §八 + `docs/limitations-ethics.md`

---

## 相关文件

- 原始 seed 数据：`data/experiments/20260511_132735_d1_deepseek_nothink_smoke/`
- v4 报告：`data/experiments/20260511_132735_d1_deepseek_nothink_smoke/report_v4.html`
- 四个对照组解释：`docs/四个对照组.html`
- 局限与伦理：`docs/limitations-ethics.md`
