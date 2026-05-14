## MODIFIED Requirements

### Requirement: StubReplanLLM 按 variant_name 分派行为

`tools/suite_stub_llm.py::StubReplanLLM` SHALL 是 `LLMClient` 协议的纯
Python 实现；`__init__(*, seed, variant_name, target_location, atlas, destinations)`
接收 variant 身份与目标位置；`generate(prompt, *, model)` **忽略 prompt 内容**，
按 variant_name 返回预定的 XML plan 片段：

| variant_name | Stub 响应 |
|---|---|
| `hyperlocal_push` | 含 1 条 PlanStep 走向 target_location（action="move"） |
| `global_distraction` | **含 1 条 PlanStep 走向 distraction_destination**（atlas 中距 target_location 最远的 outdoor area；fallback `destinations[-1]`） |
| `phone_friction` | **含 1 条 PlanStep 走向 community_heuristic_outdoor**（park / plaza；fallback `destinations[0]`），代表"放下手机回附近" |
| `shared_anchor` | 走向 community heuristic location（park/plaza 或 destinations[0]） |
| `catalyst_seeding` / 未知 | `"<plan></plan>"` |

输出 SHALL 是 Planner.replan 可解析的 XML 格式；stub **MUST NOT** 调用任何
外部 LLM / 网络。

**关键变更**：原版本对 `global_distraction` 与 `phone_friction` 都返回 `"<plan></plan>"`，
导致 Planner.replan 退回 deep_copy(unchanged) → variant 在 stub 路径下无任何
可观测行为差异（参见 `docs/audit/2026-05-09-bug-hunt.md` B2/B3）。修订后 stub
为这两个 variant 也产生真的 plan 改动，让 stub 路径下 4 个 variant 都能产出
可对比的 metric。

#### Scenario: hyperlocal_push stub 产出包含 target
- **WHEN** 构造 `StubReplanLLM(seed=0, variant_name="hyperlocal_push",
  target_location="cafe_main")`；调 `generate("any prompt")`
- **THEN** 返回字符串 SHALL XML-parse 为非空 plan；至少一个 step 的
  `destination == "cafe_main"`；action 包含 "move"

#### Scenario: global_distraction stub 返回非空 distraction plan
- **WHEN** 构造 `StubReplanLLM(seed=0, variant_name="global_distraction",
  target_location="cafe_main", atlas=lc_atlas, destinations=("park_a","mall_b","far_corner"))`；调 `generate`
- **THEN** 返回字符串 SHALL XML-parse 为非空 plan；
  `destination` SHALL 是 atlas 中距 cafe_main 最远的 outdoor area（或 fallback 到 `far_corner`）；
  destination SHALL **不等于** `cafe_main`

#### Scenario: phone_friction stub 返回 community heuristic
- **WHEN** 构造 `StubReplanLLM(seed=0, variant_name="phone_friction",
  atlas=lc_atlas, destinations=("park_a","mall_b"))`；调 `generate`
- **THEN** 返回字符串 SHALL XML-parse 为非空 plan；
  destination SHALL 是 park / plaza / square 类型的 outdoor area
  （atlas 缺省时 fallback `destinations[0]`）

#### Scenario: 跨 seed reproducibility
- **WHEN** 两次分别构造同 seed 的 StubReplanLLM；各调 generate 3 次
- **THEN** 两组返回 SHALL byte-equal


### Requirement: Replan 计数写入 RunMetrics.extensions

每个 seed 的 RunMetrics SHALL 通过 `with_extensions` 携带以下键：

- `replan_count: int`（**plan 真改的 replan 次数**——`new_future_steps` 非空且与原 plan 不全等）
- `replan_no_op_count: int`（**调用了 LLM 但 plan 未变**：fallback 到 deep_copy(unchanged) 的次数）
- `replan_by_day: list[int]`（per-day `replan_count` 计数，长度 == num_days；不含 no_op）
- `replan_no_op_by_day: list[int]`（per-day no-op 计数）

**语义变更**：原 `replan_count` 包含 fallback 的空 replan，让 reader 误以为 plan 被改了
（参见 `docs/audit/2026-05-09-bug-hunt.md` B7：gd 显示 44–105 次 replan，但 100% 是空 replan）。
修订后 `replan_count` 严格表示"plan 真改"。

实现要点：`Planner.replan` SHALL 返回 `tuple[DailyPlan, bool]` —— 第二个元素 `changed: bool`
表示 plan 是否被真改（`new_future_steps` 非空且不与 `current_plan` 完全相等）；
`memory.process_tick` 据 `changed` 分流计入 `replan_count` / `replan_no_op_count`。

不得新增 RunMetrics 的 typed 字段（metrics spec 明文 extensions 作未来挂载点）。

#### Scenario: replan_count 不再含空 replan
- **WHEN** 一个 14 day run，gd variant + StubReplanLLM(预修订时返回空 plan)
- **THEN** `extensions["replan_count"]` SHALL 为该跑里 plan 真被改的次数；
  `extensions["replan_no_op_count"]` SHALL 累计所有 fallback 次数

#### Scenario: replan_count 等于 by_day 之和
- **WHEN** 一个 14 day run 的 RunMetrics dump
- **THEN** `extensions["replan_count"] == sum(extensions["replan_by_day"])`；
  `extensions["replan_no_op_count"] == sum(extensions["replan_no_op_by_day"])`

#### Scenario: Dump 到 seed_<N>.json
- **WHEN** `run_variant_suite.py` 跑完一个 seed
- **THEN** `seed_<N>.json` 中 `run_metrics.extensions` SHALL 含 `replan_count`、
  `replan_no_op_count`、`replan_by_day`、`replan_no_op_by_day` 四键


### Requirement: 行为差异最小要求

suite-wiring change 的实施结果 SHALL 让以下行为差异在 1 day × 1 seed × 20 agent ×
4 variant smoke 配置下可被 E2E 测试验证：

- `hyperlocal_push.trajectory_deviation_m`（protag-only）SHALL **小于**
  `global_distraction.trajectory_deviation_m`（protag-only）——hp 把 target
  拉向 push location；gd 把 target 拉向相反的 distraction location
- `phone_friction.encounter.per_day_median` SHALL **大于** `baseline.encounter.per_day_median` —— friction 把人推到户外，encounter 提升
- 4 个 variant 的 `encounter_stats.total` SHALL **两两不相等**（不再 byte-identical）
- `hyperlocal_push.replan_count` SHALL > 0，`phone_friction.replan_count` SHALL > 0，`global_distraction.replan_count` SHALL > 0
- `baseline.replan_count` SHALL == 0
- 4 个 variant 各自的 `replan_no_op_count` SHALL 在 stub 路径下 == 0（stub 永不返回空 plan，除 baseline / catalyst_seeding 外）

**阈值**：方向正确即可，不做 CI 分离检查——本 change 目标是因果链通，严谨 CI
由后续 publishable 30 seed × 14 day 产出。

#### Scenario: E2E 断言 4 variant 行为可区分
- **WHEN** `pytest tests/test_variant_smoke.py::test_four_variants_diverge` 运行（1 day × 1 seed × 20 agent）
- **THEN** 4 个 variant 的 encounter_stats.total SHALL pairwise 不等；
  hp.trajectory_deviation_m < gd.trajectory_deviation_m；
  pf.encounter.per_day_median > baseline.encounter.per_day_median


### Requirement: 不改已归档 capability 的 spec

本 change 的实施 SHALL NOT 修改任何 `openspec/specs/` 下已有 spec 的
requirement 或 scenario，**除以下被本 change 显式 MODIFIED 列出的之外**：
- `openspec/specs/metrics/spec.md` — RunMetrics 数据模型 / RunMetrics.from_recorder 工厂（traj_dev_m subset 切换 + traj_dev_m_all 字段）
- `openspec/specs/policy-hack/spec.md` — PhoneFrictionVariant / GlobalDistractionVariant
- `openspec/specs/suite-wiring/spec.md` — StubReplanLLM dispatch / Replan 计数 / 行为差异最小要求

`orchestrator` / `agent` / `multi-day-run` / `attention-channel` / `memory` /
`fitness-audit` / `experimental-design` 等 capability 的 spec SHALL NOT 被本 change 触碰。

#### Scenario: 已归档 spec 文件未变（除显式 MODIFIED 外）
- **WHEN** 归档本 change 后 `git diff openspec/specs/` 于
  `orchestrator` / `agent` / `multi-day-run` / `attention-channel` /
  `memory` / `fitness-audit` / `experimental-design` 子目录
- **THEN** 输出 SHALL 为空（无修改）
