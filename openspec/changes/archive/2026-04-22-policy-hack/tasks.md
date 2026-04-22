# Tasks — policy-hack

实现 4 条 primary variant（H_info / H_pull / H_meaning / H_structure）+
1 条 paired mirror（A'）+ 统一 Variant 框架 + Phase 控制器 + CLI dispatch。

**Chain-Position**: `algorithmic-input`（主体）
**前置**: `experimental-design` spec + `multi-day-simulation` 基建 +
`attention-channel` + `agent` population
**Fitness-report 锚点**: `phase2-gaps.policy-hack` FAIL → PASS

## 1. 模块骨架 + 抽象基类

- [x] 1.1 创建 `synthetic_socio_wind_tunnel/policy_hack/__init__.py`
  （re-export 公开 API + `VARIANTS` registry）
- [x] 1.2 创建 `synthetic_socio_wind_tunnel/policy_hack/base.py`：
  - `Variant` ABC + Pydantic BaseModel 混合基类（字段 + 3 抽象方法 +
    `metadata_dict()`）
  - `PhaseController` frozen model（baseline/intervention/post_days）
  - `VariantContext` frozen dataclass
  - `VariantRunnerAdapter` class（`attach_to(runner)` + `setup_run(profiles, rng)`）

## 2. 4 条 Primary Variant 实现

- [x] 2.1 `policy_hack/variants/hyperlocal_push.py` — `HyperlocalPushVariant`（A）
  - 字段（target_location / target_agent_ids / content_templates / hyperlocal_radius_m / daily_push_count）
  - `apply_day_start`：每日选目标 + 注入 1 条 feed_item（content 模板化）
- [x] 2.2 `policy_hack/variants/phone_friction.py` — `PhoneFrictionVariant`（B）
  - 字段（friction_multiplier）
  - `apply_day_start`：intervention 第一天缓存原 profile + 构造乘 multiplier
    的新 profile，替换 `agent.runtime.profile`；post 第一天恢复
- [x] 2.3 `policy_hack/variants/shared_anchor.py` — `SharedAnchorVariant`（C）
  - 字段（share_ratio / task_templates）
  - `apply_day_start`：intervention 每日用同一 feed_item_id 注入 task feed
    到 share_ratio 比例的 agents
- [x] 2.4 `policy_hack/variants/catalyst_seeding.py` — `CatalystSeedingVariant`（D）
  - 字段（catalyst_ratio / catalyst_personality 预设）
  - `apply_population`：选 5% 用 connector personality 覆盖；`apply_day_start`
    no-op
- [x] 2.5 所有 variant 填充 `theoretical_lineage` / `success_criterion` /
  `failure_criterion` 字符串（引 research-design Part II 的 mapping）

## 3. Mirror Variant (A')

- [x] 3.1 `policy_hack/variants/global_distraction.py` — `GlobalDistractionVariant`
  - `is_mirror=True, paired_variant="hyperlocal_push"`
  - 20 条/day 饱和注入 global-news 模板；与 A 共享 target_agent_ids 选择
    逻辑（前一半 by agent_id dict sort）

## 4. Registry + CLI dispatch

- [x] 4.1 在 `policy_hack/__init__.py` 组装 `VARIANTS: dict[str, type[Variant]]`
  5 个条目
- [x] 4.2 修改 `tools/run_multi_day_experiment.py`：
  - import `policy_hack.VARIANTS`
  - `--variant <name>` 非 `baseline` → 从 registry 查 → 实例化 → 构造
    `VariantRunnerAdapter(variant, PhaseController())` → 在 build_single_seed_run
    内 `adapter.setup_run(profiles, rng)` 替换 profiles + `adapter.attach_to(runner)`
  - 未知 variant 名 → exit with error + 列出合法值
  - 生成的 `seed_<N>.json` 含 `metadata.variant_metadata` + `metadata.phase_config`
- [x] 4.3 新建 `tools/run_variant_suite.py`：一次跑 "1 variant × N seed × 14d"
  的便捷入口；包装上一步的逻辑 + aggregate

## 5. 公共 API re-export

- [x] 5.1 `synthetic_socio_wind_tunnel/__init__.py` 增加：
  - `Variant` / `PhaseController` / `VariantRunnerAdapter` / `VariantContext`
  - 5 个具体 variant 类
  - `VARIANTS` registry

## 6. 测试

- [x] 6.1 `tests/test_policy_hack_base.py`：
  - Variant ABC 不能直接实例化
  - 子类不实现 apply_day_start 无法实例化
  - PhaseController 默认 14 天边界条件（0/3/4/9/10/13）
  - PhaseController 自定义长度（1,1,1 3 天）
  - VariantRunnerAdapter.attach_to 在 baseline 不 trigger apply_day_start
  - VariantRunnerAdapter.attach_to 在 intervention 每日 trigger
  - VariantContext phase 字段正确
- [x] 6.2 `tests/test_variant_hyperlocal_push.py`：
  - 14 天跑 → 6 次注入 feed
  - baseline 无注入
  - 目标 agent 收到的 memory 事件 kind="notification"
- [x] 6.3 `tests/test_variant_phone_friction.py`：
  - intervention 开始 → screen_time_hour 乘 0.5
  - post 开始 → 恢复原值
  - agent.profile.digital 引用被替换（frozen 不破坏）
- [x] 6.4 `tests/test_variant_shared_anchor.py`：
  - 10% agents 收到同一 feed_item_id
  - CarryoverContext.pending_task_anchors 含该 task
  - Dev mode 3 天（1,1,1）仍生效
- [x] 6.5 `tests/test_variant_catalyst_seeding.py`：
  - apply_population 选 5 个 agent（100 agents pool）替换 personality
  - 其它字段（age / occupation / home）不变
- [x] 6.6 `tests/test_variant_global_distraction.py`：
  - 每 intervention day 20 条 notification
  - target_ids 与 HyperlocalPushVariant 一致（同 seed）
- [x] 6.7 `tests/test_variant_runner_adapter_integration.py`：
  - 端到端：A variant 跑 14 天 → MultiDayResult.metadata 含
    variant_metadata + phase_config
  - B variant 跑 14 天 → profile 变更与恢复路径

## 7. Fitness-audit

- [x] 7.1 确认 `synthetic_socio_wind_tunnel.policy_hack` 可 import（无需改
  phase2_gaps.py，probe 已存在）
- [x] 7.2 跑 `make fitness-audit` → `phase2-gaps.policy-hack` 从 FAIL → PASS
- [x] 7.3 更新 `tests/test_fitness_phase1_phase2.py::test_unimplemented_capabilities_still_fail`
  把 `policy-hack` 从 "still unimplemented" 集移除

## 8. 文档

- [x] 8.1 新建 `docs/agent_system/15-policy-hack.md`：
  - 5 个 variant 的 Diagnosis / Cure / Outcome criterion / Mirror pairing
  - 每 variant 的 configuration 示例
  - Phase 时序图
  - CLI 示例（`tools/run_variant_suite.py --variant hyperlocal_push`）
  - 与 experimental-design spec 每条 requirement 的对应
- [x] 8.2 更新 `docs/agent_system/13-research-design.md` Part II：
  - 每 variant 描述段末尾加"实现位置"行，指向
    `synthetic_socio_wind_tunnel/policy_hack/variants/<name>.py`
- [x] 8.3 更新 `README.md` Development Status 表：
  - 新增一行 "Policy hack (4+1 rival variants) — ✅ Complete"

## 9. CLI 冒烟 + 回归

- [x] 9.1 `python3 tools/run_multi_day_experiment.py --num-days 3 --agents 20 --seeds 2 --mode dev --variant hyperlocal_push` → 成功
- [x] 9.2 `python3 tools/run_multi_day_experiment.py --num-days 3 --agents 20 --seeds 2 --mode dev --variant global_distraction` → 成功
- [x] 9.3 `python3 tools/run_multi_day_experiment.py --num-days 3 --agents 20 --seeds 2 --mode dev --variant phone_friction` → 成功
- [x] 9.4 `python3 tools/run_multi_day_experiment.py --num-days 3 --agents 20 --seeds 2 --mode dev --variant shared_anchor` → 成功
- [x] 9.5 `python3 tools/run_multi_day_experiment.py --num-days 3 --agents 20 --seeds 2 --mode dev --variant catalyst_seeding` → 成功
- [x] 9.6 `--variant baseline` 行为与 multi-day-simulation archive 时一致
  （零 variant 参与；结果 JSON 的 variant_metadata 键 absent 或 null）
- [x] 9.7 完整 pytest 套件 0 回归

## 10. 性能

- [x] 10.1 各 variant 14 天 × 100 agent × 1 seed wall time 与 baseline
  差异 ≤ 20%（spec：variant 不引入 LLM；只是模板 + dict 操作）

## 11. 验证

- [x] 11.1 `openspec validate policy-hack --strict` 通过
- [x] 11.2 `openspec validate policy-hack --type change` 通过
- [x] 11.3 Variant 字段名一致性检查（所有子类的 `chain_position` 在 spec
  允许值集合里、`hypothesis` 正确绑定）
- [x] 11.4 grep 确保 `Variant` / `PhaseController` / `VariantRunnerAdapter`
  在 spec / 代码 / 测试 / 文档四处命名一致
