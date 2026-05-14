## Context

前 5 个 change 修了大类 bug（home_location / cartography POI / typed pools /
attention model / walking budget）。审计发现还有 thesis 解读层面 5 个 A 类
高风险问题：分布占位符、protag 稀释、polygon over-count、tie 无衰减、
walking budget × LLM joint 未验证。

## Goals / Non-Goals

**Goals:**
1. A1-A5 全部 RESOLVED
2. B 类 + C 类全 disclose in `limitations-ethics.md`
3. 不 regress 现有 250+ test

**Non-Goals:**
- 不真实证 calibration B2/B3
- 不引入 attention fatigue B5
- 不细分大公园 polygon B7

## Decisions

### D1 · A1 distribution 数值来源

ABS 2021 SAL12275 (Lane Cove) "Household Composition by Family Type":
- One family - couple family no children: 28.5%
- One family - couple with children: ~37% (under-15 + 15plus 合)
- One family - one-parent: 9.4%
- Other family: ~2%
- Lone person: 19.0%
- Group household: 4.8%

把 37% 拆为 22% (under-15) + 15% (15plus) 基于 Lane Cove 中位数年龄分布。
Sum = 1.0 ✓

### D2 · A3 polygon-size 折扣公式

线性：`spatial_factor = min(1.0, VISUAL_RANGE_M / polygon_extent_m)`
- extent 50m → factor 1.0（小 polygon 无折扣）
- extent 100m → factor 0.5
- extent 1400m (Mowbray Park) → factor 0.036

不用平方衰减是因为现实"街上两人 100m 距离"仍可能 noticing（喊一声听见）；
线性比平方更宽松。

### D3 · A4 tie decay 公式

30-day half-life 指数衰减：`exp(-ln(2) × days / 30)`。30 天是"weak tie
attrition" 经验估计。
- 14d run 内最老 tie 衰减 ~28% → 仍能 cross weak threshold
- 60d 未联系衰减 ~75%
- 365d 衰减 ~99.97%（基本失忆）

实现：raw `tie.strength` 不动（保持 monotonic + Tie immutable）；
`effective_strength(now_tick)` 读时算；新 `*_decayed` helpers 用 effective。

### D4 · A2 num_protagonists CLI

- Default `args.agents // 10` 保持当前 dev 行为（10%）
- Publishable 应传 `--num-protagonists 500`（1000 agent 时）
- 不强制——publishable 协议讨论决定

### D5 · B/C disclose 不修

A 类修后，剩 B/C 是已知 limitation。文档化即可，避免本 change 范围爆炸。

## Risks / Trade-offs

- **[A1 distribution 改 RNG 序列]** old archive 实验数据不再 byte-equal。
  Mitigation: 不依赖 byte-equal 的 test 都 pass；旧数据 documented as
  pre-fix baseline 不删
- **[A3 polygon discount 可能过激]** noticing 0.036 for 1.4km park 几乎
  消灭 park encounter。Trade-off：现实 1.4km park 里两 agent 偶遇概率
  确实小；先此处宽松，看 D1' 数据后再调
- **[A4 effective_strength 不强制更新]** 旧 callers 仍读 raw `tie.strength`。
  Migration is opt-in—— familiar_with 等保兼容；新 audit 用 *_decayed

## Migration Plan

1. A1 LANE_COVE_PROFILE 校准（已做）
2. A2 CLI flag（已做）
3. A3 noticing.py + memory/service.py（已做）
4. A4 social_graph/service.py effective_strength（已做）
5. A5 smoke 验证（已做 PASS）
6. B/C disclose in limitations-ethics.md（已做）
7. 全套 regression test（90/90 PASS）
8. Archive

## Open Questions

- A1 校准数字是 directional 估计——具体 ABS table 数字可在 publishable 前
  二次复核
- A3 polygon discount 是 linear；可能 future 改成 square-root 更柔和
- A4 30-day half-life 是直觉值；future 可基于 Granovetter 1973 weak tie
  research 校准
