## Context

thesis 核心机制是"phone notifications drain world-attention → 同位置不形成
社交关系"，但 28 维拟真 audit + 50-agent stub smoke 暴露：
- encounter = pure geographic colocation
- phone_feed_proxy = delivered_notifications / cap，不是 agent 注意力状态

修这条链路是 thesis 机制能 surface 的前提。

## Goals / Non-Goals

**Goals**:

1. 每个 agent 有 dynamic `phone_attention ∈ [0, 1.5]` 状态可观测可写入
2. notification 增 attention，时间衰减 attention
3. encounter detection 通过 noticing gate ——两 agent 都不刷手机时高概率 noticed
4. weak_tie 形成 only from noticed encounters
5. 实测 50-agent × 1-day stub run：noticed_rate(pf) > noticed_rate(baseline) > noticed_rate(gd)

**Non-Goals**:

- 不实现 spatial noticing bonus（hp 推 cafe → cafe 处 noticing +）
- 不改 perception pipeline
- 不引入 LLM 决定 noticing（pure deterministic）

## Decisions

### D1 · phone_attention 数值范围与动力学

```python
PHONE_ATTENTION_MIN = 0.0
PHONE_ATTENTION_MAX = 1.5  # 可短暂 >1 (overload)
PHONE_ATTENTION_DECAY_PER_TICK = 0.85  # half-life ~ 4 tick
NOTIFICATION_BASE_DELTA = 0.10  # 一个 medium-urgency push
NOTIFICATION_RESPONSIVENESS_GAIN = 2.0  # responsiveness=1 → ×2
```

baseline (no notifications): `phone_attention` 衰减至 floor `baseline_screen_share`:

```python
def baseline_screen_share(digital: DigitalProfile) -> float:
    """daily_screen_hours / 16h waking → [0, 1] ambient screen presence"""
    return min(1.0, digital.daily_screen_hours / 16.0)
```

每 tick：

```python
attention[t+1] = max(baseline, attention[t] * DECAY)
                 + sum(notification.delta for n in arrivals)
```

Δ formula:

```python
delta = NOTIFICATION_BASE_DELTA \
        × urgency_factor \
        × (1 + (responsiveness - 0.5) × NOTIFICATION_RESPONSIVENESS_GAIN)
        × (0.5 + openness)  # extraverts respond more
```

### D2 · noticing probability

```python
BASE_NOTICING_RATE = 0.3  # ideal-condition noticing rate

def noticing_prob(a: float, b: float) -> float:
    """两 agent 都不刷手机时 ~0.3；任一被手机占满时 ~0"""
    max_attn = max(a, b)
    return max(0.0, 1.0 - max_attn) * BASE_NOTICING_RATE
```

`max(a, b)` 而非 `mean(a, b)` 是因为社交是双向必要的——任一方被手机占满就阻断 noticing。

### D3 · deterministic gating

为复现性，gate decision SHALL 用 `(seed, day, tick, sorted(a, b))` hash 生成 rng：

```python
def noticed_pair(a_attn, b_attn, *, seed, day, tick, pair) -> bool:
    h = hash((seed, day, tick, pair[0], pair[1]))
    rng = random.Random(h)
    return rng.random() < noticing_prob(a_attn, b_attn)
```

### D4 · backward compat

- `record_encounter(a, b, tick, day_index)` 保留旧名作 `record_physical_encounter`
  的别名，**不增 strength**（行为变化—— 旧 caller 期待增 strength 的逻辑被破坏）
- 旧 metric `encounter_count_total` 保留语义不变（地理 colocation）
- 新 metric `noticed_encounter_count_total` 是 weak_tie 来源

**破坏式 vs 兼容式选择**：选**破坏式** —— 旧 record_encounter 不再增 strength。
理由：保留旧行为意味着 thesis 修复没生效。把破坏面缩到 `memory.process_tick`
一处（旁路 record_encounter / record_noticed_encounter 二选一）。

### D5 · per-agent phone_attention 存哪

**选**：放进 `AttentionService` —— 已有的 attention capability，自然延伸。
不放 Ledger（Ledger 是物理状态 / phone_attention 是心理状态，不同 concern）。

API:

```python
class AttentionService:
    def get_phone_attention(self, agent_id: str) -> float: ...
    def set_phone_attention_baseline(self, agent_id: str, baseline: float) -> None: ...
    def tick_decay_all(self) -> None: ...  # called per tick
```

### D6 · 谁调 tick_decay_all

放 `memory.process_tick` 开头（已经迭代所有 agent + 已经有 tick context）。
不放 Orchestrator 因为 attention 是 memory-layer concern。

## Risks / Trade-offs

- **[BASE_NOTICING_RATE = 0.3 vs encounter regression]** 旧 D1' 100 agent × 14 day
  513 weak_tie。新机制 gate 30% → 大致 ~150 noticed_weak_tie。如果效应来源
  错位（旧 weak_tie 包含路径效应），新数据是 honest baseline 但 publishable
  比较时旧 baseline 不可用
- **[determinism 与 RNG 序列]** 新 noticing gate 引入额外 rng call → 旧 test
  byte-equal 保证破坏。Mitigation: 用 hash-based RNG 不消耗 global state
- **[balance tuning]** 三个 magic number (DECAY, BASE_DELTA, BASE_NOTICING_RATE)
  影响 effect size，未基于真实数据校准。**只能 disclose 为 first-order**
- **[stub vs LLM 路径下行为差异]** stub variant 仍 force 走 plan_changed；
  LLM 路径 attention 高时 agent 可能拒绝 push —— 当前 design 不处理后者

## Migration Plan

1. attention/noticing.py 新增 NoticingGate + 常量
2. attention/service.py 加 per-agent phone_attention dict + decay + delta accumulate
3. social_graph/service.py 拆 record_physical / record_noticed
4. memory/service.py 在 process_tick 前调 noticing_gate
5. metrics 加新字段
6. tests + audit + 1-day smoke

## Open Questions

- BASE_NOTICING_RATE = 0.3 是合理估计还是需要 calibration？目前是占位；
  publishable 报告 limitations 应明确"未基于实证数据调校"
- 是否要 spatial bonus (hp push @ cafe → cafe 处 noticing +) ? **本 change deferred**
- 推送内容个性化是否在本 change 范围？**不在** — 单独 change
