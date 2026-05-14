# 2026-05-10 夜间 autonomous session 总结

**目的**：用户睡前指示"按路径 2 跑 D，但开完后 A 全套继续做完"。
**用户预期**：睡醒能看到大部分都做完了。

---

## ✅ 已 archive（OpenSpec change）

| Change | 内容 |
|---|---|
| **A1 realism-perception-loop** | Planner.replan 接 SubjectiveView prose；scripted_plan 拥挤换 dest；perception inspector CLI；prose helper |
| **B 全套 soul-memory-relations-completeness** | B1 archetype 12 个（adult 100% 覆盖）；B2 life_history Lane Cove anchors；B3 priors audit + household_kin 限制识别；B4 conversation_topics 12 个话题 |

---

## ✅ 已 ship 进 main（**NOT archive — minimum-viable**）

### A2 realism-household-coupling §1-§3

新增：
- `AgentProfile.household_id: str` + `household_role: Literal["parent","child","partner","lone"]`
- `synthetic_socio_wind_tunnel/agent/household.py::HouseholdRegistry`（with `members_of` / `household_of` / `home_location_for` / `siblings_of` / `household_count`）
- `agent/population.py::_cluster_into_households` 后处理函数

**关键解锁**：
- 1000 agents → 344 households (329 shared homes)
- household_kin social_prior 从 **0 → 1130 ties**（B3 audit 发现的限制已修）

**剩余 §4-§6**（待下次 session）：
- scripted_plan household coordination（morning drop-off / weekend co-trip）
- multi_day_run integration
- archive

### A3 realism-poi-capacity §1-§2

新增：
- `OutdoorArea.capacity` + `Building.capacity` 字段（None = unbounded）
- `synthetic_socio_wind_tunnel/atlas/heat.py::POIHeatModel`
- `DEFAULT_CAPACITY_BY_AREA_TYPE` map（cafe=15 / shop=10 / park=None 等）

**剩余 §3-§7**（待下次 session）：
- simulation::move_entity overflow 行为（30% defer / 30% redirect / 40% abandon）
- orchestrator 注入
- metrics extension（poi_overflow_count）
- smoke + archive

---

## ✅ 工具和脚本

- `tools/check_publishable_integrity.py`（D3）— 扫 publishable suite 输出验证 7 字段 rep_lock / cost / encounter / traj_dev 完整性
- `tools/build_evidence_report_v4.py`（D4）— 基于 publishable 数据出新版 HTML 报告（含 trajectory_deviation_m_all sanity column / provider field / 新 metric schema）

两个工具都已经在 post-fix smoke 数据上验证可跑。

---

## ⏳ 后台运行中

**D1 Gemini smoke**（1 seed × 14 day × 100 agent × 4 variant × Gemini Flash + ai-town path）

启动时间：18:21
预估完成：4-8 小时（log 用 `tail -50` 缓冲，结束才出文件内容）
进程：`run_variant_suite.py`，可用 `ps aux | grep run_variant_suite` 查
输出目录：`data/experiments/20260510_182153_d1_gemini_smoke/`

如完成，跑：
```bash
python3 tools/check_publishable_integrity.py data/experiments/20260510_182153_d1_gemini_smoke
python3 tools/build_evidence_report_v4.py data/experiments/20260510_182153_d1_gemini_smoke
open data/experiments/20260510_182153_d1_gemini_smoke/report_v4.html
```

如失败（中途崩溃 / API quota），看 `/private/tmp/claude-501/-Users-york-z-Desktop-IDEA---agent---Synthetic-Socio-Wind-Tunnel/d9b56bd9-33a2-4d80-97a9-68c675000cb0/tasks/bl23kvsqc.output`。

---

## 📊 测试基线变化

| 阶段 | passed |
|---|---|
| Session 起始（A1 + B 之前）| 1190 |
| A1 archive 后 | 1218 (+28) |
| B 全套 archive 后 | 1238 (+20) |
| A2 minimum ship | 1246 (+8) |
| A3 minimum ship | **1257** (+11) |

**全程 0 regression**。

---

## 🎯 用户睡醒该看的下一步

1. **检查 D1 是否完成**：`ls data/experiments/20260510_182153_d1_gemini_smoke/`
2. **如完成**：跑 integrity check + v4 report；看 hp 的 encounter direction 是否反转
3. **如方向 OK**：决定是否上 D2 publishable（30 seed × 14 day，~12-15hr / $80-150）
4. **下次 session**：完成 A2 §4-§6（scripted_plan household coordination）+ A3 §3-§7（move_entity overflow）

---

## 🧾 honest disclosure

- **A 全套**没完整做完——A2/A3 的 hot-path 集成（scripted_plan 协调 / move_entity overflow）是各 ~5 天的精细工作，autonomous session 硬塞会写出半成品代码污染 main。所以只 ship 了 minimum-viable 基础设施。
- D1 启动的第一次（dev mode）失败了（dev limit 3 day），第二次（publishable mode）正常 launch；预估时间从 1.5hr 调到 4-8hr 是因为 Gemini Flash 真 LLM 调用比 stub 慢 ~10x。
- 每 archive 一个 change 都写了完整 proposal/design/specs/tasks 并 strict validate 通过；A2/A3 的 propose 文档现在和 implement 进度同步。
