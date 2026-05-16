## ADDED Requirements

### Requirement: SimulationContentCache 数据结构

`SimulationContentCache` SHALL 是 Pydantic frozen 模型，位于
`synthetic_socio_wind_tunnel.data_loader.setup_cache`，作为 setup phase
LLM 内容的持久化对象。字段：

- `schema_version: str = "1"`（当前；版本不匹配 SHALL 视为 cache miss）
- `seed: int`
- `generated_at: datetime`
- `generator: dict[str, Any]`（记录 tier / model / n_records_per_protag /
  prompt_version / concurrency 等生成时元数据，用于审计）
- `life_history: dict[str, list[dict[str, Any]]]`（agent_id → list of
  LifeHistoryRecord dict，每个含 record_id / title / content / years_ago /
  location_hint / importance / tags）
- `identity_text: dict[str, str]`（agent_id → ~200 字第一人称自我介绍）
- `failed_protag: list[str]`（生成失败、走 fallback 模板的 agent_id 列表；
  审计用）

#### Scenario: 默认构造 + 字段完整
- **WHEN** 用合法参数构造 `SimulationContentCache(seed=42, generated_at=...,
  generator={...}, life_history={}, identity_text={})`
- **THEN** 字段 SHALL 全部可读；`schema_version == "1"`；`model_dump(mode="json")`
  产 JSON-safe dict；`failed_protag` 默认空 list

#### Scenario: frozen 不可变
- **WHEN** 构造后尝试 `cache.seed = 99`
- **THEN** SHALL raise（Pydantic frozen 行为）


### Requirement: load_setup_cache 读取 + schema 校验

`load_setup_cache` SHALL 提供 per-seed cache 的读取与 schema_version 校验，
签名 `load_setup_cache(seed: int, *, cache_dir: Path | None = None) ->
SimulationContentCache | None`，具体行为：

- 路径为 `<cache_dir>/seed_<seed>.json`（默认 cache_dir 是
  `<repo_root>/data/setup_content_cache/`）
- 文件不存在 → 返回 None
- 文件存在 + `schema_version` 匹配当前（默认 `"1"`）→ 反序列化为
  `SimulationContentCache` 返回
- 文件存在 + `schema_version` 不匹配 → log warning + 返回 None（视为 miss）
- 文件存在 + JSON 解析失败 → log warning + 返回 None（视为 miss）

调用方据返回值决定走 cache HIT（直接用）还是 cache MISS（在线生成 + 写 cache）。

#### Scenario: cache HIT
- **WHEN** `data/setup_content_cache/seed_42.json` 存在 + schema_version == "1"
- **THEN** `load_setup_cache(42)` SHALL 返回 SimulationContentCache 实例；
  `life_history` / `identity_text` 字段非空

#### Scenario: cache 不存在 → MISS
- **WHEN** `seed_99.json` 不存在
- **THEN** `load_setup_cache(99)` SHALL 返回 None；不抛异常

#### Scenario: schema 不兼容 → MISS + warning
- **WHEN** `seed_42.json` 存在但 `schema_version == "99"`
- **THEN** `load_setup_cache(42)` SHALL 返回 None + log warning 含"schema
  mismatch"; 不抛异常


### Requirement: save_setup_cache 原子写盘

`save_setup_cache` SHALL 提供原子写盘的 cache 持久化，签名
`save_setup_cache(seed: int, cache: SimulationContentCache, *,
cache_dir: Path | None = None) -> Path`，具体行为：

- 用 `.tmp` + `os.replace` 模式原子写盘（与 `run-resilience` /
  `tick-level-resume` 的 atomic write 模式一致）
- 返回最终路径
- SIGKILL 期间目标路径 SHALL 要么不存在、要么是合法 JSON
- 写盘失败 SHALL raise OSError；不静默吞错

#### Scenario: 原子写盘 round-trip
- **WHEN** 构造 cache + `save_setup_cache(42, cache)` + `load_setup_cache(42)`
- **THEN** 加载的 cache `model_dump()` SHALL 与原 cache 字段一致

#### Scenario: 写盘失败抛 OSError
- **WHEN** cache_dir 不可写（模拟磁盘满）
- **THEN** `save_setup_cache(...)` SHALL raise OSError


### Requirement: is_cache_complete 完整性校验

`is_cache_complete` SHALL 校验 cache 是否完整覆盖当前 profile set 中所有
protagonist，签名 `is_cache_complete(cache: SimulationContentCache,
profiles: list) -> bool`，具体规则：

1. 计算 `expected_protag_ids = {p.agent_id for p in profiles if p.is_protagonist}`
2. 计算 `cached_life_ids = set(cache.life_history.keys())`
3. 计算 `cached_identity_ids = set(cache.identity_text.keys())`
4. 返回 `expected_protag_ids ⊆ cached_life_ids AND expected_protag_ids ⊆
   cached_identity_ids`

调用方据此决定 cache HIT 是否完整。Partial coverage 也视为 MISS（让 prewarm
脚本补齐缺失的部分；prewarm 主路径 SHALL 优先补齐再 save）。

#### Scenario: 完整 cache → True
- **WHEN** cache 覆盖所有 protag 的 life_history + identity_text
- **THEN** `is_cache_complete(cache, profiles)` SHALL == True

#### Scenario: 缺少 life_history → False
- **WHEN** cache 含 500 个 identity_text 但只有 499 个 life_history
- **THEN** `is_cache_complete(cache, profiles)` SHALL == False


### Requirement: prewarm_setup_content.py CLI

`tools/prewarm_setup_content.py` SHALL 是 publishable run 之前**离线慢速预热
setup 内容**的 CLI 入口。argparse 支持以下 flag：

| flag | 默认 | 说明 |
|---|---|---|
| `--seeds` | `42-56` | seed 范围（comma-sep 或 hyphen-range） |
| `--n-protagonists` | 500 | 每 seed 的 protag 数（与 publishable 一致） |
| `--n-records-per-protag` | 20 | 每 protag 的 life_history 条数 |
| `--concurrency` | 4 | 单 seed 内并发 LLM call 数 |
| `--batch-sleep` | 0.1 | 每 batch 之间 sleep（秒） |
| `--tier` | `sonnet` | LLM tier (`sonnet` 默认 / `haiku`) |
| `--provider` | `deepseek` | LLM provider |
| `--force` | False | 已有 cache SHALL 仍重生 |
| `--cache-dir` | `data/setup_content_cache/` | cache 目录 |

退出码：

- 0：所有 seed cache 已落地（含 HIT skipped + 新生）
- 1：至少一个 seed 生成失败（含 fallback 模板写入但生成 < N 个）
- 2：CLI 参数错 / 环境错（API key 缺失等）

CLI 进度 SHALL stderr 打印：

```
[prewarm] seed=42 progress=350/500  (3 retries, 0 fallbacks)
[prewarm] seed=42 done in 184.3s  cache=data/setup_content_cache/seed_42.json
[prewarm] seed=43 SKIPPED (cache HIT)
```

#### Scenario: prewarm 全 seed 范围
- **WHEN** `python tools/prewarm_setup_content.py --seeds 42-44 --tier haiku
  --concurrency 1`（用 haiku 跑得快、做测试）
- **THEN** 3 个 `seed_{42..44}.json` SHALL 落地；CLI 退出码 0；stderr 含每
  seed 的 progress 行

#### Scenario: cache HIT 跳过
- **WHEN** `seed_42.json` 已存在 + 调用 `prewarm --seeds 42`（无 `--force`）
- **THEN** SHALL 不调任何 LLM；stderr 含 "SKIPPED (cache HIT)"；退出 0

#### Scenario: --force 强制重生
- **WHEN** `seed_42.json` 存在 + 调用 `prewarm --seeds 42 --force`
- **THEN** SHALL 重新生成 + 覆盖既有 cache 文件


### Requirement: prewarm 并发与 retry 行为

prewarm 脚本 SHALL 按以下并发与 retry 策略执行：

1. 单 seed 内并发 ≤ `concurrency`（默认 4），通过 `asyncio.Semaphore` 限流
2. 每 batch 之间 SHALL sleep `batch_sleep` 秒（默认 0.1）
3. 每个 protag 的 life_history LLM call 失败（JSON parse / API error）SHALL
   retry 最多 2 次（共 3 次尝试），每次 retry 之间 backoff 0.5s
4. 3 次尝试都失败的 protag SHALL fallback 到
   `data/lanecove/life_history_templates.json` 的 archetype-conditioned 模板，
   并把 agent_id 加入 `failed_protag` 列表（写入 cache）
5. identity_text 同样路径（retry × 3，fallback 到 "我是 {profile.name}, {age}
   岁..." 模板）

#### Scenario: JSON parse 失败 → retry → 成功
- **WHEN** mock LLM 第 1 次返回非 JSON、第 2 次返回合法 JSON
- **THEN** prewarm SHALL 在 2 次内成功；`failed_protag` 不含该 agent_id

#### Scenario: 3 次都失败 → fallback
- **WHEN** mock LLM 连续 3 次返回非 JSON
- **THEN** prewarm SHALL fallback 到模板 + 该 agent_id 进 `failed_protag`；
  cache 仍包含该 agent_id 的 life_history（虽然是模板内容）


### Requirement: ABCD 精细化应用到生成路径

`_generate_life_history_for_one` SHALL 支持 ABCD 四项精细化扩展参数（向后
兼容默认值），位于 `synthetic_socio_wind_tunnel.data_loader.lanecove`，新增：

- `n_records: int = 20`（A：默认从 10 升到 20）
- `tier: Literal["sonnet", "haiku"] = "sonnet"`（B：默认走推理 tier）
- `max_retries: int = 2`（C：JSON parse 失败 retry 2 次）
- `prompt_version: str = "v2"`（D：新 prompt 含 home_location +
  life_pattern 全字段 + Lane Cove 地标 list + 显式要求"提及具体地标和时间"）

prompt v2 SHALL 包含以下 placeholder（除原有外）：

- `{home_location}`: profile.home_location
- `{preferred_weekday_park}` / `{preferred_weekday_cafe}` / `{weekend_outing}`
- `{neighborhood_landmarks}`: 静态列表（Plaza、Longueville Rd 等）
- 显式 instruction："故事 SHALL 提及具体地标 + 具体时间（如某年、某季节）"

prompt 模板 SHALL 维护 `_LIFE_HISTORY_PROMPT_TEMPLATES` dict by version；
未知 version SHALL raise `ValueError`。

#### Scenario: 默认参数走 v2 prompt
- **WHEN** `_generate_life_history_for_one(profile, llm_client=...)`（不传
  prompt_version）
- **THEN** 内部 SHALL 用 `_LIFE_HISTORY_PROMPT_TEMPLATES["v2"]`；prompt 字符串
  SHALL 含 `{neighborhood_landmarks}` 替换后的实际 Lane Cove 地标

#### Scenario: 显式指定 v1（向后兼容）
- **WHEN** `_generate_life_history_for_one(profile, prompt_version="v1")`
- **THEN** SHALL 用旧 v1 prompt（不含 landmarks），保持单元测试稳定

#### Scenario: retry 2 次后成功
- **WHEN** mock LLM 第 1/2 次返回非 JSON、第 3 次返回合法 JSON
- **THEN** 函数 SHALL 在 max_retries=2 内成功；返回非空 list[LifeHistoryRecord]

#### Scenario: 未知 prompt_version raise
- **WHEN** `_generate_life_history_for_one(profile, prompt_version="v99")`
- **THEN** SHALL raise `ValueError`


### Requirement: identity_text 生成函数

`_generate_identity_text_for_one` SHALL 是新函数，生成 protag 的第一人称
自我介绍，位于 `synthetic_socio_wind_tunnel.data_loader.lanecove`。

签名：

```python
async def _generate_identity_text_for_one(
    profile,
    *,
    llm_client,
    archetype: ArchetypeRecord | None,
    life_history_snippets: list[str] | None = None,
    tier: Literal["sonnet", "haiku"] = "sonnet",
    max_retries: int = 2,
    max_chars: int = 500,
) -> str:
```

输出 SHALL：

- 单段第一人称中文文本，~150-200 字
- 包含 profile 基本字段（name / age / occupation / household / home_location）
- 风格自然口语（"我是 ..., 30 岁, 住在 ...", "我对 ... 感兴趣"）
- 若 `life_history_snippets` 提供 → 整合 2-3 条 anchor 进自我介绍
- 长度 ≤ `max_chars`，超过 SHALL 截断 + log warning
- LLM 失败 + retry 用尽 → fallback 到模板 `"我是 {name}，{age} 岁，{occupation}，
  住在 Lane Cove。"`

#### Scenario: 默认生成成功
- **WHEN** mock LLM 返回合法 ~150 字字符串
- **THEN** 函数 SHALL 返回该字符串；不截断

#### Scenario: 超长 → 截断 + warning
- **WHEN** mock LLM 返回 1000 字字符串
- **THEN** 函数 SHALL 返回 ≤ 500 字字符串；log warning 含截断信息

#### Scenario: 3 次失败 → fallback 模板
- **WHEN** mock LLM 连续 3 次抛异常
- **THEN** 函数 SHALL 返回非空 fallback 模板字符串；含 profile.name


### Requirement: suite-wiring 集成 _load_or_generate_setup_content

`tools/run_variant_suite.py` SHALL 在 setup phase 用新的统一函数：

```python
async def _load_or_generate_setup_content(
    *,
    seed: int,
    profiles: list,
    llm_client,
    archetypes,
    tier: str = "sonnet",
    n_records_per_protag: int = 20,
    cache_dir: Path | None = None,
) -> tuple[dict[str, list[LifeHistoryRecord]], dict[str, str]]:
    """Returns (life_history_records, identity_texts).
    Cache HIT → 0 LLM call. Cache MISS → online generation + save."""
```

逻辑：

1. 调 `load_setup_cache(seed, cache_dir=cache_dir)`
2. 若返回 cache + `is_cache_complete(cache, profiles)` → 直接用 cache 数据
3. 否则在线生成（含 retry / fallback）+ `save_setup_cache(...)`
4. 返回 `(life_history, identity_text)` 给调用方

调用方（`run_seed_with_metrics`）拿到 `life_history` 后调 `inject_life_history`、
拿到 `identity_text` 后调相应 profile 注入路径。

#### Scenario: cache 完整 → 0 LLM call
- **WHEN** cache 已存在 + 完整覆盖 profiles + 调
  `_load_or_generate_setup_content(seed=42, profiles=..., ...)`
- **THEN** 函数 SHALL 不调任何 LLM；返回 cache 数据；stderr log 含 "cache HIT"

#### Scenario: cache MISS → 在线生成 + 写盘
- **WHEN** cache 不存在 + 调用
- **THEN** 函数 SHALL 调 LLM 生成所有 protag 内容；写入 cache 文件；返回数据


### Requirement: 公共 API re-export

`synthetic_socio_wind_tunnel/__init__.py` SHALL re-export 以下类型 / 函数：

- `SimulationContentCache`
- `load_setup_cache` / `save_setup_cache` / `is_cache_complete`

使外部代码可 `from synthetic_socio_wind_tunnel import SimulationContentCache`。

`synthetic_socio_wind_tunnel/data_loader/__init__.py` SHALL 同步 re-export。

#### Scenario: 顶层 import 成功
- **WHEN** `from synthetic_socio_wind_tunnel import SimulationContentCache,
  load_setup_cache, save_setup_cache, is_cache_complete` 执行
- **THEN** SHALL 成功，无 ImportError / 循环依赖


### Requirement: Fitness-audit 探针

`synthetic_socio_wind_tunnel/fitness/audits/` SHALL 新增
`setup_content_cache.py` audit module，含 `phase2-gaps.setup-content-cache`
探针，检查：

- 模块 `synthetic_socio_wind_tunnel.data_loader.setup_cache` 可 import
- `tools/prewarm_setup_content.py` 存在且可执行
- `_generate_identity_text_for_one` 在 `data_loader/lanecove` 存在且 callable
- prompt v2 在 `_LIFE_HISTORY_PROMPT_TEMPLATES` 中存在
- `SimulationContentCache.from_disk()` round-trip 正常（用 dummy 数据）

`mitigation_change` SHALL == `"setup-content-cache"`。

#### Scenario: 本 change 实施后 audit PASS
- **WHEN** 本 change 所有 task 完成后跑 `make fitness-audit`
- **THEN** `phase2-gaps.setup-content-cache.*` 探针 SHALL 全 status == `pass`


### Requirement: 性能与成本约束

prewarm 在默认参数下 SHALL 满足以下约束：

- **wall time**：15 seed × 500 protag × tier=sonnet × concurrency=4 SHALL 在
  ≤ 90 分钟内完成（实测 baseline ~45-60 min）
- **API 成本**：单次完整 prewarm SHALL ≤ $10（DeepSeek v4-pro pricing）
- **fail rate**：fallback 模板比例 SHALL < 5%（即 `failed_protag` ≤ 25 / 500
  per seed）；超过则 stderr WARN 提示用户考虑降 `--concurrency`

#### Scenario: 性能门
- **WHEN** `tools/prewarm_setup_content.py --seeds 42-56` 在健康 API 状态下跑完
- **THEN** wall time SHALL ≤ 90 min；CLI 退出码 0

#### Scenario: fail rate 警告
- **WHEN** 任一 seed 的 `failed_protag` 长度 > 25
- **THEN** stderr SHALL 含 "WARN: seed=X had Y fallbacks (>5%)，consider lower
  concurrency"


### Requirement: docs/agent_system 用户向白话指南

`docs/agent_system/17-setup-content-cache.md` SHALL 包含以下章节：

1. 是什么（白话）：为什么不每次重生成
2. 解决什么问题（引号风格用户问题）
3. 用法速记（prewarm CLI + 续跑流程）
4. 与既有 capability 的关系（multi-day-run / run-resilience / tick-level-resume）
5. schema_version 演化策略
6. 故事化背景（D2 attempt 3 的 0/500 life_history 失败）

#### Scenario: 文档存在 + 内容覆盖
- **WHEN** archive 后 ls `docs/agent_system/17-setup-content-cache.md`
- **THEN** 文件 SHALL 存在；内容 SHALL 含 D2 attempt 3 失败事件提及 + prewarm
  CLI 示例
