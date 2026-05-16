## Context

D2 续跑 attempt 3 当天暴露的真实失败模式：

1. **并发突发模式 vs 速率限制**：`life_history` 生成在 publishable scale 是
   4 worker × 500 protag concurrent batch=5 ≈ 数百个 LLM call 同时打 DeepSeek
   server。**不是触发 429 (rate limit)，而是触发 server-side accept queue 满 +
   TCP/TLS 握手失败 → APIConnectionError**。我们的 RetryPolicy 把
   `APIConnectionError` 归 `retryable` → 3 次重试都失败 → record_failure on
   key → 5 次累计失败 → key 进入 open 状态 → 短时间内 8 个 key 全 open →
   `AllKeysOpenError` → 该 protag 的 life_history 被 fallback 到空 `[]`。

2. **同 seed 跨 run 浪费**：今天 D2 attempt 1/2/3 重复 6 次生成同一组
   seed=42 的 hp/gd/pf life_history（即使生成成功也是同一虚构人物 background，
   语义上幂等）。这些重复都白烧 LLM。

3. **每 seed 内跨 variant 浪费**（小一些）：同 seed 不同 variant 用相同的 500
   protag profile（population sampling 是 seed-only deterministic），所以
   variant_hyperlocal_push seed=42 和 variant_global_distraction seed=42 的
   life_history 应该是同一份内容（agent 是同一个人，只是 simulation 走不同
   intervention 路径）。

## Goals / Non-Goals

**Goals**：

- 一次生成、永久 reuse：单 seed 的 life_history + identity_text 落到磁盘后
  下次 run 直接 load，**零 LLM call**
- 生成质量 SHALL 达 publishable 标准：JSON parse 失败率 < 1%、内容地标具体、
  人物维度有差异
- 预热路径不会触发 D2 attempt 3 那种灾难（并发 ≤ 8，远低于 publishable 500）
- 缓存 schema 演化可控：schema_version 升级自动 invalidate，不静默用旧数据
- 实施 P0：今天 archive + 实施完、明早恢复 D2

**Non-Goals**：

- 不做人物互文（Alice 提及 Bob 的双向引用），需要 2-pass
- 不做字段扩展（emotional_valence 等），等 thesis 用到再加
- 不支持 cross-seed cache 共享（语义错）
- 不做 cache 跨机器同步（单机即可）
- 不做 incremental cache（升级一律全 invalidate）

## Decisions

### D1 · 缓存粒度：per-seed 一文件、内含全部 protag

**选**：`data/setup_content_cache/seed_<N>.json`，一文件含 500 protag 的 life_history
+ identity_text。

**Why over alternatives**：

- **alt A · per-(seed, agent_id) 一文件**（500 文件 / seed × 15 seed = 7500 文件）：
  原子性好（局部失败只丢局部）但文件爆炸；ls 缓存目录痛苦；备份 / 传输不便
- **alt B · 单一 cache file 含全部 seed**：原子写盘风险更大（每次写整库 ~15MB）；
  并发 prewarm 多 seed 时锁竞争
- **alt C · per-seed 一文件**（选）：~1MB / 文件 × 15 文件 = 15MB，磁盘友好；
  per-seed 写盘失败只丢该 seed；可单独删除某 seed 强制重生成；prewarm 多 seed
  并发写不冲突

**Trade-off**：单 seed 内部分 protag 生成失败 → 整 seed 文件可能还是要写（含
fallback 模板的 protag）。可接受。

### D2 · 数据格式：纯 JSON，非 Pydantic 序列化

**选**：cache 文件是手写的 JSON dict（`{life_history: {agent_id: [...]}, identity_text: {agent_id: "..."}}`）；
代码层用 `SimulationContentCache` Pydantic 模型读 / 校验 / 转换。

**Why**：

- 人工可读 / 可手动编辑（修个错字 / 删某条不需要重跑）
- 跨工具兼容（其它脚本 / 可视化可以直接读）
- 不依赖 Pydantic 版本（schema 改了不影响旧 cache 的 plain JSON）

### D3 · Schema 升级策略：版本字符串 + 全 invalidate

**选**：`SimulationContentCache.schema_version: str = "1"`。读时严格比较：

- `version == "1"` → 直接使用
- `version != "1"` → log warning + invalidate（视为 cache miss）+ 触发重新生成

升级 schema 时（如加 `emotional_valence` 字段）改默认值为 `"2"`，旧 cache 自动
失效。**不做 schema migration**（迁移逻辑容易出错，重新生成几小时可接受）。

**Why over forward-compat 兼容**：

- 字段加减时迁移代码会越来越乱
- 用户对 cache 失效的预期（"我升了 schema，cache 当然作废"）符合直觉
- prewarm 脚本本来就支持运行，schema 失效后自然走预热路径

### D4 · 并发与 retry 策略

**选**：prewarm 默认 concurrency=4（per seed 同时 4 个 LLM call in flight），
每批之间 sleep 0.1s；LLM call JSON parse 失败自动 retry 2 次（共 3 次尝试）。

**Why concurrency=4**：

- 8 个 DeepSeek key × 60 RPM ≈ 480 RPM 容量（理论值）
- 4 concurrent × 1 call/sec ≈ 240 RPM 实际（well within 容量）
- 与今天观察到的 stress test 上界 ~300 concurrent OK 一致
- 进一步降到 1（纯串行）太保守，500 protag × 1.5s = 750s = 12.5 min/seed
- 4 concurrent → ~3 min/seed，15 seed ≈ 45-60 min wall total

**Why retry 2 次（共 3 attempt）**：

- attempt 1 JSON 解析失败常见（sonnet 偶尔加 markdown 包装、加 ```json 标记）
- attempt 2 用同 prompt 重试通常解决（temperature 默认有抖动）
- attempt 3 仍坏 → fallback 模板（保底）
- 3 次以上是边际收益递减 + 时间浪费

### D5 · Fallback 模板

**选**：3 次 LLM attempt 失败的 protag 走 `data/lanecove/life_history_templates.json`
的 archetype-conditioned 静态模板。

**Why**：

- 已有该静态文件（archived `enrich-lanecove-map` change 写的）
- Fallback 不留空 → 实验下游不需要 special-case "0 events" 的 agent
- 模板生成的 life_history 质量低于 LLM 但**有内容**，比空字符串好得多

**已知折扣**：模板生成的内容跨 protag 重复（同 archetype 用同模板），多样性差。
Acceptable 因为 fallback 路径是 < 1% 比例。

### D6 · Prewarm 进度可见 + 中断恢复

**选**：进度通过 stderr 打印每 50 protag 一行（`[prewarm] seed=42 progress=350/500`）。
中断恢复策略：cache 写盘是 per-seed atomic（写完一个 seed 才落盘）。如果中途
SIGKILL → 已落盘的 seed 文件保留、in-flight 的 seed 丢失（重启时被 prewarm 重新
生成）。

**Why per-seed atomic 而不是 per-protag**：

- per-seed atomic 简单 + 失败影响最小
- per-protag 增量需要额外 partial file（`seed_<N>.partial.json`）+ merge 逻辑
  + 进入崩溃恢复模式 → 复杂度爆炸
- 15 seed × 3 min = ~45 min；最坏丢失一个 seed = 3 min 重做。可接受

### D7 · cache 文件是否 git track

**选**：**不**进 git。`data/setup_content_cache/` 加进 `.gitignore`。

**Why**：

- 体积大（15 seed × ~1 MB = 15 MB）
- 内容由 LLM 随机生成（虽然 schema 稳定但具体字符串 nondeterministic）
- 用户机器各自 prewarm 即可、无需共享
- 但**保留**手动备份选项（不放 .gitignore 时用户可以 commit；我们默认 .gitignore）

**Alt**：把 cache 当 fixture 进 git（让所有机器有同样数据）—— 但 LLM 随机内容
不适合 git diff。

### D8 · tier 选择：sonnet vs haiku

**选**：默认 sonnet (`deepseek-v4-pro`)，prewarm CLI 允许 `--tier haiku` 覆盖。

**Why sonnet 默认**：

- 一次性投入 + 永久 reuse → 边际成本可忽略
- sonnet 模型推理能力强，JSON 格式遵循率高（实测 99% vs haiku 80%）
- narrative 连贯性 / 多样性显著高
- DeepSeek v4-pro 单 call ~0.27/M tokens × ~1500 token / call = $0.0004 / call
- 7500 calls × $0.0004 = ~$3 总成本

**预算**：$3-10 一次性投入，相对论文级数据干净度，绝对划算。

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| prewarm 跑 45-60 min 期间 macOS 睡眠 → 中断 | `caffeinate -i .venv/bin/python tools/prewarm_setup_content.py ...`（用户命令行加） |
| cache 文件 ~1 MB × 15 seed 占磁盘 | 总 15 MB 可忽略；.gitignore 防止意外 commit |
| schema 升级后旧 cache 自动重生 → 1 小时浪费 | 文档化升级流程；rare event |
| sonnet 偶尔仍返回非 JSON → retry 2 次也救不了 | 走 fallback 模板（D5）；预期 < 1% 比例 |
| prewarm 并发=4 还是太高、又触发 connection error | CLI 允许 `--concurrency 1`（纯串行），最坏 ~15 min/seed × 15 = ~4 小时但 100% 成功 |
| cache 文件被人工误改 → schema 解析错 | `SimulationContentCache.from_disk()` 校验失败 raise + log；进 prewarm 路径 |
| identity_text 长度无上限 → cache 文件爆炸 | prompt 显式要求 ~200 字；解析时截到 max 500 字 |
| prewarm 期间 publishable run 同时启动 → 竞争 LLM | 文档化"prewarm 完成再起 publishable"；prewarm 写盘后 publishable 自然 HIT |
| sample_population 跨 sample 行为非确定（如 Atlas 更新后） | seed cache 仍按 agent_id 索引；profile 字段微变不影响 cache（cache 只存 life_history / identity_text） |

## Migration Plan

### Phase 1（本 change 实施期间，~2-3 小时）

1. 写 `data_loader/setup_cache.py` 模块（`SimulationContentCache` +
   load/save/is_complete + atomic write）
2. 写 `tools/prewarm_setup_content.py` CLI
3. 改 `data_loader/lanecove.py::_generate_life_history_for_one` 加 retry +
   prompt v2 + tier_hint
4. 写 `_generate_identity_text_for_one`（新函数）
5. 改 `tools/run_variant_suite.py::_load_or_generate_setup_content`（基于今早
   commit 的 `_load_or_generate_life_history` 扩展，加 identity_text 维度）
6. 测试 ~30 个 unit / 集成 test
7. `openspec validate setup-content-cache --strict` 通过

### Phase 2（archive 后立即）

1. 跑 prewarm：`tools/prewarm_setup_content.py --seeds 42-56`（~45-60 min wall）
2. 验证 cache 文件落地 + size 合理（1-2 MB × 15）
3. 验证质量：sample 几个 seed 看 life_history 内容（人工 spot check）
4. 启动 D2 续跑（D2 attempt 4）：preflight HIT cache → 5-10 min；main run HIT
   cache → setup 几秒；总 wall ~15-20 小时

### Rollback

- 不需要 rollback：cache 是 opt-in（cache miss 时 fallback 到在线生成）
- 删除 `data/setup_content_cache/` 整个目录 → 退化到原有在线生成路径
- 删 `--use-cache` flag（如果加了）→ 也退化

## Open Questions

1. **identity_text 长度上限**：当前 prompt 要求 ~200 字。需不需要硬上限（截 500
   字 / 字节）？答：实施时加 `max_chars=500` 截断 + warning。**P2**
2. **cache 文件 git track 与否**：默认 .gitignore，但用户可能希望"复现性"要求
   commit 进 git。**P3** — 实施时加进 .gitignore，文档建议手动 commit 为"快照"。
3. **prewarm 重启策略**：如果 prewarm 跑到一半中断，partial 落地的 seed 应该
   被 `is_cache_complete` 检测出来跳过 vs 重生？答：seed 文件原子写（写完才落
   盘），所以 partial 不存在；中断的 seed 直接重生。**P1 已决（D6）**。
4. **sonnet tier 在 setup phase 偶发的"过度思考"**：sonnet 有 reasoning，可能
   把 simple `[{...}, ...]` 输出包成 `<thinking>...</thinking>`。需要在 prompt
   里显式禁用思考。**P0** — 用 `extra_body={"thinking": {"type": "disabled"}}`
   （已有这个 DeepSeek 参数支持）。
5. **多机器协同 prewarm**：如果团队多人各跑 prewarm，是否需要 lock / 协调？答：
   单机 OK；如果未来需要分布式 prewarm 再开 follow-up change。**P3**。
6. **prewarm 跑期间 retry 失败的 agent，是否值得标记到 cache 元数据**？答：
   是，cache 顶层加 `failed_protag: ["a_42_0042", ...]` 列表，方便事后审计 /
   决定要不要单独重生。**P2** — 实施时加。
