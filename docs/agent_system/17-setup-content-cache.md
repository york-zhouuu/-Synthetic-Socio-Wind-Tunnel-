# 17 · Setup Content Cache（虚拟居民档案的"预热"机制）

**对外白话名**：人物档案预生成
**技术名**：`setup-content-cache`
**Chain-Position**：`infrastructure`
**上线日期**：2026-05-16

---

## 是什么

每一次 publishable 跑（1000 agent × 14 天 × 15+ seed）都需要先给 500 位虚构居民
**写好他们的过去**——

- 每个人的 20 条 life history（"5 年前我搬到 Lane Cove"、"上次在 Plaza
  跟邻居打照面"……）
- 每个人的 identity text（一段 200 字第一人称中文自我介绍）

这些都是用 LLM 生成的。在过去，suite 一启动时就让 LLM 在几秒钟内 **同时**
处理 500 份档案——结果服务器被打到拒绝连接，最坏的一次 500 个人里只有 0 个写
出了 life history。模拟跑得下去，但每个虚构居民都是空人格。

这一层 cache 把档案生成**搬到模拟开始之前**做：用一个慢节奏的脚本（每次只
处理 4 个人，错开节奏），慢慢生成、慢慢落盘。然后跑模拟的时候，suite 不再
打 LLM，直接读硬盘。

> "如果每次跑虚拟城市都要重新写一遍 500 个虚构居民的传记，那不是浪费吗？"
>
> 是的，这块就是把'传记'做一次写一次盘，下一次跑的时候直接用。

---

## 解决什么问题

> **"为什么之前跑出来的数据 protag 都像没有过去？"**

D2 续跑 attempt 3（2026-05-16）的诊断：

- baseline 跑出 `[aitown] life_history: 0 events across 500 protag`
- hp_push 跑出 2/500
- 模拟跑完没崩，但 reflection / decision 都基于"空人格"

根因不是代码 bug，不是 API 没钱，是**并发突发模式**——4 个 worker × 每个 worker
500 并发 LLM call = 同一秒打 2000 个连接，DeepSeek 端 connection refusal、
所有 circuit breaker open。这一层 cache 把"突发"换成"慢喷"，从根上解决。

---

## 意义

没有这一层，**publishable 实验数据等于 garbage**——agent 没有过去，
reflection 没有内容，对话没有人设。15 个 seed × 500 protag = 7500 个虚构居民
的 backstory 一定要稳定生成出来，并且每次跑都用同样的，否则不同 run 之间
的"人格"会变，违反 β=30 的可比性要求。

这一层 cache 还顺手解决了另一个问题：**幂等性**——给定 seed=42 这个虚构
小区里第 42 号居民永远是同一个 Emma，不会今天叫 Emma 明天叫 Linda。

---

## 用法速记

### 一次性预热（每台新机器 / schema 升级后跑一次）

```bash
# 默认 seeds 42-56（publishable 范围）
python tools/prewarm_setup_content.py

# 估时 45-90 分钟，估价 $3-10（DeepSeek sonnet tier）
# 写到 data/setup_content_cache/seed_<N>.json

# 单个 seed 排查
python tools/prewarm_setup_content.py --seeds 42

# 慢一点更稳
python tools/prewarm_setup_content.py --concurrency 2 --batch-sleep 0.3

# 强制重写已有 cache
python tools/prewarm_setup_content.py --seeds 42 --force

# 看一眼计划但不真的调 LLM
python tools/prewarm_setup_content.py --dry-run -v
```

### 跑 publishable suite

无需额外操作——`tools/run_variant_suite.py` 已经 cache-aware：

- cache HIT（推荐路径）：setup phase 几乎 0 秒，setup_cache=HIT 打 log
- cache MISS（兜底路径）：在线生成 + 落盘，下一次就是 HIT

worker log 找 `[setup_cache] HIT for seed=N` 行确认走的是 cache。

---

## 缓存文件格式

`data/setup_content_cache/seed_<N>.json`：

```json
{
  "schema_version": "1",
  "seed": 42,
  "generated_at": "2026-05-16T22:00:00",
  "generator": {
    "tier": "sonnet",
    "model": "deepseek-v4-pro",
    "n_records_per_protag": 20,
    "prompt_version": "v2",
    "concurrency": 4
  },
  "life_history": {
    "a_42_0042": [
      {"record_id": "...", "title": "...", "content": "...",
       "years_ago": 5.0, "location_hint": "Lane Cove Plaza",
       "importance": 0.8, "tags": ["move"]},
      ...  // 20 records per protag
    ]
  },
  "identity_text": {
    "a_42_0042": "我是 Emma, 32 岁, 设计师, 住在 Lane Cove..."
  },
  "failed_protag": []
}
```

---

## Schema 演化策略

如果未来要加字段（如 `emotional_valence` / `related_agent_id`），把
`_CURRENT_SCHEMA_VERSION` 从 `"1"` 升到 `"2"`——

- 旧 cache 文件被 `load_setup_cache` 检测为 schema mismatch，自动 invalidate
- 在 log 里打 warning："cache miss — re-prewarm needed"
- 跑一次 `prewarm_setup_content.py` 重新生成

不做向后兼容字段合并，因为 cache 是**离线产出物**而非数据迁移目标——重跑
比维护双 schema 简单。

---

## 公共 API

```python
from synthetic_socio_wind_tunnel import (
    SimulationContentCache,
    load_setup_cache,
    save_setup_cache,
    is_cache_complete,
)

# 在 setup phase 里：
cache = load_setup_cache(seed)
if cache and is_cache_complete(cache, profiles):
    # HIT — zero LLM
    life_history = cache.life_history
    identity_text = cache.identity_text
else:
    # MISS — fallback online
    ...
```

---

## 关键不变量

1. publishable run **SHALL** 先跑 `tools/prewarm_setup_content.py`
   让 cache 落地。
2. schema_version 升级 **SHALL** 重新跑 prewarm。
3. cache 目录 (`data/setup_content_cache/`) **不进 git**——每台机器独立 prewarm，
   保证文件状态来自该机器的实际预热产出。
4. cache 文件名 = `seed_<N>.json`（一文件一 seed，便于人工 spot-check 和
   per-seed 重跑）。

---

## 相关 capability

- [[run-resilience]]（2026-05-15）—— circuit breaker / retry / per-day
  checkpoint；这层 cache 走的 atomic-write 模式从那里继承
- [[tick-level-resume]]（2026-05-16）—— per-tick WAL 用同样的 atomic-write 模式
- 上游 capability：`data-loader-lanecove`（life_history + identity_text
  生成本身）
- 下游 capability：所有 publishable run（D2 attempt 4+ / D3 / 后续）
