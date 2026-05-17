# Backlog — 已识别但暂不开发的需求

记录用户确认过"需要做、但暂时不进开发流程"的事项。每条带上下文 + 优先级
+ 触发条件（什么时候应该把它从 backlog 移出来变成 OpenSpec proposal）。

---

## 1. Push 内容个体化（GD / PF）

**记录时间**：2026-05-17

**背景**：HP (HyperlocalPush) 已经过 `push-content-individualization` capability
精细化——5 个 PushTemplate × 5 audience variant + PushPersonalizer 路径。但
另外两个干预 variant 没走个体化：

- **GD (GlobalDistraction)**：10 条 generic global news headlines，所有 target
  收到同一条 broadcast。14 天 × 5 推送/天 会有大量重复。
- **PF (PhoneFriction)**：现已扩到 19 条 nudge templates（带 Lane Cove 地标 +
  时段 + 风格变化），但仍是 broadcast——所有 agent 同一时刻收到同一条。

**理想方向**：让 GD / PF 也走 PushPersonalizer，用 setup_content_cache 里的
`identity_text` + `life_history` 个体化 push：
- 对 35 岁有娃的设计师，PF nudge 提"孩子在 Canopy Park 等你"
- 对 65 岁退休志愿者，PF nudge 提"Plaza 长椅有人在等下棋"
- GD 也可按职业 / 兴趣个体化（财经 vs 娱乐 vs 体育 ……）

**优先级**：低。当前 D2 (β=10 publishable) 用 broadcast 路径已能给出 H_info /
H_pull 方向证据；个体化是"如果方向对，下一步加深效果"的扩展。

**触发条件**：D2 跑完，contest.json 显示 H_pull / H_info 方向有效但 effect
size 偏弱时考虑——届时 push 内容个体化是首要 amplification lever。

**估工**：1.5-2 hr 代码 + 0.5 hr 测试。

**Owner**：未指定。

---
