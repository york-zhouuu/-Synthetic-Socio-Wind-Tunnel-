## 1. B8 phase_config 字符串索引（最小 / 独立 / 零回归）

- [x] 1.1 修 `tools/run_variant_suite.py` 第 762–770：在调 `compute_reproducibility_lock` 前 `parts = [int(x) for x in args.phase_days.split(",")]`，传 `parts[0]/[1]/[2]`
- [x] 1.2 新增 `tests/test_run_variant_suite_reproducibility_lock.py`：构造一个 1 day × 1 seed × 5 agent run，断言 `seed_*.json` 中 `extensions.reproducibility_lock.phase_config` 三个字段都是 int 且 ≥ 0
- [x] 1.3 跑 `pytest tests/test_run_variant_suite_reproducibility_lock.py -v`，过

## 2. metrics: traj_dev_m 改成 protag-only + 新增 traj_dev_m_all 字段

- [x] 2.1 修改 `synthetic_socio_wind_tunnel/metrics/models.py::RunMetrics`：新增 `trajectory_deviation_m_all: float | None = None` 字段；现有 `trajectory_deviation_m` 字段保持名字不变，doc 更新为"protag-only median"
- [x] 2.2 修改 `synthetic_socio_wind_tunnel/metrics/factory.py::_compute_trajectory_deviation_m`：返回 `tuple[float | None, float | None]`（target_subset_median, all_median）；从 variant_metadata 读 `target_agent_ids`，缺省时 fallback 到 `is_protagonist=True` 的 agent
- [x] 2.3 修改 factory 上层调用方 `build_run_metrics`：把两个返回值分别赋给 `trajectory_deviation_m` 与 `trajectory_deviation_m_all`
- [x] 2.4 新增 `tests/test_metrics_factory_traj_dev_subset.py`：构造 hp variant 下 100 agent (10 protag) 的 fake recorder + multi_day_result，断言 `traj_dev_m`（protag 子集）与 `traj_dev_m_all`（全集）数值通常不同；fallback 路径：metadata 不含 target_agent_ids 时仍只在 protag 子集上算
- [x] 2.5 修改 `tests/test_metrics_*` 中既有 traj_dev 断言，按新口径更新预期值（已审：现有 metrics_models 和 aggregator 测试只填字段不依赖具体口径，无需改）
- [x] 2.6 跑 `pytest tests/ -k metrics -v`，过（69 passed）

## 3. policy-hack: gd 把 target_agent_ids resolved 写进 metadata_dict

- [x] 3.1 修改 `synthetic_socio_wind_tunnel/policy_hack/variants/global_distraction.py`：增加 `_resolved_target_ids: tuple[str, ...] | None = PrivateAttr(None)`；在 `apply_day_start` 第一次执行时缓存 resolved；overload `metadata_dict()` 把缓存的 target_agent_ids 写进返回 dict
- [x] 3.2 同步修改 `synthetic_socio_wind_tunnel/policy_hack/variants/hyperlocal_push.py`：同样通过 metadata_dict 暴露 target_agent_ids（hp 已有 _resolved_target_ids，只需 expose）
- [x] 3.3 新增 `tests/test_variant_metadata_target_ids.py`：实例化 hp / gd，调 apply_day_start 一次后调 metadata_dict，断言返回 dict 含非空 target_agent_ids
- [x] 3.4 跑测试，过（5 passed + 69 policy_hack regression passed）

## 4. policy-hack: phone_friction 通过 attention_service 注入 trigger event

- [x] 4.1 修改 `synthetic_socio_wind_tunnel/policy_hack/variants/phone_friction.py`：增加字段 `nudge_content_templates: tuple[str, ...]`（默认 ≥ 3 条）、`nudge_target_ratio: float = 1.0`、`primary_metric_name: str = "encounter.per_day_median"`
- [x] 4.2 增加 `apply_day_start(ctx)` 实现：在 intervention phase 内每日选 `floor(ratio * len(runtimes))` 个 agent（agent_id 字典序，seed-bound），构造 `FeedItem(source="neighbourhood", category="self_reflection", origin_hack_id="phone_friction", urgency=0.5, content=rng.choice(templates))`，调 `ctx.attention_service.inject_feed_item(item, target_ids)` — 注：source 复用 `neighbourhood`（最贴近"附近邻居"语义），不为 friction nudge 扩 FeedSource Literal
- [x] 4.3 新增 `tests/test_phone_friction_behavioral.py`：(a) pf 当日 attention_service.inject_feed_item 被调 ≥ 1 次；(b) inject 的 FeedItem 标签正确；(c) variant.metadata_dict()["primary_metric_name"] == "encounter.per_day_median"
- [x] 4.4 跑 `pytest tests/test_phone_friction_behavioral.py -v`，过（6 passed）

## 5. suite-wiring: StubReplanLLM 给 gd / pf 返回非空 plan

- [x] 5.1 在 `tools/suite_stub_llm.py` 增加 `_pick_distraction_location(atlas, target_location, destinations) -> str | None`：从 `atlas.list_outdoor_areas()` 选距 target_location 最远的；fallback `destinations[-1]`
- [x] 5.2 修改 `StubReplanLLM.__init__` 签名：增加可选 `atlas` 与 `destinations` 参数（保留向后兼容）
- [x] 5.3 在 `StubReplanLLM.generate` 的 dispatch 分支增加：gd → `_pick_distraction_location` / pf → `_pick_community_location`
- [x] 5.4 修改 `tools/run_variant_suite.py` 构造 `StubReplanLLM` 处（通过 `make_llm_client`）：传入 atlas + destinations
- [x] 5.5 修改 `tests/test_suite_stub_llm.py`：删旧的"gd/pf 返回空"断言；新增 gd / pf 非空 plan 断言；degraded fallback 路径测试
- [x] 5.6 跑 `pytest tests/test_suite_stub_llm.py -v`，过（12 passed）

## 6. suite-wiring: replan_count 拆 plan-changed vs no-op

- [x] 6.1 修改 `synthetic_socio_wind_tunnel/agent/planner.py::Planner.replan` 签名：返回 `tuple[DailyPlan, bool]`（new_plan, changed）
- [x] 6.2 grep 全 repo `planner.replan(` callers；更新 memory/service + 4 个测试文件解包 tuple
- [x] 6.3 修改 `synthetic_socio_wind_tunnel/memory/service.py`：增加 `_replan_no_op_count_today` 与 `replan_no_op_count_today_total()` accessor；按 changed 路由
- [x] 6.4 修改 `tools/run_variant_suite.py::_run_one_variant`：replan_counter 加 `no_op_total` / `no_op_by_day`；with_extensions 写 `replan_no_op_count` + `replan_no_op_by_day`
- [x] 6.5 修改 `tests/test_planner_replan.py` / `test_memory_debts_fixed.py` / `test_replan_prompt_structure.py` / `test_suite_stub_llm.py` 中现有 replan 测试：解包 tuple
- [x] 6.6 新增 `tests/test_memory_replan_counter_split.py`：5 tests for tuple semantics + counter routing
- [x] 6.7 跑 `pytest tests/ -k "planner or memory" -v`，过（178 passed）

## 7. 上游 reader / report 同步更新

- [x] 7.1 v3 是 pre-fix 数据快照（读取 `/tmp/*.json`），保留为历史证据；后续报告基于新字段重新生成（与 group 8 smoke 一并）
- [x] 7.2 修改 `synthetic_socio_wind_tunnel/metrics/contest.py`：phone_friction primary metric `attention.phone_feed_proxy` → `encounter.per_day_median`；direction dispatch `lower` → `higher`（friction 应推人遇见更多）
- [x] 7.3 跑 `pytest tests/ -k "contest or report" -v`，过（28 passed）

## 8. End-to-end smoke 验证

- [x] 8.1 跑 1 seed × 3 day × 20 agent × 4 variant smoke 通过：baseline/hp/gd/pf 分别产出 encounter total 87/87/86/86（不再 byte-identical），hp.traj_subset=146.1 < gd.traj_subset=161.7（CLI run）
- [x] 8.2 写 `tests/test_variant_smoke_e2e.py`：6 断言（encounter pairwise 不等 / baseline replan==0 / no_op==0 / traj_dev_m 双字段填充 / baseline traj_dev=None / pf primary 是 encounter）。删除 traj_subset != traj_all 严格断言（小尺度 smoke 下两值偶有重合，大规模 30-seed 才稳定分离）
- [x] 8.3 跑 `pytest tests/test_variant_smoke_e2e.py -v`，过（6 passed）

## 9. 全量回归 + 文档

- [x] 9.1 跑 `pytest tests/ -v`，断言 1123+ passed（不应有回归）；3 skipped 仍 ok（结果：1161 passed / 3 skipped）
- [x] 9.2 在 `docs/audit/2026-05-09-bug-hunt.md` 末尾追加"修复记录"小节：列出本 change 修复了 B1/B2/B3/B4/B5/B7/B8（B6 留给下一个 cost-budget change）
- [x] 9.3 更新 `docs/agent_system/16-metrics.md` 与 `docs/agent_system/17-suite-wiring.md` 中提到 traj_dev / StubReplanLLM dispatch / replan_count 的段落，反映新语义
- [x] 9.4 跑 `openspec validate fix-variant-measurement-and-friction --strict`，过
