# `data/` 目录索引

本目录所有 cache / 输入 / 输出文件的 canonical 位置说明。

最后更新：2026-05-21（commit `7de2bb4`，post-resume-fix prewarm 普查）。

## Prewarm Cache（pub 跑必读）

| 目录 | 用途 | 谁读谁写 | 状态 |
|---|---|---|---|
| **`setup_content_cache/seed_<N>.json`** | per-seed life_history (500 × 20 records) + identity_text (500 × ~200 字 中文) | 读：`tools/run_variant_suite.py::_load_or_generate_setup_content`。写：`tools/prewarm_setup_content.py` 或 cache MISS fallback | ✅ Active canonical |
| `population_cache/v1/<sha16>.json` | population sampling cache, keyed by config hash | `synthetic_socio_wind_tunnel/data_loader/population_cache.py::cached_sample_population` | ✅ Active |

### 当前 setup_content_cache 库存（2026-05-21 inventory）

```
seed_42: lh=5/500, id=5/500  ⚠️ 残缺，不能直接跑 publishable
seed_43: lh=500/500, id=500/500  ✅ 完整
seed_44: lh=500/500, id=500/500  ✅ 完整
seed_45: lh=500/500, id=500/500  ✅ 完整
seed_46: lh=500/500, id=500/500  ✅ 完整
seed_47: lh=500/500, id=500/500  ✅ 完整
seed_48: lh=500/500, id=500/500  ✅ 完整
seed_49: lh=500/500, id=500/500  ✅ 完整
seed_50: lh=500/500, id=500/500  ✅ 完整
seed_51: lh=500/500, id=500/500  ✅ 完整
seed_999: lh=1/1, id=1/1  (dev smoke only)
```

→ **β=9 publishable 可用 seed 范围：43-51**（每个 zero-LLM cache HIT）。
seed 42 需要补 500 个 identity_text（life_history_cache 历史 stub 已归档，不可用）。

### 快速 audit 命令

```bash
.venv/bin/python -c "
import json
for n in range(42, 52):
    try:
        with open(f'data/setup_content_cache/seed_{n}.json') as f:
            sc = json.load(f)
        lh, it = sc.get('life_history', {}), sc.get('identity_text', {})
        non_empty_lh = sum(1 for v in lh.values() if v)
        print(f'seed_{n}: lh={len(lh)}/500 ({non_empty_lh} non-empty), id={len(it)}/500')
    except FileNotFoundError:
        print(f'seed_{n}: NOT PREWARMED')
"
```

worker log 找 `[setup_cache] HIT for seed=N — 500 life_history + 500 identity_text (zero LLM)` 确认走的是 cache（不是 fallback online 生成）。

### 缺失 seed 的 prewarm

```bash
# 单 seed prewarm
.venv/bin/python tools/prewarm_setup_content.py --seeds 42 --force

# 多 seed batch
.venv/bin/python tools/prewarm_setup_content.py --seeds 52-55

# 估时：500 protag × ~10500 LLM call 总共 ~1-2h with --concurrency 4
# 估价：~$3-10 per seed (DeepSeek sonnet tier)
```

详见 `docs/agent_system/17-setup-content-cache.md`。

## 静态地图 / 设定文件

| 文件 | 用途 |
|---|---|
| `lanecove_atlas.json` | Atlas (静态 region + buildings) — cartography 离线产物 |
| `lanecove_enriched.geojson` | OSM 导入后增强的 GeoJSON |
| `lanecove_osm.geojson` | OSM raw export |
| `overture_buildings.geojson` / `overture_places.geojson` | Overture maps 补充 |
| `lanecove_proj_center.json` | 投影中心点 |
| `lanecove_enriched.stats.json` | atlas 统计概要 |

## 输出数据

| 目录 | 内容 |
|---|---|
| `experiments/` | 当前正在跑的 / 最近的 publishable / preflight 输出 |
| `experiments_archive_pre_2026_05_21/` | commit `7de2bb4` 之前跑的旧数据，**3 重污染不能做 publishable analysis**。详见该目录里的 `ARCHIVE_NOTE.md` |
| `exports/` | 处理过的 export 数据 |
| `face_validity/` | face-validity audit 输出 |
| `realism/` | realism 评估输出 |
| `calibration/` | 校准 / stereotype audit 报告 |

## 历史遗留（不要在新代码里引用）

- `experiments_archive_pre_2026_05_21/life_history_cache_dead_code_stubs/` — 旧
  `data/life_history_cache/` 目录的内容。该路径的 cache 是
  `tools/run_variant_suite.py::_load_or_generate_life_history` 死代码 function
  读的（无人调用），且内容是 500 个 agent_id 映射到空 list `[]` 的 stub 文件。
  归档以防有未发现的引用，确认无用后可删。
