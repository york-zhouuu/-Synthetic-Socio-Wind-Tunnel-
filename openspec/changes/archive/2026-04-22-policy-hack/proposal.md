## Why

`research-design` 已冻结"4 条 rival hypothesis × 14 天协议 × β 严谨度 + 1
paired mirror"的实验结构；`multi-day-simulation` 提供了 14 天执行基建
（`MultiDayRunner` + `CarryoverContext`）。现在缺的是**真正能往里喂 4 条
variant 的干预生成器**——没有它，Orchestrator 每天跑 288 tick 也只是在
Baseline 重复。

具体缺什么：
1. **干预抽象不存在**：`attention-channel` 有 `FeedItem` / `NotificationEvent`
   数据结构，`AttentionService.inject_feed_item()` 有通道——但**没有组织这些
   feed items 的 "variant" 类**。每个实验要写独立的 feed 生成脚本会重复
   劳动、也违反 `experimental-design` 的"每 variant 绑定一个 hypothesis"
   结构。
2. **Phase 切换无专门抽象**：14-day protocol 要求 Baseline(4)/Intervention(6)/
   Post(4) 三段切换。`multi-day-simulation` 把这个责任留给了调用方的
   `on_day_start` hook，但每个实验 change 都重写 phase 判断是反模式。
3. **4 条 variant 跨 class 机制不同**：
   - A. Hyperlocal Push → 写 feed（注 attention-channel）
   - B. Phone Friction → 改 `DigitalProfile.screen_time_hour`
   - C. Shared Anchor → 多 agent 共享 task-category feed
   - D. Catalyst Seeding → 改 population 采样
   - A'. Global Distraction → 写 feed（攻击向）
   没有统一 `Variant` 抽象会让 CLI / 报告 pipeline 各做各的。
4. **Fitness-report 锚点**：`data/fitness-report.json` 中
   `phase2-gaps.policy-hack` 状态 **FAIL**，`mitigation_change="policy-hack"`
   指向本 change（探针路径 `synthetic_socio_wind_tunnel.policy_hack`）。

本 change 提供的就是**干预生成器工具箱 + Phase 控制器 + 4+1 具体 variant
+ CLI 扩展**，让 research-design 定义的实验能真正**启动**。

**Chain-Position**: `algorithmic-input`（主体——注入扰动到 feed/配置/人群
层）；注意 variant B（Phone Friction）直接改 `DigitalProfile` 属于
`attention-main` 的 parameter 调节，variant D（Catalyst Seeding）改 population
composition 属于结构层——这与 `experimental-design` spec "4 条 cross-class"
的要求一致：不同 variant 本来就该打不同层，container change 归位到最密集
的那一层即可。

## What Changes

### 1. 新增 `policy-hack` capability（NEW）

新模块 `synthetic_socio_wind_tunnel/policy_hack/`，提供：

- **`Variant` 抽象基类**：统一 4+1 variants 的生命周期（`apply_population()`
  在 run 前改人群、`apply_day_start(ctx)` 在 intervention phase 的每日 start
  执行干预、`apply_day_end(ctx)` 日末清理）
- **`PhaseController`**：按 `day_index` 返回 "baseline" / "intervention" /
  "post" 三状态，可自定义边界（默认 4/6/4 = 14 天）
- **4 条 primary variant 的实现类**：
  - `HyperlocalPushVariant`（H_info）
  - `PhoneFrictionVariant`（H_pull）
  - `SharedAnchorVariant`（H_meaning）
  - `CatalystSeedingVariant`（H_structure）
- **1 条 paired mirror variant**：`GlobalDistractionVariant`（A' — 与 A
  配对，β 严谨度交付）
- **`VariantRunnerAdapter`**：把 `Variant` + `PhaseController` 挂到
  `MultiDayRunner` 的 `on_day_start` / `on_day_end` hook（"wire" 辅助类，
  调用方一行挂入）

### 2. 扩展 CLI（run_multi_day_experiment.py）

- 新增 `--variant <name>` 的实际 dispatch（当前是 pass-through 字符串）
- 新增 `--phase-days 4,6,4` 参数覆盖 PhaseController 默认
- 每 variant 写 JSON 时附带 `variant_metadata`（hypothesis / theoretical_lineage /
  success_criterion / failure_criterion），供未来 metrics change 消费
- 新增 `tools/run_variant_suite.py`：一次跑 1 个 variant × N seed × 14 天
  的 suite，产 aggregate + provenance manifest

### 3. 扩展 Fitness-audit

- `phase2-gaps.policy-hack` 探针：一旦 `synthetic_socio_wind_tunnel.policy_hack`
  可导入 → auto-PASS

### 4. 文档

- `docs/agent_system/15-policy-hack.md` canonical 文档：
  - 每 variant 的 Diagnosis-Cure-Outcome-Interpretation 四段 scaffold
  - Phase 时序图 / hook 注入点
  - CLI 示例：如何跑一条 A + A' pair
  - 与 `experimental-design` spec 条款的逐条对应
- `docs/agent_system/13-research-design.md`：Part II 的 variant 描述段
  加 "实现位置" 引用（指向本 change）

## Non-goals

- **不**实现任何 metrics 算法（轨迹偏离 / encounter 密度等由 `metrics`
  change 采集；本 change 只负责**施加干预 + 元数据记录**）
- **不**实现剩余 3 个 mirror（B' / C' / D' — `experimental-design` spec
  附录 A 已文档化仅不实现）
- **不**改 `attention-channel` 能力契约：只是其客户端。feed_item 注入
  仍走 `AttentionService.inject_feed_item`
- **不**改 `multi-day-simulation` 能力契约：只是其客户端。用公开的
  `on_day_start` / `on_day_end` hook
- **不**引入真实 LLM 生成 feed content：所有 4+1 variant 用**模板字符串 +
  参数化**生成 feed，保证 reproducibility；真实 LLM 生成作为未来扩展
- **不**处理 variant 间组合（"A + D 同时跑"）：单实验跑单 variant，
  experimental-design 的 rival contest 是**横向**对比而非组合
- **不**向 `cost.py` 或 `model-budget` 加新条目：policy-hack 不触发 LLM
  调用（feed 内容是模板）

## Capabilities

### New Capabilities

- `policy-hack`: 干预生成器工具箱。提供 `Variant` 抽象 + `PhaseController`
  + 4 + 1 具体 variant 实现 + `VariantRunnerAdapter`。与 `multi-day-run`
  + `attention-channel` + `agent` 的关系为纯客户端。

### Modified Capabilities

（无——本 change 是新 capability，不改现有 spec 契约）

## Impact

- **新代码**：
  - `synthetic_socio_wind_tunnel/policy_hack/__init__.py`（re-export）
  - `synthetic_socio_wind_tunnel/policy_hack/base.py`（`Variant` / `PhaseController` / `VariantContext` / `VariantRunnerAdapter`）
  - `synthetic_socio_wind_tunnel/policy_hack/variants/hyperlocal_push.py`（A）
  - `synthetic_socio_wind_tunnel/policy_hack/variants/phone_friction.py`（B）
  - `synthetic_socio_wind_tunnel/policy_hack/variants/shared_anchor.py`（C）
  - `synthetic_socio_wind_tunnel/policy_hack/variants/catalyst_seeding.py`（D）
  - `synthetic_socio_wind_tunnel/policy_hack/variants/global_distraction.py`（A' mirror）
  - `tools/run_variant_suite.py`（新 CLI）
- **修改**：
  - `synthetic_socio_wind_tunnel/__init__.py`（re-export 公开 API）
  - `synthetic_socio_wind_tunnel/fitness/audits/phase2_gaps.py`（probe 已存在但
    mitigation_change 验证；module 创建后自动 PASS）
  - `tools/run_multi_day_experiment.py`（接入 `--variant` dispatch 到真实
    Variant 实例）
- **新增测试**：
  - `tests/test_policy_hack_base.py`（Variant 抽象、PhaseController）
  - `tests/test_variant_hyperlocal_push.py`
  - `tests/test_variant_phone_friction.py`
  - `tests/test_variant_shared_anchor.py`
  - `tests/test_variant_catalyst_seeding.py`
  - `tests/test_variant_global_distraction.py`
  - `tests/test_variant_runner_adapter.py`（集成）
- **前置依赖**：`experimental-design` spec（引用）+ `multi-day-simulation`
  capability（`MultiDayRunner` / `on_day_start` hook）+ `attention-channel`
  （`FeedItem` / `AttentionService`）+ `agent`（`PopulationProfile` /
  `sample_population` / `DigitalProfile`）——**全部已实现**
- **下游依赖**：`metrics` change 将消费本 change 产出的 `variant_metadata`
  + `MultiDayResult` 来计算 thesis-层信号
- **fitness-report 影响**：`phase2-gaps.policy-hack` FAIL → PASS（实施后）
- **性能**：4 条 variant 均不引入 LLM 调用；wall time 与 baseline（无干预）
  持平（< 20 s per seed × 14 day × 100 agent）
