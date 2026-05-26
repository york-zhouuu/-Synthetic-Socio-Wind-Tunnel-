# Synthetic Socio Wind Tunnel · 全数据通用盘点

**目的**: 详尽列出项目目录下所有数据资产 — 每个文件 / 每种结构 / 每个字段。不预设用途,只描述。

**版本**: 2026-05-23 · 基于 `data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245/` 主参考 run

---

## 0. 顶层 `data/` 目录结构

```
data/
├── README.md                          # 数据目录说明
├── lanecove_atlas.json (12.9 MB)      # 主原子模型 atlas
├── lanecove_enriched.geojson (8.9 MB) # 富化后 GeoJSON
├── lanecove_enriched.stats.json
├── lanecove_osm.geojson (3.6 MB)      # 源 OpenStreetMap
├── lanecove_proj_center.json          # AEQD 投影参数
├── overture_buildings.geojson (3.8 MB)
├── overture_places.geojson (1.9 MB)
├── lanecove/                          # ← 仿真 grounding 模板源数据
├── calibration/                       # ← ABS census + 校准报告
├── face_validity/                     # ← 用户研究素材
├── realism/                           # ← 基线 metrics
├── exports/                           # ← evidence_report.html 等导出
├── lanecove/                          # 源模板
├── population_cache/v1/               # 1000 agent profile 缓存
├── setup_content_cache/               # 每 seed 预生成 life_history + identity_text
├── experiments/                       # 仿真 run 输出 (主要)
├── experiments_archive_pre_2026_05_21/ # 历史归档
└── analysis/                          # 后处理分析产物
```

---

## 1. 源模板数据 (data/lanecove/)

仿真生成 agent identity / push 内容 / 对话 grounding 的素材库。

### 1.1 `archetypes.json`

11 个 Lane Cove 居民原型(覆盖 ABS 2021 census ~87% 成人人口)

**字段**: schema_version, description, archetypes []

每 archetype:
- name (eg "Newly_arrived_renter")
- weight_pct (人口占比)
- demographics, household, income, occupation 分布
- typical_routine, typical_concerns
- life_history_template_ids

**用途**: setup 时按 census 权重 sample,LLM 用此 ground identity 生成

### 1.2 `shared_memories.json`

12 条 Lane Cove 公共记忆事件,每个 agent 都有(作为 baseline knowledge)

实例:
- `lc_mem_001` Galuwa Recreation Centre 开放
- `lc_mem_002` Lane Cove Tunnel 起重机起火
- `lc_mem_003` Longueville 大规模毒树事件
- `lc_mem_004` Crows Nest Metro 开通
- `lc_mem_005` St Leonards South 高密度重新规划
- `lc_mem_006` Lane Cove 获评全澳最宜居社区

每条几百字真实事件描述,带日期 / 影响 / 来源。

### 1.3 `conversation_topics.json`

12 个 hyperlocal 对话话题,LLM `do_something` handler 用来 ground 对话内容,避免空泛 smalltalk:
- `data_centre_proposal` (AirTrunk Mowbray Road 数据中心)
- `school_zone_overcrowding` (Lane Cove West Public School 学区超员)
- `cameraygal_festival` (11月Council节)
- `plaza_parking_rules` (Plaza 1小时停车)
- `epping_road_traffic` (上下班拥堵 144/252/254 公交晚点)
- 等...

每条带 `polarity` (controversial/positive/concerning) + 来源 URL。

### 1.4 `life_history_templates.json`

archetype-grounded 第一人称生平事件模板。每 archetype 5-8 条,LLM 用作 anchor 生成 per-agent life_history。

### 1.5 `social_priors.json`

社交图 prior 规则。比如 same-household = married,同 archetype 几率,邻居距离规则等。让 SocialGraphService 起始就有 "who-knew-whom-on-day-0" 部分图。

---

## 2. 校准 + 验证数据 (data/calibration/, data/face_validity/, data/realism/)

### 2.1 `calibration/abs_census_lanecove_2021.json`

ABS 2021 census Lane Cove SA2 (代码 SAL12275/12276) 数据,含 distributions for age/income/occupation/household 等。Population 生成的 ground truth。

### 2.2 `calibration/calibration_report.json` + `stereotype_audit_report.json` + `face_validity_report.json`

各种校准检查报告。

### 2.3 `face_validity/narratives.json`

agent 行为叙事样本,供 Prolific user study。

### 2.4 `face_validity/prolific_questions.md`

Prolific 用户研究问卷。

### 2.5 `realism/baseline_metrics.json`

baseline 真实度指标。

---

## 3. Atlas 地图数据

### 3.1 `lanecove_atlas.json` (12.9 MB) — 主参考

**top-level**: `id, name, bounds_min, bounds_max, buildings, outdoor_areas, connections, doors, borders`

- **5,722 buildings** · 每个有: id, name, polygon.vertices (atlas-local x/y), building_type, osm_tags, description, floors, exterior_material, entrance_coord, rooms, active_hours, typical_sounds, typical_smells, affordances, entry_signals, capacity
- **4,257 outdoor_areas** · 类型分布: street(4045) / playground(146) / park(64) / garden(2)
- **connections** · location_id pairs 表示连通
- **doors** · 门定义
- **borders** · 边界

坐标系: atlas-local meters (中心为 0,0,可用 `lanecove_proj_center.json` 的 AEQD 投影转 lat/lon)

### 3.2 `lanecove_enriched.geojson` (8.9 MB) + `lanecove_osm.geojson` (3.6 MB)

原始 OSM + 富化后 GeoJSON,主要给 cartography 模块用。

### 3.3 `overture_buildings.geojson` (3.8 MB) + `overture_places.geojson` (1.9 MB)

Overture Maps 数据,补充 building footprints + POI 标签。

### 3.4 `lanecove_proj_center.json`

AEQD 投影中心(lat/lon)和米转换参数。

---

## 4. Population Cache

### 4.1 `data/population_cache/v1/*.json`

10 个 hash-named JSON 文件 · 每个文件是一组 generation 参数下的 profiles cache (1000 个 agent profile)

文件结构:
```json
{
  "schema_version": 1,
  "key_inputs": {"seed": 43, ...},
  "profiles": [...1000 agents]
}
```

每 agent profile:
```python
{
  "agent_id": "a_43_0405",
  "name": "agent_405",
  "age": 75, "occupation": "retired",
  "household": "family_with_kids", "household_role": "parent",
  "home_location": "building_2022",
  "workplace": null,
  "walking_speed_m_per_min": 280.0,
  "prefer_driving": false,
  "household_id": "...",
  "personality": {
    "openness": 0.52, "conscientiousness": 0.21, "extraversion": 0.39,
    "agreeableness": 0.70, "neuroticism": 0.83,
    "curiosity": 0.47, "routine_adherence": 0.28, "risk_tolerance": 0.48
  },
  "preferred_social_size": 2,
  "interests": [],
  "languages": ["other"],
  "wake_time": "7:00", "sleep_time": "23:00",
  "ethnicity_group": "other",
  "migration_tenure_years": null,
  "housing_tenure": "renter",
  "income_tier": "low",
  "is_protagonist": true|false,
  "base_model": "sonnet|haiku|nano",
  "identity_text": "...一段角色背景描述",     # ← LLM 预生成
  "plan_text": "...日常计划描述"               # ← LLM 预生成
}
```

### 4.2 `data/setup_content_cache/seed_{42-51,999}.json`

每 seed 一个 (~6 MB) · 预生成的 life_history + identity_text 缓存,避免每次 run 都跑 LLM。

字段: `schema_version, seed, generated_at, generator, life_history, identity_text, failed_protag`

`life_history` 是 dict: agent_id → list[20 个生平事件 dict] · 每事件:
- event_id (lh_lh_{agent_id}_00 to 19)
- title (例: "卖掉Greenwich老房那天")
- text (~200 字第一人称叙事)
- year_estimate
- location_id (例: "Burns Bay Road")
- importance (0-1)
- kind: "life_history"

`identity_text` 是 dict: agent_id → 字符串 (一段角色简介)

---

## 5. Experiments 目录

### 5.1 目录命名规则
`{timestamp}_publishable_v{n}_{purpose}_seed{N}[_BACKUP_{ts}_{tag}]`

例:
- `20260521_185100_publishable_v6_day4to13_fork_seed43` — seed 43 主 run (day 4-13)
- `20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245` — 上面的 BACKUP 副本(供分析,主目录会被新 run 覆盖)
- `20260521_132618_publishable_v5_baseline_prefix_seed43` — seed 43 day 0-3 baseline-prefix run(separately)
- `20260522_212423_publishable_v7_day4to13_fork_seed45_BACKUP_20260523_022549_FULL_ALLVARIANTS` — seed 45,全 4 variant

### 5.2 当前可用 seed × variant 全表

| seed | day 0-3 (baseline_prefix) | day 4-13 (fork) baseline | hyperlocal_push | global_distraction | phone_friction |
|---|---|---|---|---|---|
| 43 | ✓ v5 | ✓ v6 BACKUP | ✓ v6 BACKUP | ✓ v6 | ✓ v6 |
| 44 | ✓ v7 | ✓ v7 BACKUP | ✓ v7 BACKUP | ✓ v7 | ✓ v7 |
| 45 | ✓ v7 | ✓ v7 BACKUP | ✓ v7 BACKUP | ✓ v7 | ✓ v7 |
| 46 | ✓ v7 (baseline only) | — | — | — | — |

**总数**: 3 seeds × 4 variants × 14 days 完整数据 + 1 个备用 seed 46 baseline。

### 5.3 每个 variant 目录的内容

```
variant_hyperlocal_push/
├── seed_43_pid69976_tick4020.snapshot.json       (523 MB) 完整仿真状态
├── seed_43_positions.json                        (41 MB)  位置变化日志
├── seed_43.json                                  (1.5 MB) per-day summary + run_metrics
├── seed_43.wal.jsonl                             (681 KB) tick-level metrics
├── seed_43.events.jsonl                          (323 KB) 运行时事件
├── seed_43.memstat.jsonl                         (223 KB) 内存采样
├── seed_43.llm.jsonl                             (136 KB) LLM call telemetry
├── aggregate.json                                (14 KB)  variant-level aggregate
├── seed_43_day{0..13}.summary.json               (~500 B 各) 单日 summary
└── .snapshot_backup_{ts}/                        中间快照备份
```

### 5.4 多个 snapshot 时间点(v4 实验)

`20260521_043528_publishable_v4_post_resume_fix_seed43/variant_hyperlocal_push/` 有:
- `seed_43_pid87617_tick300.snapshot.json` (657 MB)
- `seed_43_pid87617_tick_final.snapshot.json` (657 MB)

**意味着**:某些 experiments 有 mid-run + final 2 个 snapshot,可以做 BEFORE / AFTER snapshot 对比。

---

## 6. Snapshot.json 完整结构详解 (主参考: 523 MB)

18 个 top-level keys。用 `ijson` 流式读避免 OOM。

### 6.1 元数据(简单字段)
```
schema_version: 3
seed: 43
tick_index: 4020       # global tick 累计
day_index: 13
simulated_time: "2026-05-05T23:00:00"
tick_index_in_day: 276
start_date_anchor_iso: "2026-04-22"
provider: "deepseek"
created_at: "2026-05-21T19:17:06"
```

### 6.2 `ledger_state` (19 子 keys)

```
current_time, time_of_day, weather,
entities,                           # ← 1000 agents 当前位置 + arrived_at
items, container_states, door_states,
dynamic_connections, border_overrides,
evidence_blueprints (空), details (空), clues (空),
discovered_clue_ids, plot_tags (空),
explored_locations,                 # ← per-agent 探索过的全部 location_id list
location_traces (空), agent_knowledge_maps (空),
events,                             # ← 最近 100 个世界事件
notifications                       # ← 13396 条全部 push 投递事件
```

#### `ledger_state.entities.{agent_id}` (1000 个)
```python
{
  'entity_id': 'a_43_0001',
  'location_id': 'anytime_fitness_australia',
  'position': {'x': 324.48, 'y': -627.47},
  'activity': null, 'facing': null,
  'arrived_at': '2026-05-05T00:20:00'
}
```

#### `ledger_state.explored_locations.{agent_id}` (955 agent)
list of location_id (每个 agent 14 天里走过的所有地方,通常几十到几百个)

#### `ledger_state.events` (最近 100 条)
```python
{'type': 'location_explored', 'time': '2026-05-05T21:00:00',
 'entity_id': 'a_43_0758', 'location_id': 'road_2690_seg_3'}
```

#### `ledger_state.notifications` (13396 条 push 投递事件)
```python
{
  'event_type': 'notification_received',
  'timestamp': '2026-04-26T00:00:00',
  'location_id': 'rv_256',           # 收到时 agent 所在
  'actor_id': null,
  'target_id': 'a_43_0001',
  'properties': {
    'feed_item_id': 'hyperlocal_push_43_4_0_a_43_0001',
    'recipient_entity_id': 'a_43_0001',
    'origin_hack_id': 'hyperlocal_push'
  },
  'audible_range': 0.0, 'visible_range': 0.0,
  'source_action': 'inject_feed_item',
  'description': '...'
}
```

### 6.3 `agent_runtime_states.{agent_id}` (1000 个)

```python
{
  'agent_id': 'a_43_0405',
  'current_location': 'shinnyo_australia',
  'plan': {                                  # 当前 plan
    'agent_id': 'a_43_0405',
    'date': '2026-05-05',
    'steps': [{
      'time': '13:30',
      'action': 'move',                      # move/stay/wait
      'destination': 'shinnyo_australia',
      'activity': '走向推荐地点 shinnyo_australia',
      'duration_minutes': 45,
      'reason': '被 hyperlocal 推送吸引',
      'social_intent': 'open_to_chat'
    }],
    'current_step_index': 0
  },
  'movement': {
    'queue': [], 'moving': False,
    'in_flight_route_remaining': [],
    'in_flight_target': None
  },
  'ai_town': {
    'pending_operation': None,
    'current_dialogue_id': 'd_a_43_0405_agent_15_137',
    'to_remember': None,
    'last_dialogue_ended_tick': 258,
    'last_op_kind': 'do_something',
    'use_aitown_decision_tree': True,
    'invite_accept_probability': Decimal('0.8'),
    'op_id_counter': 18
  },
  'hints': {
    'nearby_hint': [                          # 此刻视线内 agents
      {'agent_id': 'a_43_0001', 'name': 'agent_1', 'is_familiar': True}
    ],
    'candidate_destinations_hint': [...],     # 系统提示的 10 个候选去处
    'recent_memory_hint': [                   # 最近 5 条记忆摘要
      'ran into a_43_0001 at shinnyo_australia'
    ]
  },
  'enable_replan_log': False,
  'invite_rng_state': [...]                   # RNG 状态
}
```

### 6.4 `memory_store_state` (9 子 keys)

```
agent_events,                        # 1000 个 agent · 每人 700-1500 events
consumed_feed_item_ids,              # 1000 个 agent · 每人 实际"读"过的 push id 列表
event_counter,
replan_count_today,                  # 264 agent 有今天 replan 计数
replan_no_op_count_today (空),
last_day_index,
last_reflection_time,                # 500 agent 上次 reflection 时刻
rng_state, noticing_seed
```

#### `memory_store_state.agent_events.{agent_id}` (per-agent ~700-1500 events)

**6 种 kind** (Mary a_43_0405 的统计):
- `shared_memory` (12) · importance 0.9 · 城市共享记忆(从 shared_memories.json 注入)
- `life_history` (20) · importance ~0.88 · 个人生平细节(从 setup_content_cache 注入)
- `reflection` (36) · importance ~0.55 · LLM 实时生成的对自己行为模式的觉察
- `notification` (30) · importance 0.6 · 收到的 push 文本
- `encounter` (467) · importance 0.5 · 每次 ran into 谁 at 哪
- `action` (565) · importance 0.3 · 每次 intent succeeded/failed

每事件字段:
```python
{
  'event_id': 'ev_a_43_0405_287_1416367',
  'agent_id': 'a_43_0405',
  'tick': 287,
  'simulated_time': '2026-04-22T23:55:00',
  'kind': 'reflection',
  'content': '...',
  'importance': 0.55,
  'location_id': null,
  'related_agents': [...]   # 仅 encounter 有
}
```

#### `memory_store_state.consumed_feed_item_ids.{agent_id}`

list of feed_item_id · 表示 agent 实际"消费"了这些推送(可能 30 条收到 → 24 条实际 consume)

#### `memory_store_state.replan_count_today.{agent_id}`

int · 今天 replan 次数

### 6.5 `attention_service_state` (10 子 keys)

```
profiles,                  # ← 1000 agent 手机使用画像
feed_index,                # ← ~30000 条 push 内容库
feed_bias_suppression,     # 全局 0.2
delivery_log,              # 13396 条 push 投递记录
consumed,                  # 实际 consume 状态
phone_attention,           # per-agent 手机注意力分配
phone_attention_baseline,  # baseline 对照
personality_openness,      # 用于个性化推送的开放度
notifications_today,
rng_state
```

#### `attention_service_state.profiles.{agent_id}`
```python
{
  'daily_screen_hours': 4.92,
  'feed_bias': 'global',                    # global/local/...
  'headphones_hours': 1.39,
  'notification_responsiveness': 0.54,
  'primary_apps': ['xhs', 'wechat', 'instagram']  # ← 主用 APP!
}
```

#### `attention_service_state.feed_index.{feed_item_id}`
```python
{
  'feed_item_id': 'hyperlocal_push_43_4_0_a_43_0405',
  'content': 'shinnyo_australia 周六上午 10 点儿童活动——本街妈妈群组织...',
  'source': 'local_news',
  'hyperlocal_radius': 1000.0,
  'category': 'event',
  'urgency': 0.39,
  'created_at': '2026-04-26T09:00:00',
  'origin_hack_id': 'hyperlocal_push'
}
```

ID 格式: `hyperlocal_push_{seed}_{day}_{slot}_{recipient_id}` · seed 43,day 4 (第一推送日),slot 0-4(每天 5 条/agent)

#### `attention_service_state.delivery_log`
13396 条 · 每条:
```python
{
  'feed_item_id': '...',
  'recipient_id': 'a_43_0405',
  'delivered': True|False,
  'delivered_at': '2026-04-26T00:00:00',
  'origin_hack_id': 'hyperlocal_push',
  'suppressed_by_bias': True|False
}
```

### 6.6 `tick_metrics_recorder_state` (2 子 keys)

```
current_day: 13
buckets: {                          # per-day metrics
  '0': {
    'encounter_count_total': 563907,
    'distinct_pairs': [['a_43_0064', 'a_43_0200'], ...]
  },
  ...
}
```

**`distinct_pairs` 是当日所有 unique encounter pair list** · 可重建社交图。

### 6.7 `dialogue_service_state` (7 子 keys)

```
dialogues,                # 213 个 active (含 messages: [])
dialogue_summaries,       # 752 个完成 dialogue 元数据
active_by_agent,
last_ended_at, bridged,
message_counter, rng_state
```

#### `dialogue_service_state.dialogues.{dialogue_id}` (active)
```python
{
  'dialogue_id': 'd_a_43_0742_agent_886_235',
  'initiator_id': 'a_43_0742',
  'invitee_id': 'agent_886',
  'target_location_id': 'patchai_thai_restaurant',
  'started_tick': 235,
  'last_message_tick': 235,
  'started_at': '2026-04-22T19:35:00',
  'member_status': {'a_43_0742': 'walking_over', 'agent_886': 'invited'},
  'messages': [],                  # ⚠️ 空 — 无逐句文本
  'ended_tick': None,
  'end_reason': None
}
```

#### `dialogue_service_state.dialogue_summaries.{dialogue_id}` (752 个完成)
```python
{
  'dialogue_id': 'd_a_43_0001_a_43_0102_0',
  'initiator_id': 'a_43_0001',
  'invitee_id': 'a_43_0102',
  'target_location_id': 'carranya_road_seg_1_1',
  'started_tick': 0,            # ⚠️ day-local tick, 不带 day 标签
  'ended_tick': 5,
  'message_count': 5,
  'end_reason': 'leave'
}
```

ID 格式: `d_{initiator_id}_{invitee_id}_{started_tick}`

### 6.8 `conversation_service_state` (5 子 keys)

```
infos,             # 每段对话的第一人称 LLM 生成总结
known,             # per-agent 知道的 info_id list + 学到 tick
known_by_info,     # per-info 谁知道(包括转述)
share_count,       # per-info 被分享次数
rng_state
```

#### `conversation_service_state.infos.{info_id}` (~752 条)

ID 格式: `info_dlg_{dialogue_id}`

```python
{
  'info_id': 'info_dlg_d_a_43_0012_a_43_0055_0',
  'content': '嗯,刚跟老邻居a_43_0055聊完...(几百字第一人称叙事)',
  'category': 'dialogue',
  'salience': 0.6,
  'origin_tick': 5,
  'origin_agent_id': 'a_43_0012'
}
```

**`content` 是 LLM 实时生成的几百字第一人称叙事 · 包括分享内容、对方反应、未来约定、个人感受。**

#### `conversation_service_state.known.{agent_id}`
```python
{
  'info_dlg_X': {'first_learned_tick': 5, 'hops_at_learn': 0},   # hops=0 直接参与
  'info_dlg_Y': {'first_learned_tick': 111, 'hops_at_learn': 7}  # hops=7 转述 7 次才听说
}
```

#### `conversation_service_state.known_by_info.{info_id}`
list of agent_id · 表示知道这条 info 的所有 agent

#### `conversation_service_state.share_count.{info_id}`
int · 被分享了几次(同条 info 在 known_by_info 里可能近 1000 个 agent)

### 6.9 杂项
- `rng_state` (空 dict)
- `pending_ops_meta` (空 dict)

---

## 7. positions.json (40-70 MB / variant)

```python
{
  'schema': 'position_trace_v1',
  'n_agents': 1000,
  'n_changes': 450025,
  'changes': [
    {'tick': 253, 'day': 7, 'agent_id': 'a_43_0001', 'location_id': 'road_4896_seg_1'},
    ...
  ]
}
```

**Tick semantics**:
- `tick` 是 **day-local tick** (0-287, 5 min/tick = 288 ticks/day)
- `day` 是 calendar day index (0-13 for 14-day run)
- 只记录 location_id **CHANGE** 事件
- 一个 tick 可有多条(agent 跨多个相邻路段)
- ⚠️ 仿真"日开始"机制可能把所有移动压在 day boundary,wall-clock vs tick 不严格对应

---

## 8. seed_{N}.json (1.5 MB)

```python
{
  'multi_day_result': {
    'per_day_summaries': [...14 个],
    'total_ticks': 3814,
    'total_encounters': 37956778,
    'seed': 43,
    'started_at': '...', 'ended_at': '...',
    'metadata': {...}
  },
  'run_metrics': {
    'seed': 43, 'variant_name': 'hyperlocal_push', 'num_days': 14,
    'per_day': [...14 个,每个含 encounter_count / distinct_pairs / move_success / notifications / location_dwell_ticks],
    'trajectory_deviation_m': {...},
    'trajectory_deviation_m_all': {...},
    'encounter_stats': {...},
    'space_activation': {...},
    'feed_stats': {...},
    'attention_allocation_ratio': {...},
    'weak_tie_formation_count': {...},
    'info_propagation_hops': {...},
    'reflection_count': {...},
    'dialogue_count': {...},
    'dialogue_avg_length': {...},
    'op_timeout_count': {...},
    'cost_breakdown': {...},
    'extensions': {...}
  }
}
```

**`run_metrics.per_day[].location_dwell_ticks`** 是 dict: location_id → 该位置该日累计 dwell ticks(全 agent 加和)

---

## 9. 各种 jsonl 文件

### 9.1 `seed_43.wal.jsonl` (681 KB)

Tick-level metrics · 每 tick 一条:
```python
{
  'tick_index': 1141,            # global tick (与 positions 的 day-local 不同)
  'day_index': 3,
  'simulated_time': '2026-04-25T23:05:00',
  'wall_clock': '2026-05-21T08:57:05.053066',
  'commits_succeeded': 1000,
  'commits_failed': 0,
  'encounter_count': 1405,
  'snapshot_path': null
}
```

### 9.2 `seed_43.events.jsonl` (323 KB)

Runtime 系统事件 · **不含 agent-level 内容**:
```python
{
  'v': 1,
  'ts_iso': '...',
  'kind': 'PHASE',
  'phase': 'PROCESS_START|SETUP_START|SNAPSHOT_LOAD_START|TICK_LOOP_START|DAY_START|DAY_END|EXIT',
  'rss_mb': 6098,
  'pid': 31757, 'python': '3.11.15'
}
```

### 9.3 `seed_43.llm.jsonl` (136 KB)

LLM call telemetry (sample 1%) · **⚠️ `agent_id` 字段 null** — 不能关联到具体 agent:
```python
{
  'v': 1, 'ts_iso': '...',
  'tier': 'nano|haiku|sonnet',
  'provider': 'deepseek',
  'model': 'deepseek-v4-flash',
  'kind': 'unknown|do_something|reflect|score_importance|...',
  'agent_id': null,
  'key_id': 1, 'attempt': 0, 'max_attempts': 2,
  'latency_ms': 805,
  'status': 'success|error',
  'exc_class': null,
  'prompt_chars': null, 'response_chars': null
}
```

### 9.4 `seed_43.memstat.jsonl` (223 KB)

每 N tick 一条内存采样:
```python
{
  'tick': ..., 'rss_mb': ..., 'cpu_percent': ...,
  'gc_collections': [...],
  'memory_store_event_count': ...,
  'dialogue_service_active_count': ...,
  ...
}
```

---

## 10. day_summary.json (~500 B / 文件)

每天一个 (`seed_43_day{0..13}.summary.json`):
```python
{
  'day_index': 6,
  'simulated_date': '2026-04-28',
  'tick_count': 71,                          # 当天处理了多少 tick(可能 < 288 if resume)
  'commit_succeeded': 70877,
  'commit_failed': 123,
  'encounter_count': 683727,
  'llm_fallback_pct': 0.009,
  'llm_total_samples': 2213,
  'all_keys_open_count': 0,
  'rss_mb': 423.84, 'vms_mb': 450435.91,
  'memory_store_event_count': 731355,
  'dialogue_count': 867,
  'gc_collections': [4, 7, 1251],
  'tick_latency_ms_p50': 7792, 'tick_latency_ms_p95': 15453, 'tick_latency_ms_max': 15581,
  'evicted_encounter_count': 0,
  'daily_summary_batch': {}
}
```

---

## 11. aggregate.json (14 KB / variant)

Variant-level aggregate · 跨 seed metrics:
```python
{
  'variant_name': 'hyperlocal_push',
  'variant_metadata': {...},
  'seed_count': 1, 'seeds': [43],
  'per_metric_stats': {...},
  'per_day_time_series': {...},
  'degraded_preliminary_not_publishable': false,
  'max_llm_fallback_pct': ..., 'avg_llm_fallback_pct': ...,
  'high_fallback_warning': false
}
```

---

## 12. data/analysis/2026-05-23_paper_exploration/ — 后处理分析

30 个子目录(标 A-Z + DEEP_MINING + FANCIER)+ 顶层文件。

### 顶层
- `MORNING_SUMMARY.md` · 19 个分析的总结报告
- `PAPER_DRAFT_OUTLINE.md` · 论文 outline
- `HERO_FIGURE.png` · 4-panel composite
- `index.html` · 可视化总览
- `figures/` · 14 个 PNG figures

### 主分析子目录(每个含 json data + summary.md + 可选 png)

| 目录 | 主题 | 关键文件 |
|---|---|---|
| `A_poi_activation` | 各 variant POI 激活热图 | activation_per_location.json + 4 个 heatmap.png |
| `B_temporal_curves` | 14 天 onset/habituation/post-revert | per_day_series.json + temporal_curves.png |
| `C_responder_profile` | 谁是响应者 12% | agents_{baseline,hp,gd,pf}.json + responder_profile_summary.json + deviation_histogram.png + extraversion_vs_deviation.png + responder_rates_by_demo.md |
| `D_walking_footprint` | 每 agent 步行距离 | walking_per_day.json |
| `E_location_diversity` | 每 agent 去多少不同地方 | diversity.json |
| `F_encounter_locations` | encounter 发生在哪 | encounter_locations.json |
| `G_habit_stickiness` | 习惯黏性 | stickiness.json |
| `H_personality` | personality 相关性 | personality_correlations.json |
| `I_proximity_to_targets` | 距离 push target 的影响 | proximity.json |
| `J_novelty_exploration` | 新发现地点数 | novelty.json |
| `K_cost_efficiency` | 每米/每邻居成本 | cost_efficiency.json |
| `L_spillover` | 邻居响应溢出 | spillover.json |
| `M_weekday_weekend` | 工作日 vs 周末 | weekday_weekend.json |
| `N_methods_variance` | seed 间方差 | methods.json |
| `O_time_of_day` | 时段分布 | hour_of_day.json + time_of_day.png |
| `P_tie_strength` | 强/弱关系数 | tie_series.json + tie_strength_curves.png |
| `Q_encounter_diversity` | encounter 多样性 | diversity.json |
| `R_info_propagation` | 信息扩散跳数 | info.json |
| `S_replan_dynamics` | replan 动态 | replan.json + replan_per_day.png |
| `T_case_studies` | 个案研究 | case_studies.json |
| `U_cross_cohort` | 跨人群 demo diversity | demo_diversity_per_loc.json |
| `V_repeat_vs_unique` | 重复 vs 新相遇 | repeats.json |
| `W_deeper_stickiness` | 更深黏性 | stickiness_deep.json |
| `X_workplace_pull` | 工作地点拉力 | workplace.json |
| `Y_encounter_gini` | encounter Gini 系数 | gini.json |
| `Z_peak_hour` | 高峰时段 day-of-week | peak_dow.json |
| `AA_encounter_dialogue` | encounter 转 dialogue 转化率 | encounter_dialogue.json |
| `DEEP_MINING` | 6 个深度分析 | cross_demo_ties / distance_decay / effect_sizes / responder_churn / specific_pois / spillover_timing |
| `FANCIER` | 4 个高级 finding | anchor_pois / cross_occupation / hub_emergence / responder_clustering |

### 分析层缓存
- `data/analysis/heatmap_cache_f1.json` (180 KB) · 每 location BL/HP 独立访客数
- `data/analysis/trajectory_cache_f1.json` (2-12 MB,可变) · 抽样 trajectory
- `data/analysis/case_studies/` · 我新建的 case study 缓存

---

## 13. 历史归档 (data/experiments_archive_pre_2026_05_21/)

24 个早期 experiments,大部分较小规模(smoke / 100 agent / 1 day 等)。结构同 experiments/ 但更早期。

---

## 14. exports/ (导出产物)

- `evidence_report.html` · 案件视角的证据报告(早期 Project Brief 视角)
- `inspector-payload.json` · Inspector UI 数据
- `inspector-smoke.json` · smoke 测试数据

---

## 15. 数据缺口(我们没有的)

| 想要的 | 实际状态 |
|---|---|
| dialogue 的逐句 message 文本 | dialogues.messages = [] · 仅有 first-person 总结 |
| 多个时间点的 snapshot 对比(主 v6 BACKUP) | 只有 day 13 末一个 snapshot |
| 准确的 wall-clock 时间 vs simulation tick 对照 | tick semantic 有歧义(day-local 在 positions / global 在 wal) |
| LLM 的具体 prompt/response 文本 | llm.jsonl 只有 telemetry,agent_id null |
| BL variant 的 snapshot.json(523MB 同样大) | 存在但未抽过,可以做 BL vs HP per-agent 对比 |
| GD variant + PF variant 的 snapshot.json | 同上 |
| 实时位置(每 tick 都有,不只 change) | 只能从 changes 重建 |

---

## 16. 关键 ID 命名规则

| ID 格式 | 含义 | 示例 |
|---|---|---|
| `a_{seed}_{NNNN}` | agent | a_43_0405 |
| `building_{N}` | atlas 建筑 | building_2022 |
| `road_{N}_seg_{M}` | 路段 | road_4896_seg_2 |
| `{name}_road_seg_{M}_{K}` | 命名街道路段 | mowbray_road_seg_3_1 |
| `area_{N}` | 区域 | area_117 |
| `rv_{N}` | 居住单元 | rv_222 |
| `d_{init}_{invitee}_{tick}` | dialogue id | d_a_43_0012_a_43_0055_0 |
| `info_dlg_{dialogue_id}` | dialogue info id | info_dlg_d_a_43_0012_a_43_0055_0 |
| `hyperlocal_push_{seed}_{day}_{slot}_{recipient}` | push id | hyperlocal_push_43_4_0_a_43_0405 |
| `ev_{agent_id}_{tick}_{counter}` | 内存事件 id | ev_a_43_0405_287_1416367 |
| `lh_lh_{agent_id}_{NN}` | life_history 事件 id | lh_lh_a_43_0405_00 |
| `shared_lc_mem_{NNN}_{agent_id}` | shared memory id | shared_lc_mem_004_a_43_0405 |

---

## 17. 数据规模总览

| 数据 | 单 variant | 4 variants × 3 seeds 总 |
|---|---|---|
| snapshot.json | 523 MB | ~12 个 × 500MB = ~6 GB |
| positions.json | 40-70 MB | ~840 MB |
| seed_{N}.json | 1.5 MB | ~18 MB |
| llm.jsonl | 136 KB | ~1.6 MB |
| dialogues (in snapshot) | 752 完成 + 213 active | ~9000 跨全部 |
| agent_events (in snapshot) | 1.13 M (全 agent 累计) | ~13.6 M |
| push 投递事件 (notifications) | 13396 | ~160K |
| 真实第一人称对话总结 (infos) | ~752 | ~9000 |

---

## 18. 数据访问代码片段

### 读 snapshot top-level key
```python
import ijson
with open(SNAP) as f:
    for item in ijson.items(f, "memory_store_state.agent_events.a_43_0405"):
        # item 是 list of events for Mary
        break
```

### 读 push delivery
```python
with open(SNAP) as f:
    for entry in ijson.items(f, "attention_service_state.delivery_log.item"):
        if entry["recipient_id"] == "a_43_0405":
            ...
```

### 读 push 内容
```python
with open(SNAP) as f:
    for fid, item in ijson.kvitems(f, "attention_service_state.feed_index"):
        if fid in needed_ids:
            ...
```

### 读 dialogue 内容
```python
with open(SNAP) as f:
    for iid, info in ijson.kvitems(f, "conversation_service_state.infos"):
        if "a_43_0012" in iid:
            print(info["content"])
```

### 流式读 positions.json (避免 OOM)
```python
import json
d = json.load(open("seed_43_positions.json"))   # 41 MB OK to load
mary_changes = [c for c in d["changes"] if c["agent_id"] == "a_43_0405"]
```

---

## 19. 文档/代码相关

- `synthetic_socio_wind_tunnel/` · 核心代码包(atlas / ledger / engine / perception / cartography)
- `tools/` · 100+ 工具脚本(run_variant_suite / preflight / analyze_* / build_findings_* etc.)
- `tools/case_studies/` · 我建的 case study 工具
- `openspec/specs/` + `openspec/changes/` · 规范文档(`run-resilience`, `tick-level-resume`, etc)
- `docs/agent_system/` · agent 系统设计文档
- `docs/map_pipeline/` · 地图构建文档
- `docs/项目实验结果.html` · 8 个 finding 主报告
- `docs/项目产出物.html` · 产出物总览
- `docs/项目Brief.md` · 项目方案
- `docs/case_studies/` · 我建的案例研究 + 本 inventory

---

## END · 现在可基于此规划任何深度产出物
