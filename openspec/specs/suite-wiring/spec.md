# suite-wiring — Suite CLI 装配契约

## Purpose

`suite-wiring` capability 是 CLI 层的"装配工"——把已归档的 attention-channel /
memory / agent / policy-hack / multi-day-run / metrics 等 capability 的公共 API
在 `tools/run_variant_suite.py` 里串起来，形成完整的 variant → attention →
memory → replan → 行为 因果链。它解决了 metrics 归档日 smoke 暴露的 wiring
缺口（variants 的 push 进入 attention channel 但无人消费 → agents 一直跑
scripted plan → variants 行为无差）。

模块同时提供 zero-cost、seed-reproducible 的 `StubReplanLLM`（按 variant_name
分派行为）以及 `--use-real-llm` opt-in（Anthropic Haiku，最小 wrap），使 suite
默认离线可跑、按需切换真 LLM。Replan 计数通过 `RunMetrics.extensions` 挂入
（`metrics` spec 明文预留点）；本 change **不**修改任何已归档 capability
的 spec 契约。

模块：`tools/run_variant_suite.py`、`tools/suite_stub_llm.py`
入口 CLI：`python tools/run_variant_suite.py`
## Requirements
### Requirement: Suite CLI SHALL wire MemoryService + Planner 到 orchestrator

`tools/run_variant_suite.py::run_seed_with_metrics` SHALL 在 orchestrator
栈里构造以下组件并把它们串进 `on_tick_end` hook 链：

1. `AttentionService`（policy-hack variant push 到此）
2. `MemoryService(attention_service=attention)`
3. `Planner(llm_client=<stub 或 real>)`
4. `TickMetricsRecorder(ledger, attention_service)`

Tick 结束时执行顺序：
```
orchestrator._run_tick → on_tick_end hook chain:
  recorder.on_tick_end(tick_result)                      # 观察，不改状态
  memory.process_tick(tick_result, agents, planner)      # 触发 replan
```

#### Scenario: 带 variant 的 run 触发非零 replan_count
- **WHEN** `run_seed_with_metrics(variant_name="hyperlocal_push", seed=0,
  n_agents=20, num_days=3, ...)` 执行
- **THEN** 返回的 RunMetrics.extensions SHALL 含 `replan_count`，值 SHALL > 0

#### Scenario: baseline 不触发 replan
- **WHEN** `run_seed_with_metrics(variant_name="baseline", ...)`
- **THEN** `replan_count` SHALL == 0（无 feed 注入 → 无 notification →
  should_replan 不通过）

### Requirement: StubReplanLLM 按 variant_name 分派行为

`tools/suite_stub_llm.py::StubReplanLLM` SHALL 是 `LLMClient` 协议的纯
Python 实现；`__init__(*, seed, variant_name, target_location, atlas, pools)`
接收 variant 身份、目标位置和 typed LocationPools（**取代旧 `destinations`
参数**）；`generate(prompt, *, model)` **忽略 prompt 内容**，按 variant_name
返回预定的 XML plan 片段：

| variant_name | Stub 响应 |
|---|---|
| `hyperlocal_push` | 含 1 条 PlanStep 走向 target_location（action="move"） |
| `global_distraction` | **含 1 条 PlanStep 走向 distraction_destination**（poi_pool 中距 target_location 最远的 POI；fallback `pools.poi_pool[-1]`） |
| `phone_friction` | **含 1 条 PlanStep 走向 community_heuristic**（poi_pool 中 park / community / plaza；fallback `pools.poi_pool[0]`），代表"放下手机回附近" |
| `shared_anchor` | 走向 community heuristic location（park / community 或 `pools.poi_pool[0]`） |
| `catalyst_seeding` / 未知 | `"<plan></plan>"` |

输出 SHALL 是 Planner.replan 可解析的 XML 格式；stub **MUST NOT** 调用任何
外部 LLM / 网络。

**关键变更**（fix-population-uses-typed-locations，2026-05-12）：原 stub
接收 `destinations: tuple[str, ...]` 单池——该池在旧 wiring 下全部是 outdoor
street，结果 stub 把 agent 推到的 distraction / community heuristic 也是
street，与 thesis "把人拉到附近的咖啡馆 / 公园 / 邻居家" 脱节。修订后 stub
接收 typed `pools`，从 `poi_pool` 选 building 类目标。

#### Scenario: hyperlocal_push stub 产出包含 target building
- **WHEN** 构造 `StubReplanLLM(seed=0, variant_name="hyperlocal_push",
  target_location="lane_cove_community_hub", pools=lc_pools)`；调
  `generate("any prompt")`
- **THEN** 返回字符串 SHALL XML-parse 为非空 plan；至少一个 step 的
  `destination == "lane_cove_community_hub"`；该 destination SHALL 在
  `pools.poi_pool` 中；action 包含 "move"

#### Scenario: global_distraction stub 返回非空 distraction plan（POI building）
- **WHEN** 构造 `StubReplanLLM(seed=0, variant_name="global_distraction",
  target_location="cafe_main", atlas=lc_atlas, pools=lc_pools)`；调 `generate`
- **THEN** 返回字符串 SHALL XML-parse 为非空 plan；
  `destination` SHALL 在 `pools.poi_pool` 中且距 cafe_main 距离最远；
  destination SHALL **不等于** `cafe_main`；destination SHALL **不是**
  outdoor street（`area_type != "street"`）

#### Scenario: phone_friction stub 返回 community heuristic
- **WHEN** 构造 `StubReplanLLM(seed=0, variant_name="phone_friction",
  atlas=lc_atlas, pools=lc_pools)`；调 `generate`
- **THEN** 返回字符串 SHALL XML-parse 为非空 plan；
  destination SHALL 是 building_type ∈ {park, community, worship} 或
  area_type ∈ {park, playground, garden} 的 POI（atlas 缺省时 fallback
  `pools.poi_pool[0]`）；SHALL NOT 是 street

#### Scenario: 跨 seed reproducibility
- **WHEN** 两次分别构造同 seed + 同 pools 的 StubReplanLLM；各调 generate 3 次
- **THEN** 两组返回 SHALL byte-equal

### Requirement: --use-real-llm 切换 LLM provider

`run_variant_suite.py` SHALL 接受 `--use-real-llm` flag（默认 False）；
True 时 planner 的 llm_client SHALL 为 `anthropic.Anthropic` 包装（若
`anthropic` 未安装 → 启动时清楚错误退出）；False 时走 StubReplanLLM。

#### Scenario: 默认不走真 LLM
- **WHEN** `python3 tools/run_variant_suite.py --variants baseline ...`（无
  `--use-real-llm`）
- **THEN** run 过程 SHALL 不触发任何外部 HTTP 调用；可离线跑

#### Scenario: --use-real-llm 未装 anthropic
- **WHEN** `anthropic` SDK 未安装；传 `--use-real-llm`
- **THEN** CLI SHALL exit with code != 0；stderr 含可 actionable 安装提示

### Requirement: Replan 计数写入 RunMetrics.extensions

每个 seed 的 RunMetrics SHALL 通过 `with_extensions` 携带以下键：

- `replan_count: int`（**plan 真改的 replan 次数**——`new_future_steps` 非空且与原 plan 不全等）
- `replan_no_op_count: int`（**调用了 LLM 但 plan 未变**：fallback 到 deep_copy(unchanged) 的次数）
- `replan_by_day: list[int]`（per-day `replan_count` 计数，长度 == num_days；不含 no_op）
- `replan_no_op_by_day: list[int]`（per-day no-op 计数）
- `reproducibility_lock: dict`（7 字段复现锁；含 `provider` 反映实际跑的 LLM provider）

**语义变更**（fix-variant-measurement-and-friction + fix-encounter-detection-and-observability）：
原 `replan_count` 包含 fallback 的空 replan，让 reader 误以为 plan 被改了
（参见 `docs/audit/2026-05-09-bug-hunt.md` B7）。修订后 `replan_count` 严格表示"plan 真改"。
原 `reproducibility_lock` 调用方硬编码 `provider=None`，让 model_version 永远
是 `stub:v1`（B10）。修订后 `provider` 反映实际 provider（gemini / anthropic / stub）。

实现要点：`Planner.replan` SHALL 返回 `tuple[DailyPlan, bool]` —— 第二个元素 `changed: bool`
表示 plan 是否被真改；`memory.process_tick` 据 `changed` 分流计入 `replan_count` /
`replan_no_op_count`。`compute_reproducibility_lock` SHALL 接收 `provider` 参数：
- `--use-aitown` 启用时，传 `aitown_provider`（即 `--aitown-provider` flag 的值）
- 仅 `--use-real-llm` 启用时，传 `"anthropic"`
- 否则传 `"stub"`

`reproducibility_lock["model_version"]` SHALL 反映 provider，例如：
- gemini provider → `"gemini:flash-preview"`
- anthropic provider → `"anthropic:haiku-4-5"`
- stub → `"stub:v1"`（保留兼容老快照的字符串）

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
  `replan_no_op_count`、`replan_by_day`、`replan_no_op_by_day`、
  `reproducibility_lock` 五键

#### Scenario: rep_lock provider 反映 gemini 配置
- **WHEN** `--use-aitown --aitown-provider gemini` 跑 1 seed
- **THEN** `extensions["reproducibility_lock"]["provider"]` SHALL == `"gemini"`；
  `extensions["reproducibility_lock"]["model_version"]` SHALL 包含 `"gemini"`
  子串（不再是 `stub:v1`）

#### Scenario: rep_lock provider 反映 stub 配置
- **WHEN** 不带 `--use-aitown` 也不带 `--use-real-llm` 跑 1 seed
- **THEN** `extensions["reproducibility_lock"]["provider"]` SHALL == `"stub"`

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
- **新增**：baseline 跑完后 `space_activation` 的 `building_type ==
  "residential"` 累计 dwell ≥ 全体 dwell 的 40%；`area_type == "street"` 累计
  dwell ≤ 全体 dwell 的 20%

**阈值**：方向正确即可，不做 CI 分离检查——本 change 目标是因果链通 + agent
真有家，严谨 CI 由后续 publishable 30 seed × 14 day 产出。

#### Scenario: E2E 断言 4 variant 行为可区分
- **WHEN** `pytest tests/test_variant_smoke.py::test_four_variants_diverge` 运行（1 day × 1 seed × 20 agent）
- **THEN** 4 个 variant 的 encounter_stats.total SHALL pairwise 不等；
  hp.trajectory_deviation_m < gd.trajectory_deviation_m；
  pf.encounter.per_day_median > baseline.encounter.per_day_median

#### Scenario: dwell 分布通过 acceptance
- **WHEN** `python3 tools/audit_dwell_distribution.py
  data/experiments/<smoke_dir>/variant_baseline` 在 fix 后的 baseline seed
  上跑
- **THEN** SHALL exit with code 0；stdout 含
  `residential_share=0.XX (>=0.40 ✓)` 与 `street_share=0.XX (<=0.20 ✓)`

### Requirement: 不改已归档 capability 的 spec

本 change 的实施 SHALL NOT 修改任何 `openspec/specs/` 下已有 spec 的
requirement 或 scenario（orchestrator / memory / agent / policy-hack /
multi-day-run / metrics / attention-channel 全部不动）。所有改动限于：
- 新增 `tools/suite_stub_llm.py`
- 修改 `tools/run_variant_suite.py`
- 新增 `tests/test_suite_stub_llm.py` 与 `tests/test_suite_wiring.py`
- 新增 `docs/agent_system/17-suite-wiring.md`
- 更新 `README.md` Development Status

#### Scenario: 已归档 spec 文件未变
- **WHEN** 归档 suite-wiring change 后 `git diff openspec/specs/` 于
  `orchestrator` / `memory` / `agent` / `policy-hack` / `multi-day-run` /
  `metrics` / `attention-channel` 子目录
- **THEN** 输出 SHALL 为空（无修改）

### Requirement: Suite CLI SHALL build typed LocationPools before population sampling

`tools/run_variant_suite.py::run_seed_with_metrics` SHALL 在 sample_population
调用前调 `synthetic_socio_wind_tunnel.agent.location_pools.build_location_pools`
构造 `LocationPools(home_pool, work_pool, poi_pool, target_location)`：

- `home_pool` SHALL 是 `atlas.list_residential_buildings()` 中可达连通子图的
  采样子集，`len(home_pool) >= max(40, n_agents / 2)`
- `work_pool` SHALL 是 `building_type in {office, school, commercial,
  community, hospital}` 的采样子集，`len(work_pool) >= 20`
- `poi_pool` SHALL 是 `building_type in {cafe, restaurant, shop, bar,
  entertainment, hotel, worship}` ∪ `area_type in {park, playground, garden}`
  的采样子集，`len(poi_pool) >= 30`
- 三池 SHALL pairwise disjoint
- `target_location`（variant push target）SHALL 是 `poi_pool` 子集中的一个
  community-heuristic（cafe / park / community），不再是 outdoor street

构造失败 SHALL raise `LocationPoolError`；run_seed_with_metrics SHALL 把 error
直接传播给调用方（不退化、不 fallback 到旧 outdoor-only 行为）。

#### Scenario: Suite 调 build_location_pools 而非 _pick_connected_destinations
- **WHEN** `run_variant_suite.py --seeds 1 --num-days 1 --agents 100` 跑
- **THEN** 调用栈 SHALL 包含 `build_location_pools`；
  返回的 `LocationPools` SHALL 通过类型断言（home_pool 全为 residential
  building，poi_pool 不含 residential，target_location 在 poi_pool 中）

#### Scenario: pool 数量不足时 fail-fast
- **WHEN** 用一个故意小的 atlas（少于 40 residential buildings）调
  `build_location_pools(atlas, home_count=40, ...)`
- **THEN** SHALL raise `LocationPoolError`；suite CLI SHALL exit with
  code != 0；stderr 含 "home_pool insufficient" 字样

### Requirement: target_location SHALL 来自 POI pool 且按 variant 选 community heuristic

variant push target 的 community-heuristic 选择 SHALL：

- `target_location` SHALL 优先选 `poi_pool` 中 `building_type == "community"`
  的建筑；若无，回退到 `building_type == "cafe"`；再回退到 `area_type in
  {park, plaza, community_garden}`；最后回退到 `poi_pool[0]`
- `target_location` SHALL NOT 是 outdoor street（即 `area_type == "street"`
  的 outdoor_area 永不作为 target）

#### Scenario: target 不是街段
- **WHEN** 任意 variant 跑完，dump `extensions.target_location`
- **THEN** `target_location` SHALL 是 building id 或非 street outdoor area；
  SHALL NOT 以 `road_` 或 `seg_` 模式匹配

### Requirement: run_variant_suite SHALL expose --num-protagonists CLI flag

`tools/run_variant_suite.py` MUST accept a `--num-protagonists` integer
argument that controls how many sampled agents are flagged
`is_protagonist=True` (Sonnet tier; LLM-driven decisions; receive
ai-town injections).

Default behaviour SHALL be `max(1, args.agents // 10)` (10% of population),
preserving current dev-mode speed.

Publishable runs SHOULD pass an explicit higher value (e.g. `--num-protagonists 500`
for `--agents 1000`) so variant-push effects are not diluted by a 90%
scripted-only population (A2 disclosure).

The value SHALL be forwarded to `run_seed_with_metrics(...,
num_protagonists=...)` for each seed.

#### Scenario: default is 10% of agents
- **WHEN** `run_variant_suite.py --agents 100` is invoked without
  `--num-protagonists`
- **THEN** the run SHALL use `num_protagonists = 10`

#### Scenario: explicit value overrides
- **WHEN** `run_variant_suite.py --agents 1000 --num-protagonists 500`
  is invoked
- **THEN** the run SHALL use `num_protagonists = 500` and at least 500
  sampled agents SHALL have `is_protagonist == True`

#### Scenario: minimum 1 protagonist
- **WHEN** `--agents 5` is invoked without `--num-protagonists`
- **THEN** the run SHALL use `num_protagonists = max(1, 5 // 10) = 1`

