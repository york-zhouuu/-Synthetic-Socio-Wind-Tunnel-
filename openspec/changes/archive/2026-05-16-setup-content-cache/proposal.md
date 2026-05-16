## Why

2026-05-16 D2 续跑 attempt 3 暴露**setup phase 在 publishable scale 下的灾难性失败**：
- 4 preflight worker × 500 protag × 同时打 life_history LLM call
- 突发并发把 DeepSeek 服务端打到拒绝连接（`APIConnectionError`，**不是 429**——
  是 server-side accept queue 满 + TCP/TLS 握手失败）
- 8 个 DeepSeek key 全部被 PerKeyCircuitBreaker open
- baseline worker 跑出：`[aitown] life_history: 0 events across 500 protag`
  （500 个 protag **没有一个**有生平传记）
- hp worker 跑出：`2 events across 500 protag`（500 个里 2 个有）

后果：simulation 跑得下去（tick 在推进、WAL 在长、snapshot 在落），**但 protag
memory store 是空的**——所有 reflection、do_something、daily_summary 走的是
"空白人格"。**publishable 实验数据等同 garbage**，论文用不了。

同时观察到深层浪费：`life_history` 和 `identity_text` 是**确定性内容**——给定
seed + agent_id 应当永远是同一个虚构人物的同一份生平。当前每次跑都从零生成：

```
15 seed × 500 protag × 2 (life_history + identity_text) = 15,000 redundant LLM call / 次跑
```

今天到目前为止已经 attempt 1/2/3 重复生成 6 次 ≈ 浪费 ~$10-30 + ~3-5 小时 wall。

**Chain-Position**：`infrastructure`（与 `multi-day-simulation` /
`run-resilience` / `tick-level-resume` 同位；不引入新主边界；为 publishable
run 提供干净 + 持久的 setup 内容底座）。

## What Changes

### 1. 新 capability `setup-content-cache`（NEW）

抽离 setup phase 里**幂等 + 一次性**的 LLM 内容到 per-seed 缓存：

- `data/setup_content_cache/seed_<N>.json`（一文件 per seed，含 schema_version
  + life_history + identity_text + generator metadata）
- `SimulationContentCache` Pydantic frozen 模型
- 公共 helper：`load_setup_cache(seed)` / `save_setup_cache(seed, ...)` /
  `is_cache_complete(seed, profiles)`
- schema_version-based invalidation（升 schema 旧 cache 自动失效）

### 2. 离线预热脚本 `tools/prewarm_setup_content.py`（NEW）

publishable run 之前**离线慢速预生成**全部 seed 的 setup 内容。CLI：

```bash
.venv/bin/python tools/prewarm_setup_content.py \
  --seeds 42-56 \
  --concurrency 4 \        # 远低于 publishable 的 500 并发
  --batch-sleep 0.1 \      # 给 DeepSeek 喘息
  --tier sonnet \          # 高质量生成、JSON 解析率 ~99%
  --n-records 20           # 每 protag 20 条 life_history
```

- 串行 / 低并发遍历每 seed 的 500 protag
- 调真 LLM（默认 sonnet/deepseek-v4-pro）
- 每 LLM call JSON 坏自动 retry 2 次；3 次都坏走 fallback 模板
- 每 50 个 protag 打印进度行
- 已有 cache + schema_version 匹配 → skip（除非 `--force`）

### 3. suite-wiring 集成路径（NEW，不动 suite-wiring spec 既有契约）

`tools/run_variant_suite.py` setup phase 改 cache-load-first：

```python
cache = load_setup_cache(seed)
if cache and is_cache_complete(cache, profiles):
    history = cache.life_history
    identities = cache.identity_text
    # 0 LLM call in setup
else:
    # 在线 fallback（同精细化路径，写入 cache）
    history = generate_life_history_for_protagonists(profiles, retry=2, tier=sonnet, n=20)
    identities = generate_identity_text_for_protagonists(profiles, retry=2, tier=sonnet)
    save_setup_cache(seed, history, identities)
```

**publishable run 期望**：先跑 prewarm 脚本 → cache 落地 → main run 全 cache HIT，
**setup phase 零 LLM call 零失败**。

### 4. ABCD 精细化（应用到预热脚本 + 在线 fallback）

- **A. 数量**：`n_records_per_protag` 默认 10 → **20**（memory 检索池更厚、
  reflection 有素材）
- **B. tier**：默认 haiku → **sonnet（deepseek-v4-pro）**，推理 tier 出更稳定
  的 JSON + 更连贯的 narrative
- **C. retry**：每 protag LLM call JSON parse 失败自动 retry **2 次**，3 次都
  坏走 fallback 模板（templates from `data/lanecove/life_history_templates.json`）
- **D. prompt 增强**：注入 profile.home_location + life_pattern 全字段 +
  Lane Cove 邻里地标 list（Plaza / Longueville Rd / Greenwich / Epping Rd /
  Mowbray Rd 等）+ 显式要求"提及具体地标 + 时间"

### 5. identity_text 同等处理（NEW）

`identity_text` 当前从 profile 派生默认空字符串。引入：

- `_generate_identity_text_for_one(profile, archetype, life_history_snippets)` →
  ~200 字第一人称自我介绍（"我是 XX, 30 岁, 住在 Longueville Road..."）
- 同 cache 路径（生成后写 cache、下次跑 HIT）
- 同 ABCD 精细化策略

### 6. schema_version 演化策略

`SimulationContentCache.schema_version = "1"`（当前）。未来加字段（如
`emotional_valence` / `related_agent_id`）SHALL 升 `"2"`：

- 旧版本 cache 读 → log warning "schema mismatch，重新生成中"
- 自动触发 prewarm 路径
- 旧 cache 不删（人工 review 后用户决定）

## Capabilities

### New Capabilities

- `setup-content-cache`：per-seed 持久化 setup phase LLM 内容（life_history +
  identity_text）+ 离线预热脚本 + cache-aware suite-wiring 集成。提供：
  `SimulationContentCache` / `load_setup_cache` / `save_setup_cache` /
  `is_cache_complete` 4 个公共 API + `tools/prewarm_setup_content.py` CLI。

### Modified Capabilities

无 spec 级 modify。说明：

- **`suite-wiring`（已 archive）**：`tools/run_variant_suite.py` 实现层加 cache
  分支，但**不改 suite-wiring spec 的 SHALL 契约**（spec 只描述行为，cache 是
  实现细节）。
- **`data_loader/lanecove.py`**：内部 helper 加 retry / tier_hint / prompt v2，
  但该模块当前**没有 openspec spec**——属于无契约面的内部模块。

## Impact

- **新代码**
  - `synthetic_socio_wind_tunnel/data_loader/setup_cache.py` 新模块
    （`SimulationContentCache` + helpers）
  - `tools/prewarm_setup_content.py` 新 CLI（~150-200 行）
  - `data/setup_content_cache/` 新目录（gitignored 还是 tracked 待定 — 见
    design Open Questions）
  - prompt template v2 in `data_loader/lanecove.py`
  - `_generate_identity_text_for_one` 新函数
- **修改**
  - `synthetic_socio_wind_tunnel/data_loader/lanecove.py::_generate_life_history_for_one`：
    加 retry + 增强 prompt + tier_hint 参数
  - `tools/run_variant_suite.py`：现有 `_load_or_generate_life_history`（今天
    早些时候加的）扩展为 `_load_or_generate_setup_content`（含 identity_text）
  - `synthetic_socio_wind_tunnel/__init__.py`：re-export
    `SimulationContentCache`
- **测试**
  - `tests/test_setup_content_cache.py`（cache load/save/round-trip/schema 升级）
  - `tests/test_prewarm_setup_content_cli.py`（CLI dispatch / --force / 进度 log）
  - `tests/test_life_history_retry.py`（JSON 坏 → retry → 成功；3 次坏 → fallback）
  - `tests/test_identity_text_generation.py`（生成 + 写 cache + round-trip）
- **依赖**：无新增（用既有 openai SDK + 既有 retry pattern）
- **配置 / 文档**
  - `docs/agent_system/17-setup-content-cache.md` 新增（用户向白话指南）
  - `CLAUDE.md` 关键不变量加一条（publishable 前 SHALL 跑 prewarm；schema 升级
    SHALL 重新跑 prewarm）
  - `.env.example` 不动（无新 env var）
- **前置依赖**：`run-resilience` + `tick-level-resume` 已 archive（cache 文件用
  原子写盘借用 run-resilience 的 atomic-write 模式）
- **下游影响**：所有 publishable run（D3+）SHALL 走 prewarm-then-run 流程；
  attempt 3 之后立刻可用

## Non-goals

- **不**做 F（人物互文：Alice 提到 Bob、Bob 提到 Alice）—— 需要 2-pass 生成 +
  agent_id reference 解析，复杂度大、留 follow-up
- **不**做 E（字段扩充：`emotional_valence` / `turning_point` / `related_agent_id`）
  —— 当前 thesis 不直接用，加字段会 cascade 影响 memory 检索 + reflection prompt
- **不**做 G（cross-protag 多样性 sanity check）—— 信任 sonnet + 好 prompt 自然
  解决；如果跑完 prewarm 发现 title 重复严重再单独开 change
- **不**支持 cross-seed cache 共享 —— 不同 seed 的 a_42_0042 vs a_45_0042 是
  不同虚构人物，共享 cache 在语义上错误
- **不**改其他 setup 内容（`social_priors` 从静态文件读、不是 LLM 生成；
  `archetypes` 也是静态）
- **不**做 incremental cache（部分 protag 重新生成）—— schema 升级走全
  invalidate-and-regenerate 路径
- **不**做 cache 跨机器同步 —— 单机本地缓存即可
