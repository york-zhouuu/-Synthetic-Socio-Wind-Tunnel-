# 模型选型 · 给 publishable run 用 ——— 决策文档

> 写于 2026-05-10。目的：D2 publishable run 之前，决定每个 LLM tier 用哪家模型。
> 当前问题：Gemini Flash 免费 quota 在 D1 (1 seed × 14 day × 100 agent) 中后段已被打满，
> D2 比 D1 大 ~300 倍，需要更高 QPS 或更便宜的模型。

---

## 一、项目背景（速览）

**项目**：Synthetic Socio Wind Tunnel · 合成社会风洞
**研究问题**：手机注意力如何在高密度城市制造"附近性盲区"？反向超在地推送能否打破？
**实验对象**：1000 个 AI 智能体，住在悉尼真实街区 **Lane Cove**
**实验协议**：14 天 × 4 对照变体（baseline / hyperlocal_push / global_distraction / phone_friction）× 30 个随机种子
**输出**：encounter density / trajectory 偏离 / 空间激活度 三大主信号

完整 thesis 见 `docs/agent_system/00-thesis.md`，公众版在 `docs/项目产出物.html`。

---

## 二、LLM 在系统里干什么（5 种 op kind × 3 个 tier）

`agent-stack-aitown-port` 把 convex/ai-town 的 agent 决策机制移植了过来。每 sim tick，10 个 protagonist agent 会触发以下 5 种 LLM 操作：

| op kind | 频率 | tier | 干啥 |
|---|---|---|---|
| `do_something` | ~1-3 / protag / tick | **sonnet** | 决定下一步做什么（活动 / 走 / 邀请对话 / 静观） |
| `generate_message` | ~5-8 messages / dialogue | **sonnet** | 生成对话内容 |
| `remember_conversation` | 1 / dialogue end | **haiku** | 把刚才的对话总结成 memory event |
| `reflect` | 1 / 每 ~50 个 importance event | **haiku** | 把多个 memory 抽象成 insight |
| `score_importance` | 1 / 每条 memory event | **nano** | 给 memory 打 0-9 重要性分（单 int） |

**Tier 用意**：
- **nano**：最便宜、最快、最短输出（"5"）。打分用，不需要推理深度。
- **haiku**：总结 / 反思类。中等长度（200-500 tokens）。
- **sonnet**：决策 + 对话生成。需要推理 + 个性化。最贵但占比最低。

`tools/tier_llm_factory.py` 已经把这三层抽象做好了——**可以每 tier 独立换模型**，不用改 agent 代码。

---

## 三、当前实测瓶颈（D1 数据）

D1 = 1 seed × 14 day × 100 agent × 4 variant，全程用 Gemini Flash（gemini-3-flash-preview）跑：

| 指标 | 实测 |
|---|---|
| **Wall time** | 96 分钟（1.6 hr） |
| **Total LLM ops** | 5305 completed + **4800 errors** |
| **Error rate** | **90% (4800 / 5305)** |
| **Error type** | 100% 是 `429 RESOURCE_EXHAUSTED` |
| **Cost actual** | $0.18 (baseline) / $0.18 (hp) / $0.18 (gd) / $2.76 (pf) = **$3.30 total** |
| **Throughput** | ~33 ops/min（被 quota 卡死的速率） |

**结论**：
- Gemini Flash **免费档**承受不了 D1 规模。
- D2 (30 seed × 14 day × **1000 agent**) 是 D1 的 **300 倍**——按当前 quota 跑，95-99% ai-town 调用会被拒，跑出来的数据 ai-town 路径的反思/对话部分会几乎为空。
- scripted_plan 路径不依赖 LLM，仍能跑出 spatial-output 指标 — 但 thesis 报告需要的"agent 个体故事"那一层就缺。

---

## 四、候选模型横评（三家主流 + 三 tier × 三家）

### 4.1 价格 + QPS 对比表（2026-05 价格，Tier 1 paid quota）

> 价格单位：$ / 1M tokens (input / output)
> QPS = 每分钟请求数（RPM）；具体随 paid tier level 变化

#### nano tier（importance scoring，单 int）

| 模型 | input $ | output $ | 免费 RPM | Paid Tier 1 RPM |
|---|---|---|---|---|
| **gemini-3-flash** | $0.10 | $0.40 | 15 | 1000 |
| **claude-haiku-4.5** | $0.80 | $4.00 | — | 50 |
| **gpt-4.1-nano** | $0.05 | $0.20 | — | 500 |
| **deepseek-v3** | $0.14 | $0.28 | — | 60 |

**赢家：gpt-4.1-nano** ——单 token 最便宜（$0.05/$0.20）+ 无免费档但 Tier 1 RPM 已 500。

#### haiku tier（summary / reflection，~200-500 tokens 输出）

| 模型 | input $ | output $ | 免费 RPM | Paid Tier 1 RPM |
|---|---|---|---|---|
| **gemini-3-flash** | $0.10 | $0.40 | 15 | 1000 |
| **claude-haiku-4.5** | $0.80 | $4.00 | — | 50 |
| **gpt-4.1-mini** | $0.15 | $0.60 | — | 500 |
| **deepseek-v3** | $0.14 | $0.28 | — | 60 |

**赢家：gemini-3-flash 升 paid**——价格相近 / RPM 1000 是其它的 2-20 倍。
**备选：deepseek-v3** 更便宜的 output（$0.28 vs $0.40）但 RPM 低。

#### sonnet tier（decision / dialogue，~1024 tokens 输出，需要推理）

| 模型 | input $ | output $ | 免费 RPM | Paid Tier 1 RPM |
|---|---|---|---|---|
| **gemini-3-pro** | $1.25 | $5.00 | 2 | 60 |
| **claude-sonnet-4.6** | $3.00 | $15.00 | — | 50 |
| **gpt-4.1** | $2.00 | $8.00 | — | 500 |
| **gpt-4.1-mini** | $0.15 | $0.60 | — | 500 |
| **deepseek-r1** | $0.55 | $2.19 | — | 30 |

**注意：sonnet tier 干的事是 do_something + generate_message，是 quality 最敏感的 tier。换便宜模型可能让 dialogue 质量下降到答辩防御不住。**

**赢家：gpt-4.1-mini** —— 输出 $0.60，输入 $0.15，500 RPM，但**质量比 Sonnet 4.6 / GPT-4.1 显著低**。
**保险派：claude-sonnet-4.6** —— 最贵但质量最高，能撑住答辩。
**激进派：gpt-4.1-mini** —— 4-5x 便宜，看 D2 smoke 后能不能用。

---

## 五、三种推荐方案

### 方案 A · 全 Gemini Flash + 升 paid quota（最简单）

**改什么**：去 https://aistudio.google.com/app/apikey 给项目绑定信用卡，paid Tier 1 自动开（1000 RPM）。代码不动。

**D2 估算**（30 seed × 14 day × 1000 agent）：
- LLM ops: ~1.5M
- 平均 input ~ 800 tokens / output ~ 400 tokens
- Cost ≈ 1.5M × (0.10×0.0008 + 0.40×0.0004) = **~$360**
- Wall time: 30 seed 串行约 30 × 1.6hr × 10 = **~480 hr** （单 seed 1.6hr 但 100 → 1000 agent ×10 倍 LLM 调用）
- 或并行 4 seed: ~120 hr

**问题**：480 hr 是 20 天。即便并行也太久。**1000 agent 是瓶颈**。

### 方案 B · 三 tier 混搭 + paid quota（平衡）

**改什么**：
- nano tier: **gpt-4.1-nano**（$0.05/$0.20，500 RPM）
- haiku tier: **gemini-3-flash paid**（$0.10/$0.40，1000 RPM）
- sonnet tier: **claude-sonnet-4.6 paid**（$3/$15，但走 Tier 2/3 升到 1000+ RPM）

**实施**：`tier_llm_factory.py::build_tier_clients` 已经支持每 tier 单独 provider。改一下 `aitown_provider` 参数让它接收 dict 而不是单值。

**D2 估算**：
- nano: ~500K ops × $0.05 = **$25**
- haiku: ~500K ops × $0.30 = **$150**
- sonnet: ~500K ops × $5 = **$2500**
- Total: **~$2700**

**问题**：sonnet tier 拉高 cost。

### 方案 C（推荐）· **D2 改用 100 agent + Gemini Flash paid**

**改什么**：
- D2 命令从 `--agents 1000` 改成 `--agents 100`
- 升 Gemini paid（1000 RPM）
- tier 全用 gemini-flash（不混搭）
- 加一个简单 rate limiter 防止 burst（Gemini paid 也有突发限制）

**理由**：
- 100 agent × 30 seed = 3000 agent-runs，统计置信度 D1 已展示
- 1000 agent 给 thesis 的额外信息很少（30 seed 才是 95% CI 的来源）
- 1000 agent 真实 publish 价值低，cost 高 10x
- Lane Cove 真实人口 SAL12275 也才 ~14000，1000 是合理 sub-sample；100 也是合理（更小的 cohort 模拟）

**D2 估算**：
- LLM ops: ~150K（D1 × 30）
- Cost ≈ 150K × $0.0006 = **~$90**
- Wall time: 30 seed 顺序 ~ 50 hr，并行 4 路 ~ **12-15 hr**

---

## 六、最终建议

```
方案 C（D2 改 100 agent + Gemini Flash paid + rate limiter）
   ├─ Cost: ~$90
   ├─ Wall: 12-15 hr（一晚跑完）
   ├─ Quality: D1 已证 thesis 信号方向正确
   └─ 答辩防御：1000 agent 的"大数定律"理由薄弱，30 seed 才是真置信度
```

**操作步骤**：
1. 你去 https://aistudio.google.com/app/apikey 绑定 Google Cloud paid（5 分钟）
2. 我写一个 `_AsyncRateLimiter` 包到 `_GeminiTierClient.generate`（半天）
3. Launch D2 with `--agents 100 --seeds 30 --num-days 14`
4. 第二天醒来跑 `check_publishable_integrity.py` + `build_evidence_report_v4.py`

如果你倾向"thesis 答辩需要 1000 agent 的肌肉"，方案 B 是 $2700 一晚跑完；方案 A 是 $360 但要 4-20 天。

---

## 七、附：现有代码已支持什么

`tools/tier_llm_factory.py::build_tier_clients(provider="gemini" | "anthropic" | "stub", ...)`：
- ✅ 支持单一 provider 跑全 3 tier
- ⚠️ 不支持每 tier 独立 provider（方案 B 需要小改造）
- ✅ 每 tier 已有独立 model name + max_tokens 配置
- ✅ Gemini path 用 `client.aio` 异步（asyncio.gather 真并行 ~5x speedup）
- ✅ Token cost tracking 已修（B6 fix；只对 Gemini 生效，Anthropic/OpenAI 暂未）

要混搭模型方案 B，需要：
- `_AnthropicTierClient` 加 `_last_usage` 字段（与 Gemini 对齐）
- 添加 `_OpenAITierClient` 类（参考 `_GeminiTierClient`）
- `build_tier_clients(providers={"sonnet": "anthropic", "haiku": "gemini", "nano": "openai"})` 接受 dict

工作量：~1 天写 + ~半天测试。

---

## 八、决策点（你回我）

1. **方案 A / B / C 选哪个？**
2. **D2 100 agent 还是 1000 agent？**
3. **要不要我写 rate limiter？**（半天工作）
4. **要不要我加 OpenAI 支持？**（1 天工作；只在选方案 B 时需要）
