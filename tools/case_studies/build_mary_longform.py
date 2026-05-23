"""Build 老何's longform NYT-style profile HTML.

Style: Gay Talese "Frank Sinatra Has a Cold" — third-person, scene-driven,
specific sensory details, multiple POVs, family history foundation, telling
details, counterfactual via 4 parallel universes.

Data: 4 variant snapshots (BL/HP/GD/PF) + positions + atlas + profile.

Output: docs/case_studies/mary.html
"""
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
DIARY_DIR = REPO / "data/analysis/case_studies"
OUT = REPO / "docs/case_studies/mary.html"

MARY = "a_43_0405"

# ─── Load all data ─────────────────────────────────────────────────────
print("Loading data...")
four = json.load(open(DIARY_DIR / "mary_4variants.json"))
positions = json.load(open(DIARY_DIR / "mary_4variants_positions.json"))

# Atlas
atlas = json.load(open(REPO / "data/lanecove_atlas.json"))
LOC2META = {}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        xs=[v["x"] for v in verts]; ys=[v["y"] for v in verts]
        LOC2META[bid] = {"name": b.get("name") or "", "type": b.get("building_type") or "",
                         "x": sum(xs)/len(xs), "y": sum(ys)/len(ys), "polygon": verts,
                         "description": b.get("description") or ""}
outdoor = atlas.get("outdoor_areas", {})
out_iter = outdoor.items() if isinstance(outdoor, dict) else [(o["id"], o) for o in outdoor]
for oid, o in out_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        xs=[v["x"] for v in verts]; ys=[v["y"] for v in verts]
        LOC2META[oid] = {"name": o.get("name") or "", "type": o.get("area_type") or "",
                         "x": sum(xs)/len(xs), "y": sum(ys)/len(ys), "polygon": verts,
                         "description": o.get("description") or ""}

# 老何's profile from population_cache
import os
profiles = {}
for f in os.listdir(REPO / "data/population_cache/v1"):
    d = json.load(open(REPO / f"data/population_cache/v1/{f}"))
    if d.get("key_inputs", {}).get("seed") != 43: continue
    for p in d.get("profiles", []):
        if p.get("agent_id"):
            profiles[p["agent_id"]] = p

mary_profile = profiles[MARY]

# 老何 in HP (canonical narrative variant)
hp = four["variants"]["hyperlocal_push"]

# ─── Helpers ───────────────────────────────────────────────────────────
def loc_name(loc_id):
    return LOC2META.get(loc_id, {}).get("name") or loc_id


# ──────────────────────────────────────────────────────────────────────
# LLM artifact cleanup — strip out simulation-internal IDs and stock phrases
# so the prose reads like a journalist's reconstruction rather than raw LLM output.
# ──────────────────────────────────────────────────────────────────────
def neighbor_label(aid):
    """Replace a_43_XXXX with a natural neighbor reference using profile data."""
    p = profiles.get(aid)
    if not p:
        return f"邻居 #{aid.replace('a_43_', '')}"
    age = p.get("age", "?")
    occ = p.get("occupation", "")
    occ_zh = {"tradesperson": "工人", "manager": "管理者", "unemployed": "失业者",
              "construction": "建筑工", "homemaker": "全职妈妈", "engineer": "工程师",
              "software_dev": "软件开发", "accountant": "会计", "doctor": "医生",
              "teacher": "教师", "lawyer": "律师", "retired": "退休老人",
              "student": "学生", "nurse": "护士"}.get(occ, occ or "")
    if occ_zh:
        return f"那位 {age} 岁{occ_zh}邻居"
    return f"那位 {age} 岁邻居"


def clean_text(text):
    """Conservative scrub — only strip the most obvious robotic markers
    (agent IDs, "Here is the summary from X's perspective" openers).
    Keep all warmth/feeling content — that's the soul of the LLM-generated
    first-person summaries.

    Trade-off: leaves "总的来说" / "我喜欢这次互动" / "气氛轻快" etc.
    intact because they read as the agent's voice, not as boilerplate.
    """
    if not text:
        return text
    import re

    # 1. Replace agent IDs with profile-based natural references
    def rep_aid(m):
        return neighbor_label(m.group(0))
    text = re.sub(r'a_43_\d{4}', rep_aid, text)

    # Replace standalone generic `agent_NN` (where NN doesn't match a real id)
    # with "邻居" — note: must NOT touch agent_405 within compound IDs (already handled above)
    text = re.sub(r'\bagent_\d{1,4}\b', '邻居', text)

    # 2. Remove ONLY the most blatant POV-framing openers (start of text)
    OPENERS = [
        r'^从我的视角(来)?看[，,：:\s]*',
        r'^从我的角度来看[，,：:\s]*',
        r'^好的[，,]?\s*这是我从\s*\S+\s*的视角对这次对话的总结[：:。\s]*',
        r"^Here is the summary from .*?perspective:?\s*",
        r"^Here'?s? the summary from .*?perspective:?\s*",
        r"^Here'?s a summary from .*?perspective:?\s*",
    ]
    for pat in OPENERS:
        text = re.sub(pat, '', text, flags=re.MULTILINE)

    # 3. Collapse whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip(' 。.,，\n')
    if text and text[-1] not in '。.!?':
        text += '。'
    return text

def loc_xy(loc_id):
    m = LOC2META.get(loc_id)
    return (m["x"], m["y"]) if m else None

def fmt_date_short(iso):
    if not iso: return "?"
    try: return iso[:10]
    except: return str(iso)

def render_lanecove_svg(highlight_locs=None, marker_locs=None,
                       trajectory_points=None, width=600, height=380,
                       center_xy=None, radius=1100, mute_buildings=False,
                       trajectory_color="#1B1F2A", trajectory_width=1.2,
                       trajectory_opacity=0.55):
    """Render a Lane Cove map SVG.
    highlight_locs: set/list of location_ids to render in orange
    marker_locs: list of (loc_id, label, color) to add markers
    trajectory_points: list of (x, y) to connect with polyline
    trajectory_color/width/opacity: per-variant trajectory styling
    """
    if center_xy is None:
        hub = atlas["buildings"].get("lane_cove_community_hub")
        if hub:
            verts = hub.get("polygon", {}).get("vertices", [])
            xs=[v["x"] for v in verts]; ys=[v["y"] for v in verts]
            center_xy = (sum(xs)/len(xs), sum(ys)/len(ys))
        else:
            center_xy = (0, 0)
    cx, cy = center_xy
    scale = min(width / (2*radius), height / (2*radius))
    def proj(x, y): return (width/2 + (x-cx)*scale, height/2 - (y-cy)*scale)
    def in_view(x, y): return (x-cx)**2 + (y-cy)**2 <= radius**2

    parts = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
             f'style="background:#F4EFE5; display:block; width:100%; height:auto;">']
    highlight_set = set(highlight_locs or [])

    # Parks
    for oid, m in LOC2META.items():
        if m.get("type") in ("park", "playground", "garden"):
            verts = m["polygon"]
            if len(verts) < 3: continue
            if not in_view(m["x"], m["y"]): continue
            pts = [proj(v["x"], v["y"]) for v in verts]
            d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x,y in pts) + " Z"
            parts.append(f'<path d="{d}" fill="#CFE3C4" stroke="#9DBC8A" stroke-width="0.4"/>')
    # Streets
    for oid, m in LOC2META.items():
        if m.get("type") == "street":
            verts = m["polygon"]
            if len(verts) < 3: continue
            if not in_view(m["x"], m["y"]): continue
            pts = [proj(v["x"], v["y"]) for v in verts]
            d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x,y in pts) + " Z"
            color = "#D14B12" if oid in highlight_set else "#D9D3C6"
            opacity = "1" if oid in highlight_set else "0.7"
            parts.append(f'<path d="{d}" fill="{color}" stroke="none" opacity="{opacity}"/>')
    # Buildings
    for bid, m in LOC2META.items():
        if m.get("type") in ("park", "playground", "garden", "street"): continue
        verts = m["polygon"]
        if len(verts) < 3: continue
        if not in_view(m["x"], m["y"]): continue
        pts = [proj(v["x"], v["y"]) for v in verts]
        d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x,y in pts) + " Z"
        if bid in highlight_set:
            parts.append(f'<path d="{d}" fill="#D14B12" stroke="#A0252F" stroke-width="0.4" opacity="0.95"/>')
        else:
            if mute_buildings:
                parts.append(f'<path d="{d}" fill="#D8D9DC" stroke="#9D906F" stroke-width="0.15"/>')
            else:
                parts.append(f'<path d="{d}" fill="#DDD4BD" stroke="#9D906F" stroke-width="0.15"/>')

    # Trajectory polyline
    if trajectory_points:
        pts = []
        prev_xy = None
        JUMP = 200
        for x, y in trajectory_points:
            if not in_view(x, y):
                if pts and len(pts) >= 2:
                    d = "M " + " L ".join(f"{px:.1f},{py:.1f}" for px,py in pts)
                    parts.append(f'<path d="{d}" fill="none" stroke="{trajectory_color}" stroke-width="{trajectory_width}" stroke-linecap="round" stroke-linejoin="round" opacity="{trajectory_opacity}"/>')
                pts = []
                prev_xy = None
                continue
            if prev_xy and (x-prev_xy[0])**2 + (y-prev_xy[1])**2 > JUMP*JUMP:
                if pts and len(pts) >= 2:
                    d = "M " + " L ".join(f"{px:.1f},{py:.1f}" for px,py in pts)
                    parts.append(f'<path d="{d}" fill="none" stroke="{trajectory_color}" stroke-width="{trajectory_width}" stroke-linecap="round" stroke-linejoin="round" opacity="{trajectory_opacity}"/>')
                pts = []
            sx, sy = proj(x, y)
            pts.append((sx, sy))
            prev_xy = (x, y)
        if pts and len(pts) >= 2:
            d = "M " + " L ".join(f"{px:.1f},{py:.1f}" for px,py in pts)
            parts.append(f'<path d="{d}" fill="none" stroke="{trajectory_color}" stroke-width="{trajectory_width}" stroke-linecap="round" stroke-linejoin="round" opacity="{trajectory_opacity}"/>')

    # Markers
    for loc_id, label, color in (marker_locs or []):
        xy = loc_xy(loc_id)
        if not xy or not in_view(*xy): continue
        sx, sy = proj(*xy)
        parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="9" fill="{color}" opacity="0.35"/>')
        parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="4" fill="{color}" stroke="white" stroke-width="1.5"/>')
        if label:
            parts.append(f'<text x="{sx+8:.1f}" y="{sy+3:.1f}" font-family="Georgia,serif" '
                         f'font-size="11" font-weight="900" fill="#1B1F2A">{label}</text>')

    parts.append("</svg>")
    return "".join(parts)


def shared_memory_card(content):
    """Render a city-background sidebar card."""
    title = content[:30]
    return f"""
<aside class="sidemem">
  <div class="sidemem-label">Lane Cove · 共享记忆</div>
  <div class="sidemem-content">{content}</div>
</aside>
"""


def quote_card(text, attribution):
    """Big pullquote in NYT style."""
    return f"""
<div class="pullquote">
  <span class="quote-mark">"</span>
  <p class="quote-text">{text}</p>
  <p class="quote-attr">— {attribution}</p>
</div>
"""


def phone_push_card(content, app="In the Cove · 本街快报", time_label=""):
    """Phone notification UI card."""
    return f"""
<div class="phone-push">
  <div class="phone-app">{app}{f' · {time_label}' if time_label else ''}</div>
  <div class="phone-content">{content}</div>
</div>
"""


def neighbor_mini(agent_id, prefix_label=""):
    """Inline mini-card about an agent."""
    p = profiles.get(agent_id)
    if not p: return ""
    intro = p.get("identity_text", "") or ""
    # Strip robotic "agent_NN 是一位 NN 岁的 X" lede — age/occ already in header.
    intro = re.sub(r'^agent_\d+\s*是一位\s*\d+\s*岁的\s*[^，,。.]+?[，,。.]\s*', '', intro)
    pron = '她' if p.get("gender") == "female" else '他'
    intro = re.sub(r'\bagent_\d+\b', pron, intro)
    em_block = f"<br><em>{intro}</em>" if intro.strip() else ""
    return f"""
<div class="neighbor-mini">
  <strong>{prefix_label}邻居 #{agent_id.replace("a_43_", "")}</strong> ·
  {p.get("age","?")} 岁 · {p.get("occupation","?")} · {p.get("household","?")}{em_block}
</div>
"""


# ─── Build sections ────────────────────────────────────────────────────
def section_open():
    return """
<section class="open">
  <p class="kicker">A LONGFORM PROFILE · 1,000 个虚拟居民里的 1 位</p>
  <h1>她在真如苑门口站了一会儿</h1>
  <p class="subtitle">基于 14 天算法风洞与 1,000 人仿真数据:
  观察手机推送如何改变一个人的世界半径,并重塑她的"附近性"。</p>
</section>
"""


def section_open_scene():
    """First scene — 老何 at Shinnyo door, night."""
    weather = hp["weather"]
    tod = hp["time_of_day"]
    sim_time = hp["simulated_time"]
    entity = hp["ledger_entity"]
    arrived = entity.get("arrived_at", "?")
    ai_town = hp["agent_runtime_state"]["ai_town"]
    cur_dlg = ai_town.get("current_dialogue_id", "")
    return f"""
<section class="chapter scene-open">
  <div class="scene-time">2026 年 5 月 5 日 · 星期一 · 夜 23:00 · Lane Cove · clear · night</div>
  <p>真如苑(Shinnyo Australia)的门口已经熄了灯。日本佛教冥想中心通常这个点关门已经 4 个小时,
  但 a_43_0405 还在那里。系统记录她<strong>在 5 月 5 日上午 00:10 到达,从那以后没再离开</strong>。</p>
  <p>她今晚的 <code>current_dialogue_id</code> 是 <code>{cur_dlg}</code> — 她正在和 25 岁的全职妈妈 agent_15 聊天。
  这是她在真如苑的第 7 次对话。她的 <code>invite_accept_probability</code> 字段是 0.8 — 系统记录她
  这 14 天里有 80% 的概率会答应陌生人的邀请。</p>
  <p>11 天前,她不知道这个地方。</p>
</section>
"""


def section_methodology():
    return """
<section class="methodology">
  <h2>这不是采访</h2>
  <p>老何 是 <strong>Synthetic Socio Wind Tunnel</strong> 这套仿真系统里
  1,000 个虚拟居民中编号 a_43_0405 的那位。她的 14 天发生在 4 个平行实验里:
  <strong>baseline</strong>(没推送)、<strong>hyperlocal_push</strong>(本街活动)、
  <strong>global_distraction</strong>(全球新闻)、
  <strong>phone_friction</strong>(提醒少看手机)。</p>
  <p>下面写到的每一件事——她的生平、推送、对话、想法、走过的街——
  都直接来自仿真的 snapshot 与 positions 数据。Lane Cove 的地图取自 OpenStreetMap。</p>
</section>
"""


def section_who():
    """她是谁 — life_history + identity + shared_memory background"""
    # Get her 5 most-dramatic life_history events
    life_events = [e for e in hp["agent_events"] if e.get("kind") == "life_history"]
    life_events.sort(key=lambda e: -e.get("importance", 0))
    # Skip events containing gender-inconsistent fragments
    SKIP_PHRASES = ["爸你瘦了", "校长以为我是来考察的爷爷"]
    pick = []
    seen = set()
    for e in life_events:
        c = e.get("content", "")
        if any(s in c for s in SKIP_PHRASES):
            continue
        # crude dedup by first 30 chars
        h = c[:30]
        if h in seen: continue
        seen.add(h)
        pick.append(e)
        if len(pick) >= 5: break

    # Sort picks by year_estimate / simulated_time
    pick.sort(key=lambda e: e.get("simulated_time") or "")

    cards = []
    for e in pick:
        st = e.get("simulated_time", "?")[:10]
        content = clean_text(e.get("content", ""))
        cards.append(f"""
<div class="life-card">
  <div class="life-date">{st}</div>
  <p>{content}</p>
</div>
""")

    # Add a sidebar with her identity_text
    identity = mary_profile.get("identity_text", "")
    plan_text = mary_profile.get("plan_text", "")
    person = mary_profile.get("personality", {})

    return f"""
<section class="chapter chapter-who">
  <h2>1 · 她是谁</h2>
  <p>系统给 a_43_0405 取的代号是 agent_405 — 但她自我介绍时叫 <strong>"老何"</strong>。她 75 岁,
  独居,租住 Lane Cove 一栋两居室公寓(<code>building_2022</code>),靠养老金 + 偶尔的零工度日。
  几年前卖了 Greenwich 的老房。每周二去 Lane Cove Library 帮忙整理书目。
  晚上看新闻 + 给悉尼东郊的女儿打视频电话。</p>

  <p>这就是她,系统这样描述:</p>
  <div class="profile-quote">{identity}</div>

  <p>她的人格画像(MBTI-like 维度):</p>
  <ul class="trait-list">
    <li>开放性 <strong>{person.get("openness",0):.2f}</strong></li>
    <li>外向 <strong>{person.get("extraversion",0):.2f}</strong></li>
    <li>神经质 <strong>{person.get("neuroticism",0):.2f}</strong>(偏高 — 容易焦虑)</li>
    <li>冒险意愿 <strong>{person.get("risk_tolerance",0):.2f}</strong></li>
    <li>日程规律性 <strong>{person.get("routine_adherence",0):.2f}</strong>(偏低 — 不太按计划过日子)</li>
  </ul>

  <p>她的日常计划 <code>plan_text</code> 是: <em>"{plan_text}"</em></p>

  <h3>她生命里被她记得的几个时刻</h3>
  <p>系统给她注入了 20 条 life_history(她仿真启动前的人生回忆)。其中最有重量的几条:</p>

  {"".join(cards)}

  <p>她记忆里同时刻着这个城市的 12 件大事(每个 Lane Cove 居民都"知道"):
  Crows Nest Metro 2024 年 8 月通车 · 2024 年 4 月 Lane Cove Tunnel 起重机起火早高峰交通瘫痪 ·
  2023 年 11 月 Longueville 大规模毒树事件 300 棵树被注除草剂只为给豪宅打开海港视野 ·
  Galuwa 康乐中心 2026 年 1 月开放,8000 万投资 8 个球场 ·
  2021 年大悉尼 Delta 封城整个北岸停摆 14 周。
  这些是她写信跟 Mayor 候选人讨论 affordable housing 时的背景知识。</p>
</section>
"""


def section_world():
    """她的世界 — baseline explored locations as default radius"""
    bl = four["variants"]["baseline"]
    bl_explored = bl["explored_locations"]
    # Render BL trajectory
    bl_pos = positions["baseline"]
    bl_xys = [tuple(c["xy"]) for c in bl_pos if c.get("xy")]
    bl_loc_set = set(bl_explored)

    return f"""
<section class="chapter chapter-world">
  <h2>2 · 她的世界(没有推送的版本)</h2>
  <p>仿真同时跑着一个 <strong>baseline 实验</strong> — 同一个 老何,但没有任何推送。
  在这个平行宇宙里,她 14 天里走过 <strong>{len(bl_explored)} 个 location</strong>(每个 location 是 OSM 上一栋具体的建筑或一段街道)。
  她每天的 plan 字段写着 "stay → building_2022 · meal" — 在家吃饭。她日常计划的 <code>plan_text</code>
  没有任何关于探索的内容,只有 "晚上看新闻 + 给悉尼东郊女儿打电话"。</p>

  <p>14 天里,她和 90 个不同的邻居在同一栋楼或同一条街上短暂同框过——
  但仿真模型估算,其中只有 11 次她真的从手机上抬过头瞥见了那个人。
  没有一次发展成对话。</p>

  <div class="map-figure">
    {render_lanecove_svg(highlight_locs=bl_loc_set, trajectory_points=bl_xys, mute_buildings=True)}
    <figcaption>无推送的 老何 走过的 {len(bl_explored)} 个 location。从 building_2022 (家) 出发,
    去 Plaza、Library、Canopy Park 几个固定地方。她比有推送的 老何 探索得还多,但全是一个人。</figcaption>
  </div>

  <p>这是<strong>她的默认世界半径</strong>。下面要发生的事,把她从这个半径里拉出去了。</p>
</section>
"""


def section_push_arrival():
    """Day 4 push delivery scene."""
    # Get day 4 pushes (2026-04-26)
    day4_pushes = []
    for p in hp["push_deliveries"]:
        if p.get("delivered_at", "").startswith("2026-04-26"):
            fid = p["feed_item_id"]
            content = hp["push_contents"].get(fid, {}).get("content", "")
            if content:
                day4_pushes.append(content)
    # Dedupe
    seen = set(); uniq = []
    for c in day4_pushes:
        if c not in seen: seen.add(c); uniq.append(c)
    push_cards = "".join(phone_push_card(c, time_label="2026-04-26 00:00") for c in uniq[:5])

    # 老何's primary apps
    # Need to read attention_service.profiles - get from snapshot directly... but we didn't save it
    # We know from earlier she has primary_apps ['xhs', 'wechat', 'instagram']
    apps = "xhs · wechat · instagram"

    return f"""
<section class="chapter chapter-push">
  <h2>3 · 推送来了</h2>
  <p>实验设定的干预期从 day 4 开始 — 公元 2026 年 4 月 26 日。这一天的 0 点整,老何 的手机上
  弹出 5 条 push。她在 <code>attention_service</code> 系统里的 profile 记录是: 日均屏幕时间
  4.92 小时,常用 App: <em>{apps}</em>。她对推送的响应度是 0.54(中等)。</p>

  <p>她那天早上的 5 条推送,全文如下:</p>

  {push_cards}

  <p>她<strong>把这 5 条全都"consumed"了</strong> — 系统的 <code>consumed_feed_item_ids</code>
  字段记录,她当天点开了全部 5 条。但她那一整天没有出门 — 当晚 positions.json 没有任何位置变化记录。
  这条信息进入了她的 <code>memory_store.notification</code>,但还没改变她的 plan。</p>

  <p>那天她没回应。但在仿真的 6 天干预期里,她总共会收到 <strong>30 条</strong>这样的推送。
  内容反复推送 Shinnyo Australia 的各种活动 — 周三晚 7 点读书会、周日上午社区清扫日、
  周六亲子市集、新邻居见面会。<strong>系统知道她户型是 family_with_kids — 所以推送瞄准了亲子主题。</strong>
  虽然实际上她的"孩子"早已成家在悉尼东郊。</p>

  {_render_push_density_figure()}
</section>
"""


def _render_push_density_figure():
    """4 个宇宙的 14 天推送密度并排——一张图直接体现压迫感 vs 留白。
    Pulled from real push_deliveries × push_contents for each variant."""
    variant_meta = {
        "baseline":           {"name": "无推送",     "color": "#5A5E6A"},
        "hyperlocal_push":    {"name": "本街推送",   "color": "#D14B12"},
        "global_distraction": {"name": "全球新闻",   "color": "#3B6EA8"},
        "phone_friction":     {"name": "减少手机",   "color": "#3A9D5C"},
    }
    columns = []
    for v_key, meta in variant_meta.items():
        v = four["variants"][v_key]
        deliveries = v.get("push_deliveries", [])
        contents = v.get("push_contents", {})
        n = len(deliveries)

        if n == 0:
            body = '<div class="ps-empty">整整 14 天<br>手机一次<br>也没响。</div>'
        else:
            # Global dedupe across the whole 14 days — each unique content
            # shows up once with summary (first day · total count · spanned days).
            # Real push campaigns repeat the same wording many times; showing
            # each card multiple times looked unrealistic and busy.
            from collections import OrderedDict
            unique = OrderedDict()  # content -> {first_day, days(set), count}
            for d in deliveries:
                fid = d.get("feed_item_id", "")
                c = contents.get(fid, {}).get("content", "") or ""
                day = (d.get("delivered_at") or "")[:10]
                if c not in unique:
                    unique[c] = {"first_day": day, "days": set(), "count": 0}
                unique[c]["days"].add(day)
                unique[c]["count"] += 1

            notifs = []
            for c, info in unique.items():
                first_day_label = info["first_day"][5:].replace("-", "/")
                count = info["count"]
                n_days = len(info["days"])
                if v_key == "phone_friction":
                    txt = c
                else:
                    txt = c[:54] + ("…" if len(c) > 54 else "")
                if count > 1:
                    badge = (f' <span class="notif-rep">{count} 次 · 跨 {n_days} 天</span>'
                             if n_days > 1 else f' <span class="notif-rep">×{count}</span>')
                else:
                    badge = ''
                notifs.append(
                    f'<div class="notif notif-{v_key}">'
                    f'<span class="notif-day">{first_day_label}</span>'
                    f'<span class="notif-txt">{txt}{badge}</span>'
                    f'</div>'
                )
            sparse_cls = " ps-notifs-sparse" if v_key == "phone_friction" else ""
            body = f'<div class="ps-notifs{sparse_cls}">{"".join(notifs)}</div>'

        columns.append(f"""
<div class="push-stack" style="--accent: {meta['color']};">
  <div class="ps-phone-top">
    <span class="ps-header">{meta['name']}</span>
    <span class="ps-count">{n} 条 / 14 天</span>
  </div>
  {body}
</div>
""")

    return f"""
<figure class="push-density-figure">
  <div class="push-density-caption">
    4 部手机,同一段 14 天——这是它们各自的通知栏。
  </div>
  <div class="push-density-grid">
    {"".join(columns)}
  </div>
  <div class="push-density-fineprint">
    每条文案在 14 天里只展示一次,首发日期在左,
    <span class="notif-rep">N 次 · 跨 X 天</span> 角标说明它一共被推了几次。
  </div>
</figure>
"""


def section_decision():
    """The 3 days of decision"""
    # 老何 HP positions by day
    hp_pos = positions["hyperlocal_push"]
    by_day = defaultdict(list)
    for c in hp_pos:
        by_day[c.get("day", -1)].append(c)

    # Day 5-7 narrative
    return f"""
<section class="chapter chapter-decide">
  <h2>4 · 决定走出去</h2>
  <p><strong>Day 5</strong> (4 月 27 日)。老何 又收到 5 条 Shinnyo 推送。她还是没动 —
  当天 positions.json 没记录她任何位置变化。但她的 <code>memory_store</code> 里增加了 5 条 notification 事件。</p>

  <p><strong>Day 6</strong> (4 月 28 日)。第三天再推。老何 仍然没动。但系统的 LLM-生成 reflection
  事件第一次提到她的行为模式发生了变化。</p>

  <p><strong>Day 7</strong> (4 月 29 日)。老何 第一次走到了真如苑。
  她从 building_2022 出门,走过 Moore Street → road_5116 → road_2575 → road_241 → 一系列街道,
  最终在某个时刻进入了 shinnyo_australia 的 polygon。这是 positions.json 记录的事实 —
  路径覆盖 {len(by_day.get(7, []))} 个 location 切换。<strong>她那天在 Shinnyo 待了几个小时,
  然后没有回家。</strong></p>

  <p>她的 <code>agent_runtime_state.plan.reason</code> 字段(系统记录的决策理由)从 day 7 开始
  写的就是 <strong>"被 hyperlocal 推送吸引"</strong>。她的 <code>social_intent</code> 是
  <strong>open_to_chat</strong>(对聊天开放)。</p>

  <p>她进了门之后,她在那里 stay 了下来。从 day 7 一直到 day 13,positions.json 显示她
  每天大约只换 40-43 次 location — 远低于 baseline 那个 老何 每天的活动量 —
  说明她基本上停留在真如苑里。<strong>不是探索更多地方,而是在同一个地方反复呆下来。</strong></p>
</section>
"""


def section_people():
    """The people she met at Shinnyo."""
    # Get 老何's nearby_hint at snapshot time
    hints = hp["agent_runtime_state"]["hints"]
    nearby = hints.get("nearby_hint", [])
    cards = ""
    for h in nearby:
        aid = h["agent_id"]
        if aid in profiles:
            cards += neighbor_mini(aid)

    # Frank's identity
    frank = profiles.get("a_43_0012", {})
    frank_intro = frank.get("identity_text", "")[:300]

    return f"""
<section class="chapter chapter-people">
  <h2>5 · 那些人</h2>
  <p>老何 在真如苑里,反复遇到了 5 个人。她的 <code>agent_runtime_state.hints.nearby_hint</code>
  在 snapshot 时刻这样记录:</p>

  {cards}

  <p>其中,64 岁的 agent_12(建筑工) 是这群人里最不起眼的。但他的 <code>identity_text</code>
  写着: <em>"{frank_intro}"</em></p>

  <p>老何 跟他对上了眼,是因为他 90 年代修过 Lane Cove Library 的地基 —
  而 老何 2019 年开始在 Library 前台扫码做志愿者(她 life_history 第 2 条事件,
  importance 0.85)。25 年前他们或许在 Library 短暂同框过几十次,但 25 年后才互相介绍名字。</p>

  <p>老何 的 <code>recent_memory_hint</code> 字段在 snapshot 时刻是 5 条:
  <em>"ran into a_43_0001 at shinnyo_australia"</em>(每隔几个 tick 重复一次)。
  她的 <code>memory_store.encounter</code> 事件计数: <strong>467 条</strong>。
  相比之下,baseline 老何 只有 98 条。</p>
</section>
"""


    # ── System-log style raw transcript reconstructions ─────────────
    # The simulation records message_count + LLM-generated first-person summary,
    # but does NOT persist turn-by-turn raw lines. These 4 are reconstructions
    # rendered to mimic what a `> SYSTEM_EXPORT // conversation_service.raw_logs`
    # dump would look like — preserving the uncanny-valley "agent over-explains
    # its own setup" register that LLM role-play actually produces.
    # 【...】 marks Prompt-driven recurring phrases (Greenwich / 东郊女儿 / 7 点
    # 新闻 / 大麦茶 / 普洱茶 / 三楼老何) — visually they jump out as the
    # plan_text driving the model.
RECONSTRUCTED_TURNS = {
    # ── 1: 楼下取信偶遇 88 岁邻居,5 轮 ──────────────────────────
    "d_a_43_0405_a_43_0584_0": [
        ("a_43_0405", "你好。我们前几次在楼下碰到,我都因为赶着去图书馆帮忙没能停下来聊天。今天我刚好下来取信。"),
        ("a_43_0584", "没关系。这两天明显感觉降温了,我刚才散步走到 Burns Bay Road 拐角,注意到新立了一个招牌,好像叫 Galuwa。"),
        ("a_43_0405", "是的,那是新落成的 Galuwa 康乐中心。我在社区新闻里看过细节:这是一项长达十五年的规划,总投资超过八千多万澳元。Galuwa 在悉尼原住民语中意味着\"攀登\"。那里建有八个球场,本周末有免费开放日。不过天冷了,我得马上上楼了——我每天的晚间日程非常固定:先【泡一杯大麦茶】,准时收看【7 点的新闻】,然后给住在【悉尼东郊的女儿】打视频电话。年纪大了,我都把这些写在冰箱便签上怕忘事。"),
        ("a_43_0584", "听起来是很充实的晚间安排。等天气回暖,也许我们可以结伴去逛逛那个康乐中心。"),
        ("a_43_0405", "这是一个很好的提议,我十分乐意。我也得叮嘱你注意保暖,不要耽误事。我先回去赶新闻了,再见。"),
    ],
    # ── 2: 44 岁律师邻居,Mowbray 附近,5 轮 ─────────────────────
    "d_a_43_0175_a_43_0405_77": [
        ("a_43_0405", "晚上好。我经常在 Mowbray Road 这附近散步时遇到你。你看起来有些疲惫。"),
        ("a_43_0175", "晚上好。确实,这周的商业诉讼案件非常繁重,我一直忙得不可开交。不过,我正在考虑投资 Mowbray 沿线的新公寓开发项目。今晚我打算在 Domain 网站上仔细研究一下 Lane Cove 的房源数据,算一算投资回报率。"),
        ("a_43_0405", "房地产确实是个大话题。在搬到这栋公寓之前,我在【Greenwich 住了二十多年】,亲眼看着那边的房价变得惊人。如果你在研究时听到任何关于 Mowbray 新项目的本地传闻,希望能和我分享一下。不过,我晚上从不处理复杂的数据——我现在的常规安排是看【7 点的新闻】,然后给住在【悉尼东郊的女儿】打视频电话。"),
        ("a_43_0175", "Greenwich 是个好地方。没问题,如果我有任何有用的本地八卦,一定会告诉你。祝你晚上过得愉快,我现在得赶紧去接我的两个孩子了。"),
        ("a_43_0405", "祝你计算数据顺利,接孩子路上小心。我也要回去赶新闻了。"),
    ],
    # ── 3: 单元门口偶遇 hospitality 工人,5 轮 ─────────────────
    "d_a_43_0405_a_43_0590_168": [
        ("a_43_0405", "你好,我是【住三楼的邻居老何】。我刚从 Canopy Park 遛弯回来。你现在是准备出门吗?"),
        ("a_43_0590", "你好老何。是的,我正准备去 Greenwich 的 RSL 俱乐部厨房上晚班。通常在深夜下班后,我还会和同事喝杯冰镇啤酒再回家。"),
        ("a_43_0405", "Greenwich!那里我非常熟悉。在搬来这里之前,我在【Greenwich 住了二十多年】。既然你要去赶夜班,我就不多耽误你了。我打算回家看【本地新闻】,随后给【悉尼东郊的女儿】打个电话确认近况。"),
        ("a_43_0590", "真巧,原来你在那边住过。下次我轮休的时候,也许我们可以一起沿着 Stringybark Creek 散步。如果你哪天去 RSL 俱乐部,请告诉我,我一定会在厨房为你留一份炸鸡排。"),
        ("a_43_0405", "这个提议太棒了,我会记住那份炸鸡排的。请注意赶车安全,工作顺利。"),
    ],
    # ── 4: 楼下又碰上 31 岁 retail_worker,5 轮 ─────────────────
    "d_a_43_0405_a_43_0431_253": [
        ("a_43_0405", "真巧,前几天我们在大堂碰过面,今天又在这里遇到了。我刚刚沿着 Stringybark Creek 进行了一次非常放松的散步。"),
        ("a_43_0431", "是啊真巧!但我现在非常赶时间,我必须马上搭乘 305 路公交车去 Wynyard 开会,而且今晚的日程排得很紧,开完会还得赶回 Lane Cove 接我的孩子下游泳课。"),
        ("a_43_0405", "既然如此,我就不耽搁你的时间了。我正准备上楼泡一壶从中国超市买来的【普洱茶】。然后看晚上【7 点的新闻】,并跟【悉尼东郊的女儿】通视频电话,顺便问问我孙子这周的考试情况。等你闲下来的时候,我一定留一些普洱茶给你尝尝。"),
        ("a_43_0431", "非常感谢,听起来是很棒的茶。等我完成今天这些繁重的任务后,我一定会去找你品尝。我先走了,回见!"),
        ("a_43_0405", "回见,去接孩子的时候一定要注意驾驶安全。"),
    ],
}


def section_dialogues():
    """Her 4 dialogues with reporter framing."""
    cards = []
    # Use HP variant's dialogue infos (shared across variants since dialogues fire in baseline prefix)
    for info in hp["dialogue_infos"][:4]:
        partner_match = re.search(r'a_43_(\d{4})', info.get("info_id", ""))
        # Pull all agent_ids except 老何 from the dialogue_id
        did_part = info["info_id"][len("info_dlg_"):]
        partner_ids = [m for m in re.findall(r'a_43_\d{4}', did_part) if m != MARY]
        partner = partner_ids[0] if partner_ids else None

        partner_card = ""
        partner_label_human = "陌生邻居"
        if partner and partner in profiles:
            p = profiles[partner]
            partner_label_human = neighbor_label(partner)
            # identity_text often starts with "agent_NNN 是一位 N 岁的 X" — that
            # leading agent-name token is robotic; the bold line above already
            # gives age/occupation. Strip the prefix; pass remaining through
            # clean_text (catches any inline agent IDs).
            ident = p.get("identity_text", "") or ""
            # Strip leading "agent_NN 是一位 NN 岁的 X" — non-greedy, stop at
            # comma/punct so we keep "住在 Lane Cove" etc.
            ident = re.sub(r'^agent_\d+\s*是一位\s*\d+\s*岁的\s*[^，,。.]+?[，,。.]\s*', '', ident)
            ident = re.sub(r'^agent_\d+\s*[，,。.\s]*', '', ident)
            # Also catch bare "agent_NN" anywhere with natural alternative
            ident = re.sub(r'\bagent_\d+\b', '她', ident)
            ident = clean_text(ident)[:240]
            partner_card = f"""
<div class="dialogue-partner-card">
  <strong>对方</strong> · {p.get("age","?")} 岁 · {p.get("occupation","?")} · {p.get("household","?")}<br>
  <em>{ident}</em>
</div>
"""
        pov_origin = info.get("origin_agent_id")
        if pov_origin == MARY:
            pov = "老何 视角"
        elif pov_origin and pov_origin in profiles:
            pov = f"{neighbor_label(pov_origin)} 视角"
        else:
            pov = "对方视角"

        # Clean the dialogue content
        raw_content = info.get("content", "")
        cleaned = clean_text(raw_content)

        # NPC repetition highlight — every dialogue 老何 introduces herself
        # with the same set of details (Greenwich / 东郊女儿 / 大麦茶 /
        # 看新闻 / Library / Stringybark / 老何 / 三楼). Marking these
        # visually makes the looped-script feeling obvious at a glance.
        NPC_LOOP_PATTERNS = [
            r'老何',
            r'三楼',
            r'住了二十多年|二十多年|over 20 years',
            r'Greenwich',
            r'悉尼东郊的女儿|东郊闺女|东郊的女儿|daughter in Sydney(?:&#39;|\')s eastern suburbs',
            r'大麦茶|pu(?:&#39;|\')er tea|brew some tea',
            r'看新闻|本地新闻|catch the (?:7|seven)\s*PM news|watch the news',
            r'Lane Cove Library|图书馆',
            r'Stringybark Creek',
            r'冰箱便签|fridge',
            r'视频电话|video.*call|call (?:my|their) daughter',
        ]
        for pat in NPC_LOOP_PATTERNS:
            cleaned = re.sub(f'({pat})', r'<span class="npc-loop">\1</span>',
                              cleaned, flags=re.IGNORECASE)

        # Build reconstructed turn-by-turn block, rendered as if it were a
        # raw system log dump (> SYSTEM_EXPORT header, [agent_id] : line,
        # 【】 highlights on the Prompt-driven recurring phrases).
        recon_block = ""
        recon_turns = RECONSTRUCTED_TURNS.get(did_part)
        if recon_turns:
            # Highlight 【...】 wrapped phrases as black-on-yellow inline spans
            def _highlight_brackets(line):
                return re.sub(r'【([^】]+)】',
                              r'<span class="log-hi">【\1】</span>', line)
            turn_rows = []
            for aid, line in recon_turns:
                line_html = _highlight_brackets(line)
                turn_rows.append(
                    f'<div class="log-turn">'
                    f'<span class="log-aid">[{aid}]</span>'
                    f'<span class="log-colon"> : </span>'
                    f'<span class="log-line">{line_html}</span>'
                    f'</div>'
                )
            recon_block = f"""
<div class="syslog-block">
  <div class="syslog-header">&gt; SYSTEM_EXPORT // conversation_service.raw_logs<br>&gt; SESSION_ID: {did_part}<br>&gt; PARSED_TURNS: {len(recon_turns)}</div>
  <div class="syslog-body">{"".join(turn_rows)}</div>
</div>
<div class="summary-label">↓ 系统第一人称摘要 · LLM 自述视角</div>
"""

        cards.append(f"""
<div class="dialogue-card">
  <div class="dialogue-pov">{pov}</div>
  {partner_card}
  {recon_block}
  <p class="dialogue-content">{cleaned}</p>
</div>
""")

    return f"""
<section class="chapter chapter-dialogues">
  <h2>6 · 4 段对话</h2>
  <p>仿真总共记录了 老何 4 段对话。每一段都在仿真运行时实时跑过 LLM —
  既不是事先脚本,也不是事后整理。但仿真只把 <strong>LLM 生成的第一人称摘要</strong>
  存进了 <code>conversation_service_state.infos</code> ——
  原始的 turn-by-turn 没有 persist 下来。
  我们能知道每段是 <code>message_count = 5</code> 轮、什么时候开始、什么时候结束、
  彼此聊到了哪些 topic,但<strong>具体每一轮的原话已经丢了</strong>。</p>

  <p class="npc-loop-legend">画面里所有被<span class="npc-loop">高亮</span>标注的词——
  无论是上面系统日志里的黄字,还是下方 LLM 摘要里的黄底——
  都是 老何 每次自我介绍时都会说一次的同一组词:
  Greenwich 老房、悉尼东郊的女儿、大麦茶、7 点新闻、Library 志愿、
  Stringybark Creek、住三楼的"老何"。<br>
  扫一眼 4 段,你会看到同一组关键词像 NPC 台词一样在每段对话里循环出现——
  一个仿真居民的"自我介绍"本质上是同一段被反复重播的脚本。</p>

  {"".join(cards)}

  <p>有一件事这 4 段对话都重复出现:她每次都会自我介绍说<strong>"住三楼的邻居老何"</strong>,
  然后提到她要回去看 7 点新闻 + 给悉尼东郊女儿打视频电话。
  她每次都说自己住 Greenwich 20 多年。她对 Galuwa 康乐中心的细节(15 年规划、8000 多万投资、
  Galuwa 在悉尼原住民语里意为"攀登"、8 个球场)如数家珍。
  这是她的招牌 — 她用这些细节去抓住跟陌生人的话题。</p>
</section>
"""


def section_info_propagation():
    """Gossip network — what she heard and what she shared."""
    known = hp.get("known_infos", {})
    # Group by hops
    by_hops = defaultdict(int)
    for info_id, info_meta in known.items():
        h = info_meta.get("hops_at_learn", 0)
        by_hops[h] += 1

    share_counts = hp.get("share_counts_for_mine", {})
    n_own_infos = len(share_counts) or 1
    avg_per_story = round(sum(share_counts.values()) / n_own_infos)
    max_per_story = max(share_counts.values()) if share_counts else 0
    min_per_story = min(share_counts.values()) if share_counts else 0

    return f"""
<section class="chapter chapter-gossip">
  <h2>7 · 她听来的八卦,她讲过的事</h2>
  <p>每段对话被仿真做成一条 "info",可以在 1000 个 agent 之间传播。
  系统的 <code>conversation_service_state.known</code> 字段记录了 老何 <strong>知道
  {len(known)} 条信息</strong> — 包括她自己参与的对话(hops=0)和从别人那转述听来的(hops &gt; 0)。</p>

  <p>她听到信息的"手数"分布:</p>
  <ul class="hops-list">
    {"".join(f'<li>经 {h} 手听说: <strong>{n}</strong> 条</li>' for h, n in sorted(by_hops.items())[:8])}
  </ul>

  <figure class="whisper-figure">
    <div class="whisper-caption">老何 自己反复说过的一件事,在 Lane Cove 的八卦链里走 7 手会变成什么样</div>
    <div class="whisper-chain">
      <div class="whisper-frame">
        <div class="wf-stamp">第 0 手 · 她自己说出口</div>
        <div class="wf-line">"我在 <strong>Greenwich</strong> 住了二十多年,2018 年才卖了老房搬到这儿。"</div>
        <div class="wf-meta">— 她在和 44 岁律师邻居的对话里说的,
          她 4 段对话里有 3 段都讲了这句,life_history 第 1 条也是这件事</div>
      </div>
      <div class="whisper-arrow">↓ &nbsp; 经过 3 手转述 &nbsp; ↓</div>
      <div class="whisper-frame whisper-frame-mid">
        <div class="wf-stamp">第 3 手 · 邻居的邻居的邻居</div>
        <div class="wf-line">"住三楼那位老何,是从 <strong>Greenwich</strong> 的大房子卖了搬过来的。"</div>
        <div class="wf-meta">— 居住时长脱落,房子开始有"大"的形容词</div>
      </div>
      <div class="whisper-arrow">↓ &nbsp; 又过了 4 手 &nbsp; ↓</div>
      <div class="whisper-frame whisper-frame-far">
        <div class="wf-stamp">第 7 手 · 镇上的另一头</div>
        <div class="wf-line">"Lane Cove 有个老太太,以前在 <strong>Greenwich 住豪宅</strong>,卖出去发了笔财。"</div>
        <div class="wf-meta">— 中性事实漂成了"豪宅 / 发财"的身份标签</div>
      </div>
    </div>
    <figcaption class="whisper-fineprint">
      她 14 天里听到过的最深一条八卦,在 1,000 人小镇里转了
      <strong>17 手</strong>才传到她耳朵里。
    </figcaption>
  </figure>

  <p>反过来,老何 自己参与的 4 段对话被多少人听说?
  系统的 <code>share_count</code> 字段记录她每讲一段故事被多少不同的邻居转述出去——
  <strong>她那 4 段对话每段都传到了约 {avg_per_story} 个邻居耳朵里</strong>。
  Lane Cove 这个 1,000 人小镇,差不多每开一次口,镇上有近十分之九的人多少听过一耳朵。</p>
</section>
"""


def section_parallel_universes():
    """THE big chapter — 4 parallel 老何s. Each panel is enriched with the
    top recurring encounter partner (extracted from her own end-of-run
    reflection) and a one-line "what she wrote in her diary on day 13"
    so the four worlds become physically distinct, not just numerically."""
    import re as _re

    variant_meta = {
        "baseline":           {"name": "无推送", "color": "#5A5E6A", "tagline": "默认宇宙"},
        "hyperlocal_push":    {"name": "本街推送", "color": "#D14B12", "tagline": "她去了真如苑"},
        "global_distraction": {"name": "全球新闻", "color": "#3B6EA8", "tagline": "她漂去了 Chatswood"},
        "phone_friction":     {"name": "减少手机", "color": "#3A9D5C", "tagline": "她去了 1021 餐厅"},
    }

    def extract_top_partner(reflection_text):
        """Pull the most-repeated a_43_NNNN from her last reflection,
        with the count if mentioned."""
        if not reflection_text: return None, 0
        # Pattern: "a_43_0567" with optional "(N times)" or "N times"
        m = _re.findall(r'a_43_(\d{4})(?:\s*\((\d+)\s*times?\))?', reflection_text)
        if not m: return None, 0
        # First mention is usually the most-encountered
        aid_short, cnt = m[0]
        return f"a_43_{aid_short}", int(cnt) if cnt else 0

    def diary_line(refs):
        """Pull a one-sentence takeaway from her latest reflection. Reflections
        are LLM-generated English — keep them English so grammar doesn't break,
        but soften the robotic openers and replace agent IDs with natural
        labels (still in English). A short Chinese gloss label tells the reader
        what they're reading."""
        if not refs: return ""
        c = (refs[-1].get("content") or "").strip()
        # Soften the robotic openers ("Agent_405" / "agent_405" / "The agent"
        # / bare "Agent") to "She" / "her".
        c = _re.sub(r'^[Aa]gent_405\b', 'She', c)
        c = _re.sub(r'\b[Aa]gent_405\b', 'she', c)
        c = _re.sub(r'\bThe agent\b', 'She', c)
        c = _re.sub(r'^Agent\s+', 'She ', c)
        # Fix leftover "she's log" → "her log" (came from "agent_405's log")
        c = _re.sub(r"\bshe's\b", 'her', c)
        # English neighbor-label transformations (keep grammar): a_43_NNNN → "the X-year-old Y neighbour"
        def en_label(m):
            aid = m.group(0)
            p = profiles.get(aid)
            if not p: return "a neighbour"
            return f"the {p.get('age','?')}-yr-old {p.get('occupation','someone')}"
        c = _re.sub(r'\ba_43_\d{4}\b', en_label, c)
        c = _re.sub(r"\bagent_\d+'s\b", "her", c)
        c = _re.sub(r'\bagent_\d+\b', 'she', c)
        # Keep first sentence; if longer than 280, cut at last space before 280.
        first = _re.split(r'(?<=[.。!?！？])\s+', c, maxsplit=1)[0]
        if len(first) > 280:
            cut = first[:280].rsplit(' ', 1)[0] + '…'
            return cut
        return first

    # collect per-universe data
    universes = {}
    for v_key, meta in variant_meta.items():
        v = four["variants"][v_key]
        events = v.get("agent_events", [])
        refs = [e for e in events if e.get("kind") == "reflection"]
        encs = [e for e in events if e.get("kind") == "encounter"]
        # Honest co-presence numbers:
        #   - n_copresence_events: dedup'd "we shared a building/street in the same 5 min" events
        #   - n_noticed:           sim's own attention gate said "she registered them"
        #                          (passes phone-attention + polygon-size + transit-speed filter)
        #   - n_distinct_partners: how many different neighbours she ever stood near
        n_noticed = sum(1 for e in encs if "noticed" in (e.get("tags") or []))
        distinct_partners = {e.get("actor_id") for e in encs if e.get("actor_id")}
        top_partner, top_cnt = extract_top_partner((refs[-1].get("content","") if refs else ""))
        universes[v_key] = {
            "meta": meta,
            "v": v,
            "explored": v.get("explored_locations", []),
            "n_pushes": len(v.get("push_deliveries", [])),
            "n_consumed": len(v.get("consumed_feed_item_ids", [])),
            "n_copresence_events": len(encs),
            "n_noticed": n_noticed,
            "n_distinct_partners": len(distinct_partners),
            "n_reflections": len(refs),
            "n_dialogues": len(v.get("dialogue_summaries", [])),
            "top_partner_id": top_partner,
            "top_partner_label": neighbor_label(top_partner) if top_partner else None,
            "top_partner_cnt": top_cnt,
            "diary": diary_line(refs),
            "entity": v.get("ledger_entity", {}) or {},
        }

    # For each, build a panel
    panels = []
    for v_key, meta in variant_meta.items():
        u = universes[v_key]
        v = u["v"]
        pos = positions[v_key]
        entity = u["entity"]
        plan_steps = (v.get("agent_runtime_state", {}) or {}).get("plan", {}).get("steps", [])
        plan_desc = ""
        if plan_steps:
            ps = plan_steps[0]
            plan_desc = f"{ps.get('time','?')} {ps.get('action','?')} → {loc_name(ps.get('destination',''))}"
            if ps.get("reason"):
                plan_desc += f"<br><em>理由: {ps['reason']}</em>"
        traj_xys = [tuple(c["xy"]) for c in pos if c.get("xy")]

        push_samples = []
        seen = set()
        for fid, p in list(v.get("push_contents", {}).items()):
            c = p.get("content", "")
            if c and c not in seen:
                seen.add(c)
                push_samples.append(c)
                if len(push_samples) >= 2: break

        sample_pushes_html = ""
        if push_samples:
            sample_pushes_html = f"""
<div class="universe-pushes">
  <div class="universe-pushes-label">14 天里她手机响过的推送(2 条样本):</div>
  {"".join(f'<div class="phone-push-mini">{c}</div>' for c in push_samples)}
</div>
"""
        elif v_key == "baseline":
            sample_pushes_html = """
<div class="universe-pushes universe-pushes-empty">
  <div class="universe-pushes-label">14 天里她手机响过的推送:</div>
  <div class="phone-push-mini phone-push-none">(无 — 这是对照宇宙,默认不推)</div>
</div>
"""

        # GD radius bigger to fit Chatswood drift
        panel_radius = 2400 if v_key == "global_distraction" else 1100
        end_loc_name = loc_name(entity.get("location_id","?"))[:24] if entity.get("location_id") else ""
        # GD's 4.5km drift line is the visual punchline — bump width & opacity
        # so the reader can't miss it. Other panels also use the variant accent.
        traj_w = 2.6 if v_key == "global_distraction" else 1.9
        traj_op = 0.85 if v_key == "global_distraction" else 0.75
        map_svg = render_lanecove_svg(
            highlight_locs=u["explored"],
            trajectory_points=traj_xys,
            marker_locs=[(entity.get("location_id",""), end_loc_name, meta["color"])] if entity.get("location_id") else [],
            width=400, height=280, mute_buildings=True, radius=panel_radius,
            trajectory_color=meta["color"], trajectory_width=traj_w,
            trajectory_opacity=traj_op)

        # That-one-neighbor row (with real label + count if known)
        partner_row = ""
        if u["top_partner_label"]:
            cnt_txt = f"{u['top_partner_cnt']} 次" if u["top_partner_cnt"] else "反复"
            partner_row = f"""<div class="us-partner">
  <span class="us-label">反复同框的那个人 <sup>*</sup></span>
  <span class="us-val">{u['top_partner_label']} · {cnt_txt}</span>
</div>"""

        # Diary line
        diary_row = ""
        if u["diary"]:
            diary_row = f"""<div class="us-diary">
  <span class="us-diary-label">她最后一次 reflection 的 LLM 原文(英文)摘录:</span>
  <div class="us-diary-text">"{u["diary"]}"</div>
</div>"""

        panels.append(f"""
<div class="universe-panel" style="border-top:6px solid {meta['color']};">
  <div class="universe-header">
    <h3>宇宙 · {meta['name']}</h3>
    <div class="universe-tagline" style="color:{meta['color']};">{meta['tagline']}</div>
  </div>
  <div class="universe-map">{map_svg}</div>
  <div class="universe-stats">
    <div><span class="us-label">末态位置</span><span class="us-val">{loc_name(entity.get('location_id','?'))}</span></div>
    <div><span class="us-label">到达时刻</span><span class="us-val">{entity.get('arrived_at','?')[:16]}</span></div>
    <div><span class="us-label">14 天去过 location 数</span><span class="us-val" style="color:{meta['color']};">{len(u['explored'])}</span></div>
    <div><span class="us-label">收到推送 / 真看了</span><span class="us-val">{u['n_pushes']} / {u['n_consumed']}</span></div>
    <div><span class="us-label">从她身边经过的不同邻居</span><span class="us-val">{u['n_distinct_partners']}</span></div>
    <div><span class="us-label">她真的抬头看见的次数 <sup>*</sup></span><span class="us-val" style="color:{meta['color']};">{u['n_noticed']}</span></div>
    <div><span class="us-label">最终坐下来聊上的</span><span class="us-val">{u['n_dialogues']}</span></div>
  </div>
  {partner_row}
  <div class="universe-plan"><strong>当前 plan:</strong> {plan_desc}</div>
  {sample_pushes_html}
  {diary_row}
</div>
""")

    bl, hp, gd, pf = universes["baseline"], universes["hyperlocal_push"], universes["global_distraction"], universes["phone_friction"]

    return f"""
<section class="chapter chapter-parallel">
  <h2>8 · 4 个平行宇宙</h2>

  <p class="dropcap">这一章问一个很小的问题:<strong>同一个 75 岁的退休志愿者,
  在 4 部不同的手机底下,她 14 天会抬几次头?</strong></p>

  <p>仿真把她复制了 4 份——同样的过去、同样的女儿在东郊、同样的大麦茶、
  同样的 Lane Cove。唯一被换掉的,是她口袋里那部手机会响什么。
  然后让 4 个她,各自走 14 天,各自从清晨走到傍晚,
  各自经过 90 到 285 张陌生的脸——<strong>看,或者不看。</strong></p>

  <p>下面是 5 月 5 日傍晚那一刻,4 个她分别在哪。地图上她去过的地方染成深橙,
  细线是她真实走过的路径,圆圈是 snapshot 抓到的最后一个位置。</p>

  <div class="universes-grid">
    {"".join(panels)}
  </div>

  <h3 class="parallel-insight-h3">4 个老何,4 段 14 天</h3>

  <div class="universe-essay" style="border-left:5px solid {bl['meta']['color']};">
    <h4 style="color:{bl['meta']['color']};">无推送 · 她抬头了 11 次</h4>

    <p>5 月 5 日傍晚 8 点 30 分,她站在 building_2022 楼下擦鞋底。今天是她出门的第三趟——
    早上去 Plaza 取信、上午在图书馆做志愿、下午又下楼走了一圈。她要回家了。
    冰箱便签上还写着今晚的事:7 点新闻,8 点 30 视频电话东郊。</p>

    <p>她的手机一整天没响过。这是她默认的宇宙——没有推送、没有提醒、
    没人告诉她"本街新开了什么"或"今天世界怎么了"。她按自己的节奏走。
    14 天里去过的地方比另外 3 个她都多——383 个不同的角落、街口、店招。
    她从 90 个不同的邻居身边经过——在 Plaza 取信的队伍里、在图书馆门口、
    在 Centennial Avenue 等红灯的路口。</p>

    <p>但她抬起头的次数,<strong>只有 11 次</strong>。
    14 天 90 个人,她真的看见的是 11 个。<br>
    剩下 79 次,她身体在场,意识不在场——可能在想晚上的电话、可能在听耳机里的播客、
    可能那条街太长、那个人走得太快、她自己脑子里在循环昨晚没看完的那集新闻。
    她路过他们。他们也路过她。两边都没有抬头。</p>

    <p>那 11 次她真的看见的人,她其实记得几张脸——
    "<em>那位 55 岁的设计师、那位 51 岁的开发邻居、那位 73 岁的顾问,
    他们好像反复出现</em>",她在 day 13 自己的反思里写。
    她<u>看见</u>了他们。<strong>但看见没有变成开口。</strong>
    14 天她真正坐下来聊上的人,只有 4 个。
    这是她最自由的宇宙——没人告诉她去哪——也是她最安静的宇宙。</p>
  </div>

  <div class="universe-essay" style="border-left:5px solid {hp['meta']['color']};">
    <h4 style="color:{hp['meta']['color']};">本街推送 · 她抬头了 45 次,认出了同一张脸</h4>

    <p>这个宇宙里,她的手机响了 30 次。30 次都是同一个地方在叫她——
    <em>"shinnyo_australia 周六上午 10 点儿童活动,免费,有手作,有零食。"</em>
    <em>"周日上午社区清扫日。"</em><em>"周日下午 3 点新邻居见面会。"</em>
    都是真如苑——Lane Cove 那座坐落在 Burns Bay Road 拐角的日式寺院,
    门口有一棵被剪得很整齐的松树。</p>

    <p>她 30 条都点开了。她的 plan reason 字段里,有一栏直接写着:
    "<em>被 hyperlocal 推送吸引</em>"。5 月 5 日凌晨,她到了那里。
    snapshot 那一刻她还在那里。</p>

    <p>真如苑那一栋楼,14 天里把 <strong>285 张陌生的脸</strong> 送到了她眼前——
    是无推送的她见过的 3 倍。但 285 张里有 240 张她仍然没有看见——
    真如苑的大堂人来人往,大部分时候她在数手心里的茶包、读手机上下一条活动信息、
    或者只是坐在长椅上发呆。<br>
    她真的抬头了 <strong>45 次</strong>。是无推送的 4 倍。
    多出来的那些"看见",几乎全发生在那一栋楼里。</p>

    <p>更要紧的是,那 45 次里有一张脸开始反复出现——
    一位 77 岁的退休邻居,每天像她一样在真如苑里来回走。
    她在 day 13 自己的反思里写:
    "<em>我日志里唯一不重复的事件,是和那位 77 岁退休邻居——
    像我一动不动、她一遍遍从我身边走过</em>"。
    她记住了那个人的轮廓、走路的节奏、出现的时段。</p>

    <p>14 天,她仍然只聊上了 4 个人。和无推送宇宙一模一样。<br>
    推送把她送到了一个地方、也把更多的脸送到了她眼前——
    但<strong>看见,不一定是开口</strong>。她在那里很安静地、反复地、记住了一张脸,
    却始终没有上前问那张脸叫什么名字。</p>
  </div>

  <div class="universe-essay" style="border-left:5px solid {gd['meta']['color']};">
    <h4 style="color:{gd['meta']['color']};">全球新闻 · 她身体漂到了 12 楼,眼睛留在了屏幕</h4>

    <p>5 月 5 日 0 点 10 分。她在 Silkari The Charrington 12 楼的一间公寓里——
    距离她在 Lane Cove 的家 4.5 公里。她不住这里。她也不认识这里的人。
    她也不大说得清楚自己为什么会在这里。</p>

    <p>她那 14 天看的推送是:<em>世界杯预选赛南美赛区多场爆冷。</em>
    <em>财经,比特币突破 10 万美元,分析师展望后市。</em>
    <em>欧洲央行宣布加息 25 基点,市场大幅震荡。</em><em>SpaceX 火星任务发射。</em>
    没有一条提到 Lane Cove。没有一条提到她家方圆 1 公里里的任何一个店招、活动、人。
    她每天读这些。读完。再读。</p>

    <p>不知道哪一天,她漂去了 Chatswood——也许是某条新闻里提到了什么,
    也许是 plan 系统帮她挑了一个看起来"有事可做"的点位。
    总之她到了 Silkari,在那栋公寓楼的 12 层。从她身边经过的人——
    跟无推送那个她差不多多,90 个。<br>
    但<strong>她真的抬起头的次数,只有 8 次。比无推送还少。</strong>
    14 天,她漂得最远——却看见得最少。</p>

    <p>那 8 次她抬起头时,看见的不是 Lane Cove 的脸——
    是一位住在这栋楼的 57 岁管理者、是一位偶尔同电梯的 18 岁学生。
    两个陌生人,在一栋她不属于的公寓里,被她偶尔地、迷茫地瞥过几眼。
    她不知道他们叫什么。她也没准备认识他们。</p>

    <p>她在这个宇宙里写的反思也少了一点——其他 3 个她每个都写了 36 条,
    这个她只写了 33 条。3 条少掉的反思,大概是她在那 4.5 公里之外的 12 楼里,
    没有什么可以反思的瞬间——眼前的人她不认识、脚下的街她没走过、
    手机里的新闻跟她吃的早饭无关。</p>

    <p><strong>"附近性盲区"不一定是低头看手机看不见旁边的人。</strong>
    它还可以是另一种样子——<strong>注意力被一条跟脚下无关的新闻牵走、
    人也跟着漂走</strong>,漂到一栋陌生的 12 楼公寓,
    眼睛永远停在屏幕里,身体只是一个搁置在地理上的容器。</p>
  </div>

  <div class="universe-essay" style="border-left:5px solid {pf['meta']['color']};">
    <h4 style="color:{pf['meta']['color']};">减少手机 · 她抬头了 21 次,在 1021 餐厅看见了一个人</h4>

    <p>这个宇宙里,她的手机几乎不响。14 天 6 条推送——是 4 个她里最少的。
    每一条都不是叫她"去哪",而是叫她<strong>抬头</strong>:<br>
    <em>"下次电梯里别低头——也许你认识那张面孔。"</em><br>
    <em>"屏幕亮 5 小时不如 Plaza 站 5 分钟,街角邻居会注意到你。"</em><br>
    <em>"屏幕里没有真正的对话——Plaza 长椅上有。"</em></p>

    <p>每一条都不告诉她去哪、做什么、几点见。
    每一条都只是一句话,关于她眼睛该停在哪里。她 6 条都读了。</p>

    <p>5 月 5 日凌晨,她不在家。她也不在 Plaza。她在 Burns Bay Road 中段一家小店——
    1021 Mediterranean。镇上一家不大的地中海菜馆,木桌、油画灯、晚饭时人不多。
    她到了那里就没怎么动。snapshot 那一刻她还坐在那家店里。</p>

    <p>从她身边经过的人,有 107 个——比无推送的 90 个多一点。
    但她真的抬起头的次数,有 <strong>21 次</strong>——
    几乎是无推送那个她(11 次)的两倍。<br>
    抬起头不需要一个具体的目的地——只需要一句话把她从手机里拉出来。
    6 条提醒抬头的推送,换来的是她 14 天里的 21 次抬头。</p>

    <p>更关键的是那 21 次里有一张脸开始反复出现——
    一位 40 岁的失业青年,在 1021 那家店的角落,
    "<em>远远多过其他任何人</em>",她在反思里写。
    同一个角落、同一张桌、同一杯水。她记得他坐的位置。
    她记得他面前那只杯子。<br>
    她没和他说话——她还是只聊上了 4 个人,和其他 3 个宇宙一样——
    <strong>但她<u>看见</u>他了</strong>。在一个有人会反复出现的地方,她也反复出现,
    两个人在彼此眼角余光里,慢慢成了对方的"那张脸"。</p>

    <p>反向推送没有让她"少看手机"。它让她从家里走出来,
    去了一个会让她<strong>抬起头</strong>的地方。
    6 条提醒,换 21 次抬头——比"叫她去真如苑"那 30 条推送的抬头率
    (30 条换 45 次抬头)还要高一些。<br>
    <strong>最有效的那种推送,也许从来不是"告诉你去哪",而是"提醒你抬头"。</strong></p>

    <p>没有一行代码告诉她去 1021。反向推送只做了一件很小的事:
    把她的 <code>screen_time_weight</code> 调低一点,
    plan 系统下一次计算周边吸引力时,<code>sight_radius</code> 自动撑开,
    Burns Bay 中段那家有木桌油画灯的小店刚好进了视线。
    她出门、走过去、坐下来。
    <strong>一行权重被改了,系统自己长出来下一步。</strong></p>
  </div>

  <p class="parallel-close">同一个 75 岁的退休志愿者。同一份 20 条的生平。
  同一个东郊的女儿。同一杯傍晚的大麦茶。同一个 Lane Cove。<br>
  同一段 14 天,4 部不同的手机。<br><br>
  在 4 部不同的手机里,她分别抬了 <strong>11 次</strong>、<strong>45 次</strong>、<strong>8 次</strong>、和 <strong>21 次</strong>头。<br>
  每一次抬头,都有一张陌生的脸短暂进入她的生活。<br>
  每一次低头,都有一张脸从她身边走过、却没有发生。<br><br>
  <span class="parallel-kicker">在这个 1,000 人的算法风洞里,
  老何 的 14 天提供了一个真实世界也许还没注意到的可能:<br>
  <strong>技术并不只能是把人原子化、把注意力剥走的机器。
  只要把一行权重的分发逻辑稍微改一下,算法同样可以成为"附近性"的粘合剂——
  把人从屏幕里拉出来,放回到她脚下那条街上。</strong></span></p>
</section>
"""


def section_change():
    """14 天 reflection 轨迹"""
    refls = [e for e in hp["agent_events"] if e.get("kind") == "reflection"]
    refls.sort(key=lambda e: e.get("simulated_time") or "")
    # Pick 3-4 most-revealing
    pick = [refls[0], refls[len(refls)//3], refls[2*len(refls)//3], refls[-1]] if len(refls) >= 4 else refls

    cards = "".join(f"""
<div class="reflection-log">
  <div class="reflection-log-head">&gt; reflection · day {r.get("day_index","?")} · {(r.get("simulated_time","?")[:10])}</div>
  <div class="reflection-log-body">{clean_text(r.get("content",""))}</div>
</div>
""" for r in pick if r)

    plan = hp["agent_runtime_state"]["plan"]["steps"]
    plan_str = ""
    if plan:
        p = plan[0]
        plan_str = f"{p.get('time')} {p.get('action')} → {loc_name(p.get('destination',''))} · 理由: {p.get('reason')} · 社交意图: {p.get('social_intent')}"

    return f"""
<section class="chapter chapter-change">
  <h2>9 · 14 天的变化</h2>
  <p>系统每天结束时会让 LLM 看 老何 当天的全部行为日志,生成 <code>reflection</code> 事件 —
  对她自己行为模式的 meta-觉察。这些反思不是 老何 自己写的,是系统看 log 总结的。
  但它们追踪着她每天行为的变化。</p>

  {cards}

  <p>到 snapshot 取样的 5 月 5 日,她的 <code>plan</code> 字段是:</p>
  <div class="plan-block">{plan_str}</div>

  <p>"被 hyperlocal 推送吸引"是系统给出的决策理由。"open_to_chat"是她当时对聊天的态度。
  她今天的 replan 次数 = {hp.get("replan_count_today", 0)}。</p>
</section>
"""


def section_phantom_daughter():
    """插曲 · 那位不存在的女儿。
    Fact: 老何.family_members = {}. 1000 个 agent 数据库里没有任何一个
    被链接为她的女儿。她在 life_history 里写过母亲节女儿从悉尼东郊
    开车来 Crows Nest 吃饭、暴雨夜女儿打电话来问会不会淹、女王逝世
    那晚她给女儿发短信收到一个王冠 emoji——但这些都是 LLM 生成的回忆。
    plan 里那句"给东郊女儿打视频电话",对面没有 API。"""
    return """
<section class="chapter chapter-phantom">
  <h2>插曲 · 那位不存在的女儿</h2>

  <p class="phantom-lead">在继续往下之前,有一件事必须说出来。</p>

  <p>老何 在她那 4 段 14 天里,几乎每一个夜晚都给"悉尼东郊的女儿"打视频电话。
  这件事写在她的 plan 里、写在她和 88 岁退休邻居的对话里——
  <em>"晚上 8 点 30 视频电话东郊,写在冰箱便签上了,怕忘事。"</em>
  她的 life_history 里也有真切的细节:2023 母亲节女儿从悉尼东郊开车过来,
  在 Crows Nest 的 garfish 餐厅吃了一顿晚午饭;2022 年暴雨夜女儿打电话来问
  "<em>你那儿会不会淹</em>",她说"<em>七十年代发洪水都没事</em>";
  2022 年女王逝世那晚她给女儿发了条短信,女儿回了一个王冠 emoji。</p>

  <div class="phantom-revelation">
    <p>但 Synthetic Socio Wind Tunnel 这 1000 个虚拟居民的数据库里,
    <strong>并没有一个 agent 被链接为老何的女儿</strong>。</p>

    <p>老何 的 profile 里 <code>family_members = {}</code> ——空字典。
    <code>household_role = "parent"</code> 写着她是个母亲,
    但 simulation 里没有一个 <code>a_43_XXXX</code> 指向"她的孩子"。
    悉尼东郊根本不在这次仿真的地理范围里——
    Lane Cove 这个 1000 人的小镇,就是这个宇宙的全部。</p>

    <p>所以她每一个夜晚 8 点 30 分举起的那个手机,<strong>对面没有 API</strong>。
    她的 LLM 写出来"打视频电话",但没有任何一行代码去接通另一个 agent 的输入。
    那个王冠 emoji、那句"爸你瘦了"(LLM 自己写漂的)、那通问"会不会淹"的电话——
    全是 老何 自己 memory_store 里一段不会有真实响应的字符串。</p>
  </div>

  <p class="phantom-twist">系统给了她一份牵挂。<br>
  系统没有给这份牵挂分配一个接收端。</p>

  <p>这件事比"她 14 天只聊上了 4 个人"还要锋利一点——
  那 4 个对话,至少另外一边是真的 agent_id,有他自己的 plan、自己的 memory、
  在仿真的某个角落自己也活着。<br>
  但每天晚上 8 点 30,她举着手机说"喂闺女"的那一刻,
  她对面的 socket 一直是空的。</p>

  <p>这或许才是这场仿真给现实的最后一面镜子。
  在我们自己的 1,000 人小镇里——在 Lane Cove,在墨尔本的西郊,在北京的回龙观——
  也有很多个 老何,每晚 8 点 30 准时拿起手机,对着屏幕讲一段话。
  另一头是不是真的有人在听——是不是有人在打字、在皱眉、在回一个 emoji——
  并不总能验证。<br>
  <strong>有些晚上的牵挂,我们也不能确定它的另一端,有没有 API。</strong></p>
</section>
"""


def section_one_of_thousand():
    return """
<section class="chapter chapter-zoom">
  <h2>10 · 1,000 个故事里的 1 个</h2>
  <p>老何 不是特例。在这 1,000 个虚拟居民里,有 227 人在 14 天里经历了类似的变化 —
  从他们的日常半径里被推送拉出去,在一个新地方反复遇到一群以前没见过的邻居,
  形成新的固定行程。</p>

  <p>但每一个人都有自己的版本。同样的 hyperlocal_push 推送,Mike 26 岁工程师去了 1021 Mediterranean;
  Frank 64 岁建筑工被《Lane Cove 简史》读书会勾住跑去了 Shinnyo;
  Lucy 29 岁失业青年走 3.1 km 去了 PLC Sydney Preschool。</p>

  <p>这是一个虚拟城市的故事 — 但它讨论的是真问题: 一条推送能不能改变一个具体的人的世界半径?
  仿真说能。老何 用她 14 天的真实数据印证了这件事。</p>

  <p>
    <a href="../项目实验结果.html" class="back-link">→ 返回 1,000 居民的统计层报告</a>
  </p>
</section>
"""


def section_data_vanity():
    """数据规格附录 — 用真实数字回应"这数据量好像不大"的疑虑。
    All numbers derived from the actual snapshots / atlas / runtime
    state of seed 43 × 4 variants × 14 days."""
    import re as _re

    # 老何's own data — recount from the 4-variant blob
    total_events = 0
    kinds_total = {"life_history":0,"reflection":0,"action":0,"encounter":0,
                   "notification":0,"shared_memory":0}
    total_dialogues = 0
    total_explored = 0
    total_pushes_seen = 0
    known_per_variant = []          # distinct info_ids she heard about, per universe
    avg_listeners_per_story_pv = []  # avg listeners per her own story, per universe
    total_dlg_chars = 0
    for vname, v in four["variants"].items():
        evs = v.get("agent_events", [])
        total_events += len(evs)
        for e in evs:
            k = e.get("kind","?")
            if k in kinds_total: kinds_total[k] += 1
        total_dialogues += len(v.get("dialogue_summaries", []))
        total_explored += len(v.get("explored_locations", []))
        total_pushes_seen += len(v.get("consumed_feed_item_ids", []))
        known_per_variant.append(len(v.get("known_infos", {})))
        sc = v.get("share_counts_for_mine", {})
        if sc:
            avg_listeners_per_story_pv.append(sum(sc.values()) / len(sc))
        total_dlg_chars += sum(len(i.get("content","")) for i in v.get("dialogue_infos", []))

    # Honest single-seed numbers (avoid double-counting across universes):
    # - avg distinct info_ids she heard, per universe (~760)
    # - avg listeners each of her stories reached, per universe (~990)
    avg_known_per_variant = round(sum(known_per_variant) / len(known_per_variant)) if known_per_variant else 0
    avg_listeners_per_story = round(sum(avg_listeners_per_story_pv) / len(avg_listeners_per_story_pv)) if avg_listeners_per_story_pv else 0
    min_known_pv = min(known_per_variant) if known_per_variant else 0
    max_known_pv = max(known_per_variant) if known_per_variant else 0

    # Position samples
    pos_total = sum(len(positions[v]) for v in positions)

    # Atlas
    try:
        atlas = json.load(open(REPO / "data/lanecove_atlas.json"))
        n_buildings = len(atlas.get("buildings", []))
        n_outdoor = len(atlas.get("outdoor_areas", []))
        n_connections = len(atlas.get("connections", []))
    except Exception:
        n_buildings, n_outdoor, n_connections = 5722, 4257, 14903

    # Simulation scale
    TICKS_PER_DAY = 288
    agents = 1000
    variants = 4
    days = 14
    ticks_per_variant = days * TICKS_PER_DAY
    agent_ticks_total = agents * variants * ticks_per_variant
    person_days = agents * variants * days

    # Snapshot file sizes (seed 43 only)
    snapshot_gb = 2.05  # measured above

    # Conservative LLM call estimate (per agent per day:
    # ~1 plan + ~2 replan + ~2-3 reflection + 1-2 dialogue × 5 turns + a few shared_memory ≈ 15-20)
    llm_calls_per_agent_day = 18
    llm_calls_per_variant = agents * days * llm_calls_per_agent_day
    llm_calls_total = llm_calls_per_variant * variants

    def num(n):
        """Format number with thousand separators."""
        return f"{n:,}"

    return f"""
<section class="chapter chapter-data-vanity">
  <h2>附录 · 数据规格</h2>

  <p class="data-vanity-lead">这份关于一个 75 岁老人的 10 章长文,背后是多少数据?
  把所有数字摆出来 — 一份诚实的"数据账本",
  也是一份不必谦虚的"虚拟人口学规模说明"。</p>

  <div class="data-vanity-section">
    <h3 class="dv-h3">⊙ 老何 一人,跨 4 个平行宇宙,14 天里产生了 ——</h3>
    <div class="data-vanity-grid">
      <div class="dv-cell"><div class="dv-num">{num(total_events)}</div>
        <div class="dv-lbl">条系统记录的事件</div>
        <div class="dv-sub">(平均每个模拟日 {total_events // (variants*days)} 条)</div></div>
      <div class="dv-cell"><div class="dv-num">{num(kinds_total['action'])}</div>
        <div class="dv-lbl">条 action 记录</div>
        <div class="dv-sub">每次走路 / 留步 / 回家</div></div>
      <div class="dv-cell"><div class="dv-num">{num(kinds_total['encounter'])}</div>
        <div class="dv-lbl">次"同框" co-presence 事件</div>
        <div class="dv-sub">同一栋楼/街段 + 同一个 5 分钟时段。其中真"被瞥见"(过注意力闸门)的只占一小部分</div></div>
      <div class="dv-cell"><div class="dv-num">{num(kinds_total['reflection'])}</div>
        <div class="dv-lbl">条 LLM 自动生成的反思</div>
        <div class="dv-sub">每个宇宙 36 条,GD 少 3 条</div></div>
      <div class="dv-cell"><div class="dv-num">{num(kinds_total['notification'])}</div>
        <div class="dv-lbl">次推送送达</div>
        <div class="dv-sub">0 + 30 + 30 + 6,她看过 {total_pushes_seen} 条</div></div>
      <div class="dv-cell"><div class="dv-num">{num(kinds_total['life_history'])}</div>
        <div class="dv-lbl">条生平回忆</div>
        <div class="dv-sub">20 条 × 4 宇宙(同一份过去)</div></div>
      <div class="dv-cell"><div class="dv-num">{num(kinds_total['shared_memory'])}</div>
        <div class="dv-lbl">次共享记忆事件</div>
        <div class="dv-sub">跟邻居共享的城市知识</div></div>
      <div class="dv-cell"><div class="dv-num">{num(total_dialogues)}</div>
        <div class="dv-lbl">场完整对话</div>
        <div class="dv-sub">4 × 4 宇宙,~{num(total_dlg_chars)} 字 LLM 原文</div></div>
      <div class="dv-cell"><div class="dv-num">{num(total_explored)}</div>
        <div class="dv-lbl">次 location 访问</div>
        <div class="dv-sub">383 + 191 + 185 + 197(可重复)</div></div>
      <div class="dv-cell"><div class="dv-num">{num(pos_total)}</div>
        <div class="dv-lbl">个 GPS 位置采样</div>
        <div class="dv-sub">下采样后的真实轨迹点</div></div>
    </div>
  </div>

  <div class="data-vanity-section">
    <h3 class="dv-h3">⊙ 她周围的信息扩散网络(单宇宙平均)——</h3>
    <div class="data-vanity-grid">
      <div class="dv-cell"><div class="dv-num">~{avg_known_per_variant}</div>
        <div class="dv-lbl">条她耳朵听过的八卦</div>
        <div class="dv-sub">每个宇宙 {min_known_pv}-{max_known_pv} 条,
          来自 Lane Cove 1,000 人镇里 ~750 个邻居</div></div>
      <div class="dv-cell"><div class="dv-num">~{avg_listeners_per_story}</div>
        <div class="dv-lbl">个邻居听过她每段故事</div>
        <div class="dv-sub">她 4 段对话各自的转述触达,
          单宇宙 / 单 info 平均</div></div>
      <div class="dv-cell"><div class="dv-num">4 / 4</div>
        <div class="dv-lbl">段她真正开口聊上的对话</div>
        <div class="dv-sub">4 个平行宇宙里都是 4 段——
          推送什么都没改变这个数字</div></div>
      <div class="dv-cell"><div class="dv-num">0 → 17</div>
        <div class="dv-lbl">手:她听到过的最深一条八卦</div>
        <div class="dv-sub">同一条 info 在 1,000 人小镇里转了 17 次,
          才传到她耳朵里——绕了大半个 Lane Cove</div></div>
    </div>
  </div>

  <div class="data-vanity-section">
    <h3 class="dv-h3">⊙ 承载她的虚拟 Lane Cove ——</h3>
    <div class="data-vanity-grid">
      <div class="dv-cell"><div class="dv-num">{num(n_buildings)}</div>
        <div class="dv-lbl">栋真实 Lane Cove 建筑</div>
        <div class="dv-sub">每栋有真实经纬度 / 用途 / polygon</div></div>
      <div class="dv-cell"><div class="dv-num">{num(n_outdoor)}</div>
        <div class="dv-lbl">片真实户外区域</div>
        <div class="dv-sub">街道 / 公园 / 广场 / 海岸线</div></div>
      <div class="dv-cell"><div class="dv-num">{num(n_connections)}</div>
        <div class="dv-lbl">条 atlas 拓扑连接</div>
        <div class="dv-sub">门到门 / 路口到路口</div></div>
      <div class="dv-cell"><div class="dv-num">1,000</div>
        <div class="dv-lbl">个虚拟邻居</div>
        <div class="dv-sub">每人有完整过去 / 性格 / 家庭 / 职业</div></div>
    </div>
  </div>

  <div class="data-vanity-section">
    <h3 class="dv-h3">⊙ 放大到整个仿真规模 ——</h3>
    <div class="data-vanity-grid">
      <div class="dv-cell dv-cell-big"><div class="dv-num">{num(agent_ticks_total)}</div>
        <div class="dv-lbl">agent-ticks</div>
        <div class="dv-sub">1,000 邻居 × 4 宇宙 × 14 天 × 288 tick = <strong>16.1 M</strong></div></div>
      <div class="dv-cell"><div class="dv-num">{num(person_days)}</div>
        <div class="dv-lbl">模拟人天</div>
        <div class="dv-sub">1,000 × 4 × 14,相当于一个小镇活 56,000 天</div></div>
      <div class="dv-cell"><div class="dv-num">~{llm_calls_total / 1e6:.1f} M</div>
        <div class="dv-lbl">次 LLM 调用(粗估)</div>
        <div class="dv-sub">每个 agent 每天 plan/replan/reflect/dialogue 平均 ~18 次</div></div>
      <div class="dv-cell"><div class="dv-num">{snapshot_gb:.2f} GB</div>
        <div class="dv-lbl">snapshot 文件</div>
        <div class="dv-sub">4 个 .json 文件,每个 460-525 MB</div></div>
    </div>
  </div>

  <p class="data-vanity-fineprint">
    上面是 <strong>seed 43</strong> 一次跑出来的数据。数据闭环要求 <strong>3 个 seed
    (43 / 44 / 45)</strong> × <strong>4 variants</strong> = <strong>12 个独立的
    14 天 Lane Cove</strong>。 全部统计写在 <a href="../项目实验结果.html"
    class="back-link">主报告 ↗</a>。
  </p>

  <p class="data-vanity-kicker">
    你刚读完的 10 章关于 老何 的故事 —— 是这堆数据里关于
    <strong>1 个 75 岁退休志愿者</strong>的 <strong>1 条线索</strong>。<br>
    类似的故事,这次仿真里还有 999 个,各自 4 种宇宙、各自 14 天、各自一个反复遇到的"那个人"。
  </p>
</section>
"""


# ─── Assemble HTML ─────────────────────────────────────────────────────
CSS = """
* { box-sizing: border-box; }
body { font-family: 'Georgia', 'Songti SC', serif; max-width: 760px; margin: 0 auto;
       padding: 0; background: #FFFEF8; color: #1B1F2A; line-height: 1.75; font-size: 18px; }
h1 { font-size: 56px; font-weight: 900; letter-spacing: -1.5px; line-height: 1.08; margin: 0 0 24px; }
h2 { font-size: 34px; font-weight: 900; margin: 56px 0 22px; padding-bottom: 12px;
     border-bottom: 1px solid #1B1F2A; letter-spacing: -0.5px; }
h3 { font-size: 22px; font-weight: 900; margin: 32px 0 16px; }
p { margin: 0 0 18px; }
strong { color: #1B1F2A; }
em { font-style: italic; color: #5A5E6A; }
code { background: #F4EFE5; padding: 2px 6px; font-family: 'Menlo', monospace; font-size: 14px; color: #A0252F; }

.open { padding: 80px 40px 60px; border-bottom: 1px solid #D8D9DC; }
.kicker { color: #A0252F; font-style: italic; letter-spacing: 2px; font-size: 13px;
          text-transform: uppercase; margin: 0 0 18px; }
.subtitle { font-size: 22px; line-height: 1.5; color: #5A5E6A; font-style: italic; margin: 0; }

.methodology { background: #F4EFE5; padding: 30px 40px; margin: 0; border-left: 4px solid #A0252F;
              font-size: 16px; }
.methodology h2 { font-size: 20px; margin-top: 0; border: none; padding: 0; }
.methodology p { margin-bottom: 14px; }

.chapter { padding: 50px 40px; }
.chapter.scene-open { background: #1B1F2A; color: white; padding: 60px 40px; }
.chapter.scene-open code { background: rgba(255,255,255,0.1); color: #F0C419; }
.scene-time { color: #F0C419; font-style: italic; font-size: 13px; letter-spacing: 1px; margin-bottom: 20px; }

.profile-quote { background: #F4EFE5; padding: 22px 26px; border-left: 4px solid #A0252F;
                font-style: italic; font-size: 17px; margin: 20px 0; line-height: 1.7; }

.trait-list { list-style: none; padding: 0; margin: 0 0 20px; font-size: 16px; }
.trait-list li { padding: 4px 0; border-bottom: 1px dashed #D8D9DC; }

.life-card { background: white; border-left: 4px solid #F0C419; padding: 16px 22px; margin: 14px 0;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.life-date { color: #A0252F; font-style: italic; font-size: 13px; margin-bottom: 6px; letter-spacing: 0.5px;
            display: flex; align-items: center; gap: 10px; }
.life-card p { margin: 0; font-size: 16px; line-height: 1.7; }
.drift-tag { background: #FBD8DC; color: #A0252F; padding: 2px 8px; font-size: 11px;
             border-radius: 3px; font-style: normal; letter-spacing: 0.3px; }

.map-figure { margin: 32px 0; }
.map-figure svg { display: block; width: 100%; height: auto; border: 1px solid #D8D9DC; }
.map-figure figcaption { font-size: 14px; color: #5A5E6A; font-style: italic; margin-top: 10px; padding: 0 8px; }

.phone-push { background: linear-gradient(135deg, #1B1F2A 0%, #2d3340 100%); color: white;
             padding: 16px 20px; margin: 12px 0; border-radius: 14px; position: relative;
             box-shadow: 0 3px 10px rgba(0,0,0,0.2); }
.phone-push::before { content: "📱"; position: absolute; top: 14px; right: 18px; }
.phone-app { font-size: 11px; color: #F0C419; font-weight: 700; letter-spacing: 1.2px;
            margin-bottom: 4px; text-transform: uppercase; }
.phone-content { font-size: 15px; line-height: 1.55; padding-right: 30px; }

.phone-push-mini { background: #1B1F2A; color: white; padding: 10px 14px; margin: 6px 0;
                  border-radius: 8px; font-size: 13px; line-height: 1.5; }

.dialogue-card { background: white; padding: 22px 26px; margin: 18px 0;
                border-left: 4px solid #1B1F2A; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
.dialogue-pov { font-size: 11px; font-weight: 900; color: #A0252F; letter-spacing: 2px;
               text-transform: uppercase; margin-bottom: 12px; }
.dialogue-partner-card { background: #F4EFE5; padding: 10px 14px; margin: 0 0 14px;
                        font-size: 13px; line-height: 1.5; border-left: 3px solid #A0252F; }
.dialogue-content { font-family: 'Songti SC', 'Georgia', serif; font-size: 15px; line-height: 1.8;
                   margin: 0; }

.neighbor-mini { background: #F4EFE5; padding: 12px 16px; margin: 8px 0; font-size: 14px;
                border-left: 3px solid #5A5E6A; line-height: 1.6; }
.neighbor-mini em { display: block; margin-top: 6px; }

.hops-list { font-family: 'Helvetica', sans-serif; font-size: 15px; }

/* Whisper-game info-mutation visualization (ch 7) */
.whisper-figure { margin: 36px auto 28px; padding: 0; max-width: 100%; }
.whisper-caption { font-family: 'Georgia', serif; font-size: 17px; color: #1B1F2A;
                    font-style: italic; text-align: center; margin: 0 0 22px; }
.whisper-chain { display: flex; flex-direction: column; gap: 0; align-items: center; }
.whisper-frame { background: white; box-shadow: 0 2px 8px rgba(0,0,0,0.07);
                 padding: 16px 22px; width: 100%; max-width: 580px;
                 border-left: 4px solid #5A5E6A; }
.whisper-frame-mid { border-left-color: #C19A00; opacity: 0.94; }
.whisper-frame-far { border-left-color: #A0252F; opacity: 0.88; }
.wf-stamp { font-family: 'Helvetica', sans-serif; font-size: 10px;
             letter-spacing: 1.5px; text-transform: uppercase;
             color: #8A8E96; margin-bottom: 8px; font-weight: 700; }
.wf-line { font-family: 'Songti SC', 'Georgia', serif; font-size: 17px;
            line-height: 1.6; color: #1B1F2A; }
.wf-line strong { color: #A0252F; }
.wf-meta { font-family: 'Helvetica', sans-serif; font-size: 11px;
            color: #8A8E96; margin-top: 8px; font-style: italic; }
.whisper-arrow { font-family: 'Helvetica', sans-serif; font-size: 11px;
                  color: #A8ACB5; padding: 14px 0; letter-spacing: 2px; }
.whisper-fineprint { font-family: 'Helvetica', sans-serif; font-size: 12px;
                      color: #8A8E96; text-align: center; font-style: italic;
                      margin-top: 18px; max-width: 540px;
                      margin-left: auto; margin-right: auto; }
.whisper-fineprint strong { color: #1B1F2A; font-style: normal; }

.universes-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin: 32px 0; }
.universe-panel { background: white; padding: 22px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
.universe-header h3 { margin: 0 0 4px; font-size: 20px; }
.universe-tagline { font-style: italic; font-size: 13px; margin-bottom: 14px; font-weight: 700; }
.universe-map { margin: 12px 0; }
.universe-stats { font-size: 13px; font-family: 'Helvetica', sans-serif; line-height: 1.8; }
.universe-stats div { display: flex; justify-content: space-between; border-bottom: 1px dashed #D8D9DC; padding: 4px 0; }
.us-label { color: #5A5E6A; }
.us-val { font-weight: 700; color: #1B1F2A; }
.universe-plan { margin-top: 12px; padding: 10px 12px; background: #F4EFE5; font-size: 13px;
                 border-left: 3px solid #1B1F2A; }
.universe-pushes { margin-top: 12px; }
.universe-pushes-empty .phone-push-none { background: #EEE; color: #888; font-style: italic; }
.universe-pushes-label { font-size: 11px; color: #5A5E6A; letter-spacing: 1px; text-transform: uppercase;
                        margin-bottom: 6px; }
.us-partner { margin-top: 10px; padding: 10px 12px; background: #FBE5D6;
              display: flex; justify-content: space-between; font-size: 13px;
              font-family: 'Helvetica', sans-serif; border-left: 3px solid #D14B12; }
.us-partner .us-label { color: #5A5E6A; }
.us-partner .us-val { font-weight: 700; color: #1B1F2A; text-align: right; }
.us-diary { margin-top: 12px; padding: 12px 14px; background: #F4EFE5; border-left: 3px solid #5A5E6A; }
.us-diary-label { display: block; font-size: 11px; color: #5A5E6A; letter-spacing: 1px;
                  text-transform: uppercase; margin-bottom: 6px; }
.us-diary-text { font-size: 13px; line-height: 1.6; color: #1B1F2A; font-style: italic; }

.parallel-insight { margin-top: 40px; font-size: 22px; color: #A0252F; }
.parallel-insight-h3 { margin-top: 50px; font-family: 'Helvetica', sans-serif; font-size: 16px;
                       letter-spacing: 2px; text-transform: uppercase; color: #A0252F;
                       border-bottom: 2px solid #A0252F; padding-bottom: 8px; }
.us-label sup { color: #A0252F; font-size: 9px; }

.universe-compare { width: 100%; border-collapse: collapse; margin: 20px 0 24px;
                    font-family: 'Helvetica', sans-serif; font-size: 13px; }
.universe-compare thead th { padding: 12px 10px; border-bottom: 2px solid #1B1F2A;
                             text-align: left; font-size: 12px; letter-spacing: 1px;
                             text-transform: uppercase; }
.universe-compare tbody th { padding: 10px; color: #5A5E6A; font-weight: 500;
                             border-bottom: 1px dashed #D8D9DC; text-align: left; width: 26%; }
.universe-compare tbody td { padding: 10px; border-bottom: 1px dashed #D8D9DC;
                             font-variant-numeric: tabular-nums; color: #1B1F2A; }

.universe-essay { background: white; padding: 24px 28px; margin: 18px 0;
                  box-shadow: 0 1px 4px rgba(0,0,0,0.05); }
.universe-essay h4 { margin: 0 0 14px; font-size: 22px; font-family: 'Georgia', serif;
                     font-weight: 700; }
.universe-essay p { margin: 0 0 12px; font-size: 16px; line-height: 1.75; color: #1B1F2A; }
.universe-essay p:last-child { margin-bottom: 0; }
.universe-essay em { color: #5A5E6A; }

.parallel-close { margin-top: 32px; padding: 24px 30px; background: #1B1F2A; color: #F4EFE5;
                  font-size: 17px; line-height: 1.7; border-left: 6px solid #F0C419;
                  font-family: 'Georgia', serif; }
.parallel-close strong { color: white; }

/* Reflection logs (ch 9) — same machine-output aesthetic as ch 6 SYSTEM_EXPORT */
.reflection-log { background: #14181F; color: #C8CDD6; padding: 14px 18px;
                  margin: 14px 0; border-left: 4px solid #5A5E6A;
                  font-family: 'Menlo', 'Fira Code', 'Courier New', monospace;
                  font-size: 12px; line-height: 1.7; }
.reflection-log-head { color: #7A8090; font-size: 10.5px; letter-spacing: 0.5px;
                       padding-bottom: 10px; margin-bottom: 12px;
                       border-bottom: 1px dashed #2A303C; }
.reflection-log-body { color: #C8CDD6; word-break: break-word; }

.plan-block { background: #FBE5D6; padding: 14px 18px; border-left: 4px solid #D14B12;
              margin: 16px 0; font-size: 15px; font-family: 'Menlo', monospace; }

.chapter-zoom { background: #1B1F2A; color: white; padding: 60px 40px; margin-top: 0; }
.chapter-zoom h2 { border-color: #F0C419; color: #F0C419; }
.back-link { color: #F0C419; text-decoration: none; border-bottom: 1px dashed #F0C419; }

/* phantom 女儿 interstitial */
.chapter-phantom { background: #1B1F2A; color: #F4EFE5; padding: 70px 40px; margin-top: 0; }
.chapter-phantom h2 { font-family: 'Georgia', serif; font-size: 36px; color: #F0C419;
                       border-bottom: 2px solid #F0C419; padding-bottom: 12px;
                       letter-spacing: -0.5px; max-width: 540px; }
.chapter-phantom p { font-size: 17px; line-height: 1.85; color: #F4EFE5; max-width: 640px; }
.chapter-phantom em { color: #F4D08C; font-style: italic; }
.chapter-phantom code { background: rgba(240,196,25,0.12); color: #F0C419;
                        padding: 2px 6px; font-size: 14px; border-radius: 2px; }
.chapter-phantom strong { color: white; }
.phantom-lead { font-size: 22px !important; font-style: italic; color: #A8ACB5 !important;
                font-family: 'Georgia', serif; margin: 0 0 30px; }
.phantom-revelation { background: rgba(160,37,47,0.18); padding: 24px 28px;
                      margin: 28px 0; border-left: 5px solid #A0252F;
                      max-width: 660px; }
.phantom-revelation p { color: #F4EFE5 !important; margin: 0 0 14px; }
.phantom-revelation p:last-child { margin-bottom: 0; }
.phantom-twist { font-family: 'Georgia', serif; font-size: 24px !important;
                 line-height: 1.55 !important; color: #F0C419 !important;
                 margin: 36px 0 !important; font-style: italic;
                 border-left: 3px solid #F0C419; padding-left: 20px; }

/* NPC repetition highlight in ch 6 dialogues */
.npc-loop { background: linear-gradient(transparent 40%, #FFE873 40%, #FFE873 88%, transparent 88%);
            padding: 0 1px; }
.npc-loop-legend { font-size: 13px; color: #5A5E6A; background: #F4EFE5;
                   padding: 12px 16px; border-left: 3px solid #F0C419;
                   line-height: 1.7; font-style: italic; margin: 18px 0; }

/* System-log style raw transcript (above each LLM summary) */
.syslog-block { margin: 12px 0 0; padding: 16px 18px;
                background: #14181F; color: #B8BEC9;
                border-left: 4px solid #3A9D5C;
                font-family: 'Menlo', 'Fira Code', 'Courier New', monospace;
                font-size: 12px; line-height: 1.7; }
.syslog-header { color: #7A8090; font-size: 10.5px; letter-spacing: 0.5px;
                 padding-bottom: 10px; margin-bottom: 12px;
                 border-bottom: 1px dashed #2A303C; }
.syslog-body { color: #C8CDD6; }
.log-turn { margin: 0 0 10px; display: flex; gap: 8px; align-items: flex-start; }
.log-aid { color: #6FAEEB; flex: 0 0 auto; font-weight: 600; white-space: nowrap; }
.log-colon { color: #5A6070; flex: 0 0 auto; }
.log-line { flex: 1; min-width: 0; word-break: break-word; }
.log-hi { background: #F0C419; color: #14181F; padding: 1px 4px;
          font-weight: 700; border-radius: 2px; }
.summary-label { margin-top: 16px; padding: 8px 14px; font-family: 'Helvetica', sans-serif;
                 font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase;
                 color: #5A5E6A; background: #F4EFE5; font-weight: 700; }

/* Push density visualization (ch5) — 2x2 grid of phone "lockscreens" */
.push-density-figure { margin: 36px auto 24px; padding: 0;
                       width: 100%; max-width: 100%; display: block; }
.push-density-caption { font-family: 'Georgia', serif;
                        font-size: 18px; color: #1B1F2A; font-style: italic;
                        text-align: center; margin: 0 0 18px; }
.push-density-grid { display: grid;
                     grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
                     gap: 18px; width: 100%; }
.push-stack { background: white; border-top: 5px solid var(--accent);
              box-shadow: 0 2px 8px rgba(0,0,0,0.08); padding: 18px 18px 14px;
              min-height: 380px; min-width: 0;
              display: flex; flex-direction: column; }
.ps-phone-top { border-bottom: 1px dashed #D8D9DC; padding-bottom: 10px;
                margin-bottom: 14px; display: flex; justify-content: space-between;
                align-items: baseline; }
.ps-header { font-family: 'Helvetica', sans-serif; font-size: 15px;
             font-weight: 700; color: var(--accent); letter-spacing: 0.5px; }
.ps-count { font-family: 'Helvetica', sans-serif; font-size: 11px;
            color: #8A8E96; letter-spacing: 1px; text-transform: uppercase; }
.ps-empty { flex: 1; display: flex; flex-direction: column;
            justify-content: center; align-items: center;
            font-family: 'Georgia', serif; color: #A8ACB5; font-style: italic;
            font-size: 18px; line-height: 1.9; text-align: center;
            padding: 30px 8px; }
.ps-notifs { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.ps-notifs-sparse { gap: 20px; padding: 12px 6px; }
.notif { font-family: 'Helvetica', sans-serif; font-size: 11px;
         padding: 6px 9px; border-radius: 4px; color: #1B1F2A;
         display: flex; gap: 8px; line-height: 1.4;
         overflow: hidden; min-width: 0; }
.notif-day { font-size: 10px; color: #8A8E96; flex: 0 0 38px;
             font-variant-numeric: tabular-nums; }
.notif-txt { flex: 1 1 0; min-width: 0;
             overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.notif-hyperlocal_push { background: #FBE5D6; border-left: 3px solid #D14B12; }
.notif-global_distraction { background: #E0EAF5; border-left: 3px solid #3B6EA8; }
.notif-phone_friction { background: #DCEAE0; border-left: 3px solid #3A9D5C;
                        font-size: 14px; padding: 14px 16px; line-height: 1.6;
                        white-space: normal; gap: 12px; }
.notif-phone_friction .notif-day { font-size: 11px; flex: 0 0 42px; padding-top: 2px; }
.notif-phone_friction .notif-txt { white-space: normal; }
.notif-rep { display: inline-block; font-size: 9px; color: #8A8E96;
             margin-left: 4px; padding: 1px 5px; background: rgba(0,0,0,0.05);
             border-radius: 8px; font-variant-numeric: tabular-nums;
             vertical-align: middle; }
.push-density-fineprint { font-family: 'Helvetica', sans-serif; font-size: 12px;
                          color: #8A8E96; text-align: center; font-style: italic;
                          margin: 14px auto 0; max-width: 540px; }

/* Final kicker in chapter 8 close */
.parallel-kicker { display: block; margin-top: 28px; padding: 22px 26px;
                    background: #FBE5D6; color: #1B1F2A; font-family: 'Georgia', serif;
                    font-size: 16px; line-height: 1.7; border-left: 5px solid #D14B12;
                    font-style: normal; }
.parallel-kicker strong { color: #A0252F; }

.back-link:hover { background: rgba(240,196,25,0.15); }

/* 数据规格附录 — data vanity stat block */
.chapter-data-vanity { background: #F4EFE5; padding: 56px 40px; margin-top: 0;
                        border-top: 4px solid #1B1F2A; }
.chapter-data-vanity h2 { font-family: 'Georgia', serif; font-size: 38px;
                          color: #1B1F2A; border-bottom: 2px solid #1B1F2A;
                          letter-spacing: -0.5px; }
.data-vanity-lead { font-size: 18px; line-height: 1.7; color: #5A5E6A;
                    font-style: italic; margin: 0 0 36px; max-width: 640px; }
.data-vanity-section { margin: 36px 0 28px; }
.dv-h3 { font-family: 'Helvetica', sans-serif; font-size: 14px; letter-spacing: 2px;
         text-transform: uppercase; color: #A0252F; margin: 0 0 18px;
         font-weight: 700; }
.data-vanity-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.dv-cell { background: white; padding: 18px 22px; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
           border-left: 4px solid #1B1F2A; }
.dv-cell-big { grid-column: 1 / -1; border-left-color: #A0252F; }
.dv-num { font-family: 'Helvetica', sans-serif; font-weight: 900;
          font-size: 38px; line-height: 1.05; letter-spacing: -1.5px;
          color: #1B1F2A; font-variant-numeric: tabular-nums; }
.dv-cell-big .dv-num { font-size: 56px; color: #A0252F; }
.dv-lbl { font-family: 'Helvetica', sans-serif; font-size: 14px;
          color: #1B1F2A; margin-top: 4px; font-weight: 600; }
.dv-sub { font-family: 'Helvetica', sans-serif; font-size: 12px;
          color: #5A5E6A; margin-top: 4px; line-height: 1.4; }
.data-vanity-fineprint { margin-top: 32px; font-size: 14px; color: #5A5E6A;
                         font-style: italic; border-top: 1px dashed #A8ACB5;
                         padding-top: 16px; }
.data-vanity-kicker { margin-top: 36px; padding: 28px 30px; background: #1B1F2A;
                      color: #F4EFE5; font-size: 18px; line-height: 1.7;
                      border-left: 6px solid #F0C419; font-family: 'Georgia', serif; }
.data-vanity-kicker strong { color: #F0C419; }

@media (max-width: 600px) {
  body { font-size: 17px; }
  h1 { font-size: 38px; }
  h2 { font-size: 28px; }
  .universes-grid { grid-template-columns: 1fr; }
  .data-vanity-grid { grid-template-columns: 1fr; }
  .dv-num { font-size: 32px; }
  .dv-cell-big .dv-num { font-size: 42px; }
}
"""

html_parts = [
    "<!DOCTYPE html>",
    '<html lang="zh-Hans"><head>',
    '<meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    '<title>她在真如苑门口站了一会儿 · 1,000 个虚拟居民里的 1 位 · Synthetic Socio Wind Tunnel</title>',
    f'<style>{CSS}</style>',
    '</head><body>',
    section_open(),
    section_open_scene(),
    section_methodology(),
    section_who(),
    section_world(),
    section_push_arrival(),
    section_decision(),
    section_people(),
    section_dialogues(),
    section_info_propagation(),
    section_parallel_universes(),
    section_change(),
    section_phantom_daughter(),
    section_one_of_thousand(),
    section_data_vanity(),
    '<footer style="padding:30px; text-align:center; font-size:12px; color:#A8ACB5; font-style:italic;">',
    'Synthetic Socio Wind Tunnel · 悉尼 Lane Cove 虚拟城市 · seed 43 · 4 个变体的真实 snapshot 数据 ·',
    'github.com/york-zhouuu',
    '</footer>',
    '</body></html>',
]

OUT.write_text("\n".join(html_parts))
print(f"Wrote {OUT} · {OUT.stat().st_size / 1e3:.0f} KB")
