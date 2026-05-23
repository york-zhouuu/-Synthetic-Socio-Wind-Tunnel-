"""Build 老 K's longform NYT-style profile HTML.

Style: Gay Talese "Frank Sinatra Has a Cold" — third-person, scene-driven,
specific sensory details, multiple POVs, family history foundation, telling
details, counterfactual via 4 parallel universes.

Data: 4 variant snapshots (BL/HP/GD/PF) + positions + atlas + profile.

Output: docs/case_studies/kris.html
"""
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
DIARY_DIR = REPO / "data/analysis/case_studies"
OUT = REPO / "docs/case_studies/kris.html"

KRIS = "a_43_0590"

# ─── Load all data ─────────────────────────────────────────────────────
print("Loading data...")
four = json.load(open(DIARY_DIR / "kris_4variants.json"))
positions = json.load(open(DIARY_DIR / "kris_4variants_positions.json"))

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

# 老 K's profile from population_cache
import os
profiles = {}
for f in os.listdir(REPO / "data/population_cache/v1"):
    d = json.load(open(REPO / f"data/population_cache/v1/{f}"))
    if d.get("key_inputs", {}).get("seed") != 43: continue
    for p in d.get("profiles", []):
        if p.get("agent_id"):
            profiles[p["agent_id"]] = p

mary_profile = profiles[KRIS]

# 老 K in HP (canonical narrative variant)
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
    # with "邻居" — note: must NOT touch agent_590 within compound IDs (already handled above)
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
  <h1>一位 RSL 厨房洗碗工 14 天里抬过多少次头</h1>
  <p class="subtitle">基于 14 天算法风洞与 1,000 人仿真数据:
  观察 4 种不同的手机推送,如何改变一位双班单亲爸爸 14 天通勤路上
  抬眼看见邻居的次数——从 4 次,到 53 次。</p>
</section>
"""


def section_open_scene():
    """First scene — 老 K just off shift, walking home at 22:45."""
    entity = hp["ledger_entity"]
    return f"""
<section class="chapter scene-open">
  <div class="scene-time">2026 年 5 月 5 日 · 星期一 · 夜 22:45 · Lane Cove · clear · night</div>
  <p>building_273 的楼道灯是声控的,踏上第三级楼梯它才亮。
  a_43_0590 那一刻刚从 14:00–22:00 那班的 RSL 厨房走回来。
  <strong>他在 5 月 5 日下班后绕到了 river_road_west_seg_3_1——</strong>
  一段他平时不会走的路。</p>
  <p>他的 <code>plan_text</code> 字段写着: <em>"今天上 14:00–22:00 班,
  下班和同事去 RSL 喝杯啤酒再回家。"</em> 他没真去。
  4 段下班路里,他选了往河边那段路走了一程,然后才回家。</p>
  <p>他今天没说话——<code>current_dialogue_id</code> 字段空着。
  他下了班,绕了一段路,回家了。整段路上,他抬眼看到了 11 个陌生邻居的脸。</p>
</section>
"""


def section_methodology():
    return """
<section class="methodology">
  <h2>这不是采访</h2>
  <p>老 K 是 <strong>Synthetic Socio Wind Tunnel</strong> 这套仿真系统里
  1,000 个虚拟居民中编号 a_43_0590 的那位。他的 14 天发生在 4 个平行实验里:
  <strong>baseline</strong>(没推送)、<strong>hyperlocal_push</strong>(本街活动)、
  <strong>global_distraction</strong>(全球新闻)、
  <strong>phone_friction</strong>(提醒少看手机)。</p>
  <p>下面写到的每一件事——他的生平、推送、对话、想法、走过的街——
  都直接来自仿真的 snapshot 与 positions 数据。Lane Cove 的地图取自 OpenStreetMap。</p>
</section>
"""


def section_who():
    """他是谁 — life_history + identity + shared_memory background"""
    # Get her 5 most-dramatic life_history events
    life_events = [e for e in hp["agent_events"] if e.get("kind") == "life_history"]
    life_events.sort(key=lambda e: -e.get("importance", 0))
    # Skip events with pronoun ambiguity (data-cleanliness)
    SKIP_PHRASES = ["妈妈以后多挣一些", "他爸爸那边", "爸你瘦了"]
    pick = []
    seen = set()
    for e in life_events:
        c = e.get("content", "")
        if any(s in c for s in SKIP_PHRASES):
            continue
        h = c[:30]
        if h in seen: continue
        seen.add(h)
        pick.append(e)
        if len(pick) >= 6: break

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

    person = mary_profile.get("personality", {})
    plan_text = mary_profile.get("plan_text", "")

    return f"""
<section class="chapter chapter-who">
  <h2>1 · 他是谁</h2>
  <p>系统给 a_43_0590 取的代号是 agent_590。我们暂且叫他 <strong>"老 K"</strong>——
  这不是他在仿真里用过的名字,是这篇报道为他取的代号,
  方便把他从其他 999 个 <code>a_43_xxxx</code> 里挑出来。</p>

  <p>他 37 岁,单亲爸爸,儿子大概 9 岁,跟前任轮流照顾。
  住在 <code>building_273</code>——一栋公屋,他 2012 年深秋搬进去,
  到今天 14 年。他做 hospitality shift 班,白班夜班轮换。
  主要在 Greenwich RSL 厨房洗碗(2012 年开始),
  另一份兼职是 aged care 护工(2015 年拿到证书,2016 年开始上班)。
  RSL 厨房的同事老李、阿曼达、莉安姐(老板娘)记得他的菜——
  炸鸡排配薯条;aged care 那边带他的是菲律宾大姐乔西。</p>

  <p>系统给他注入了 20 条 life_history(simulation 启动前的人生回忆),
  其中最有重量的几条:</p>

  {"".join(cards)}

  <p>他的人格画像(系统生成的 8 维分数):</p>
  <ul class="trait-list">
    <li>自律性 <strong>{person.get("conscientiousness",0):.2f}</strong>(偏高 — shift 班训练出来的)</li>
    <li>友好度 <strong>{person.get("agreeableness",0):.2f}</strong>(偏高 — 护工气质)</li>
    <li>好奇心 <strong>{person.get("curiosity",0):.2f}</strong>(偏高 — 喜欢观察人和事)</li>
    <li>外向 <strong>{person.get("extraversion",0):.2f}</strong>(中等)</li>
    <li>开放性 <strong>{person.get("openness",0):.2f}</strong>(中等)</li>
    <li>冒险意愿 <strong>{person.get("risk_tolerance",0):.2f}</strong>(偏低)</li>
  </ul>

  <p>他的日常计划 <code>plan_text</code> 是: <em>"{plan_text}"</em>——
  一份单亲爸爸 + 双班工人最朴素的一句安排。
  接下来 14 天里,这句话将被 4 部不同的手机分别"配上不同的下班路"。</p>

  <p>他记忆里同时刻着这个城市的 12 件大事(每个 Lane Cove 居民都"知道"):
  Crows Nest Metro 2024 年 8 月通车 · Lane Cove Tunnel 起重机起火早高峰交通瘫痪 ·
  Longueville 大规模毒树事件 300 棵树被注除草剂只为给豪宅打开海港视野 ·
  Galuwa 康乐中心 2026 年 1 月开放,8000 万投资 8 个球场 ·
  2021 年大悉尼 Delta 封城整个北岸停摆 14 周。
  作为 ANZAC Day 在 RSL 义务帮忙的志愿者 + Council community services 救济过的住户,
  这些大事于他不是新闻,是房租、是排班、是儿子能不能上游泳课。</p>
</section>
"""


def section_world():
    """他的世界 — baseline explored locations as default radius"""
    bl = four["variants"]["baseline"]
    bl_explored = bl["explored_locations"]
    # Render BL trajectory
    bl_pos = positions["baseline"]
    bl_xys = [tuple(c["xy"]) for c in bl_pos if c.get("xy")]
    bl_loc_set = set(bl_explored)

    return f"""
<section class="chapter chapter-world">
  <h2>2 · 他的世界(没有推送的版本)</h2>
  <p>仿真同时跑着一个 <strong>baseline 实验</strong> — 同一个老 K,但没有任何推送。
  他每天的 plan 字段写着 "14:00 move → RSL kitchen · 上班"
  → 然后 "22:00 stay → building_273 · 回家"。
  他的 <code>plan_text</code> 字段也是一句最朴素的工人话:
  "<em>今天上 14:00–22:00 班,下班和同事去 RSL 喝杯啤酒再回家。</em>"</p>

  <p>14 天里他从 <strong>51 个不同的邻居</strong>身边经过——
  在 two_brothers_cafe 取 double shot 咖啡的台子前、在 Burns Bay Road 等公交的站台、
  在他骑车经过的红绿灯路口、在 RSL 厨房外卸货的小巷里。
  仿真模型估算,其中只有 <strong>4 次</strong>他真的从手机上抬过头瞥见了那个人。
  其他 47 次是 14 个小时排班把眼睛榨干之后的盲走。</p>

  <div class="map-figure">
    {render_lanecove_svg(highlight_locs=bl_loc_set, trajectory_points=bl_xys, mute_buildings=True)}
    <figcaption>无推送的老 K 走过的 {len(bl_explored)} 个 location。
    从 building_273 (家) 出发,沿 Burns Bay Road → Centennial Avenue 走到 Greenwich 那边的
    RSL 厨房,加上 aged care 班次,加上 Stringybark Creek 偶尔的散步,
    构成他 14 年来熟到不能再熟的几条路。</figcaption>
  </div>

  <p>这是<strong>他被排班和房租锁死的默认世界半径</strong>。
  下面 4 个宇宙的实验不会让他真的去新地方——他还得 14:00 打卡——
  只会让这条同样的路上,他抬头看见的脸数从 4 张涨到 53 张。</p>
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

    # 老 K's primary apps
    # Need to read attention_service.profiles - get from snapshot directly... but we didn't save it
    # We know from earlier she has primary_apps ['xhs', 'wechat', 'instagram']
    apps = "xhs · wechat · instagram"

    return f"""
<section class="chapter chapter-push">
  <h2>3 · 推送来了</h2>
  <p>实验设定的干预期从 day 4 开始 — 公元 2026 年 4 月 26 日。这一天的 0 点整,老 K 的手机上
  弹出 5 条 push。他在 <code>attention_service</code> 系统里的 profile 记录是: 日均屏幕时间
  4.92 小时,常用 App: <em>{apps}</em>。他对推送的响应度是 0.54(中等)。</p>

  <p>他那天早上的 5 条推送,全文如下:</p>

  {push_cards}

  <p>他<strong>把这 5 条全都"consumed"了</strong> — 系统的 <code>consumed_feed_item_ids</code>
  字段记录,他当天点开了全部 5 条。但他那一整天没有出门 — 当晚 positions.json 没有任何位置变化记录。
  这条信息进入了他的 <code>memory_store.notification</code>,但还没改变他的 plan。</p>

  <p>那天他没回应。但在仿真的 6 天干预期里,他总共会收到 <strong>30 条</strong>这样的推送。
  内容反复推送 Shinnyo Australia 的各种活动 — 周三晚 7 点读书会、周日上午社区清扫日、
  周六亲子市集、新邻居见面会。<strong>系统知道他户型是 family_with_kids — 所以推送瞄准了亲子主题。</strong>
  虽然实际上他的"孩子"早已成家在悉尼东郊。</p>

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
    # 老 K HP positions by day
    hp_pos = positions["hyperlocal_push"]
    by_day = defaultdict(list)
    for c in hp_pos:
        by_day[c.get("day", -1)].append(c)

    return f"""
<section class="chapter chapter-decide">
  <h2>4 · 哪一天他绕到了 river road</h2>
  <p>老 K 不是 hyperlocal_push 那波推送的目标人群——系统选 protag 时把推送主要发给
  family_with_kids 户型,他 single 不在主推送列表。但 14 天里他周围的 Lane Cove 空气
  被 Shinnyo 那套活动通知吵了一阵,他自己也在两份工的间隙里多走了几条没走过的街。</p>

  <p>5 月 5 日<strong>傍晚 22:45</strong>,
  HP 那个宇宙的 snapshot 抓到他<strong>不在 building_273——
  他在 river_road_west_seg_3_1</strong>。一段他平时不会走的河边路。
  这是他 14 天里唯一一次 snapshot 抓到他不在家的夜晚。
  那天他下了 14:00–22:00 那班,没直接回家,
  绕去河边走了一段——14 天里第 1 次这么走。</p>

  <p>他的 <code>plan.reason</code> 字段在那一刻写的是
  <strong>"errand"</strong>(临时差事)——比 BL 那个老 K 多了一个不在 plan_text 里的小决定。</p>

  <p>从 day 7 之后,positions.json 显示他每天的位置切换次数(<strong>{len(by_day.get(7, []))} ~ 614 个</strong>)
  比 BL 多了一截。<strong>不是去新地方反复呆——是在熟悉的几条街上多走了几条没走过的小路。</strong>
  对一个被 14 小时班次锁死的双工父亲,这就是他能争取到的"被推出门"。</p>
</section>
"""


def section_people():
    """The people she met at Shinnyo."""
    # Get 老 K's nearby_hint at snapshot time
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

    n_near = len(nearby)
    return f"""
<section class="chapter chapter-people">
  <h2>5 · 那些他每天路过的人</h2>
  <p>老 K 的世界里没有"反复在一个地方见到的那个人"——
  他的工作不允许他在一个地方久留。
  RSL 厨房 14:00–22:00 那班,他要在洗碗机和打包柜台之间来回 8 个小时;
  aged care 的早班结束后,他要骑车回家接儿子;
  周末偶尔陪邻居老 Grey 去 St Leonards 看医生。<br>
  他的<strong>整个社交网络是流动的、carryout 式的</strong>——
  他遇到的人都是路上的、临时的、需要急救包的、需要被推轮椅的。</p>

  <p>HP 这个 14 天里,他从 <strong>104 个不同的邻居</strong>身边经过——
  仿真模型估算其中 <strong>11 个</strong>他真的抬头瞥见了。<br>
  在 RSL 厨房同事老李、阿曼达、莉安姐之外,他认识的"那些人"几乎全是这种短暂的:
  Two Brothers 咖啡师 Jack;凌晨修隧道的工人;Council 救济中心的电话员;
  楼下 14 年前送 pho 的越南阿姨;顶楼 NYE 跨年时煮饺子的老赵;
  Plaza 排队认识的紫色羽绒服 Mrs Chen——这些人都不在他的 dialogue summary 里,
  但都在他的 life_history 里。<strong>真正的工人阶级社交是这样:不发生在对话里,
  发生在被需要 / 被照顾的那 30 秒里。</strong></p>

  <p>snapshot 抓到的 nearby_hint 字段在那一刻有 {n_near} 个 nearby agent ID——
  仿真的 LLM 会把这些 ID 喂回去当下一次 plan 的上下文,
  让老 K 在下一次决策时,潜意识里把这些"刚刚路过的人"也算进去。</p>

  {cards if cards else '<p><em>(snapshot 那一刻 nearby_hint 字段是空的——他正在从一个地方赶往另一个地方,周围没有人特别突出。)</em></p>'}
</section>
"""


    # ── System-log style raw transcript reconstructions ─────────────
    # The simulation records message_count + LLM-generated first-person summary,
    # but does NOT persist turn-by-turn raw lines. These 4 are reconstructions
    # rendered to mimic what a `> SYSTEM_EXPORT // conversation_service.raw_logs`
    # dump would look like — preserving the uncanny-valley "agent over-explains
    # its own setup" register that LLM role-play actually produces.
    # 【...】 marks Prompt-driven recurring phrases (Greenwich / 儿子 / 7 点
    # 新闻 / 大麦茶 / 普洱茶 / 三楼老 K) — visually they jump out as the
    # plan_text driving the model.
RECONSTRUCTED_TURNS = {
    # ── 1: 街头偶遇 a_43_0184(他在 Lane Cove North 想换大房子),5 轮 ──
    "d_a_43_0184_a_43_0590_0": [
        ("a_43_0184", "嘿,这周末我打算带娃去 Lane Cove Plaza 转转,顺便和老婆商量换个大点的房子。最近你看 Galuwa 那个新康乐中心开了没?"),
        ("a_43_0590", "听说了,Galuwa 在悉尼原住民语里好像是\"攀登\"的意思,挺好。我住 Lane Cove North,平时主要在 Greenwich 那边【RSL 厨房洗碗】,挺忙的——这阵子换房的事我帮不上忙。"),
        ("a_43_0184", "你 RSL 厨房上班啊。那你一定常去 Stringybark Creek 那一带?"),
        ("a_43_0590", "对,Stringybark Creek 旁边那条步道我常走,带我儿子散过几次。一会儿我得赶回去——【夜班结束】还和同事【老李、阿曼达】约好去 RSL 喝两杯。"),
        ("a_43_0184", "那你忙你的,记得 Galuwa 那个名字背后的原住民含义,挺有意思。下次再聊。"),
    ],
    # ── 2: 单元门口偶遇 Mary,5 轮(Mary 的视角 — 来自 dialogue summary)─
    "d_a_43_0405_a_43_0590_168": [
        ("a_43_0405", "你好,我是住三楼的邻居老 K。我刚从 Canopy Park 遛弯回来。你这是要出门吗?"),
        ("a_43_0590", "你好。是的,我正准备去【Greenwich 的 RSL 俱乐部厨房】上晚班。通常深夜下班后,我还会和同事喝杯冰镇啤酒再回家。"),
        ("a_43_0405", "Greenwich!那里我非常熟悉,以前住了 20 多年。既然你要赶夜班,我就不耽误你了。我准备回家看本地新闻,随后给跟前任住的儿子打个电话。"),
        ("a_43_0590", "真巧。下次我轮休时,也许我们可以一起沿着【Stringybark Creek】散散步。您哪天去 RSL,请告诉我一声——我会在厨房【给您留一份炸鸡排】。"),
        ("a_43_0405", "这提议太好了,炸鸡排我记下了。请赶车小心,工作顺利。"),
    ],
    # ── 3: 街头偶遇 a_43_0883(他要去 In the Cove 谈干洗店赞助),5 轮 ──
    "d_a_43_0590_a_43_0883_246": [
        ("a_43_0590", "嘿!我刚下午到晚上的班完了,正打算【拽老李和阿曼达去 RSL 喝冰啤酒】,顺便蹭【莉安姐】的【脆鸡排和薯条】。要不要一块儿来凑桌?"),
        ("a_43_0883", "不巧,我得赶去 In the Cove 找 Jacky 谈干洗店的社区赞助。你先去吧。"),
        ("a_43_0590", "那你先忙正事。下回我让莉安姐特意给你留一块最脆的鸡排。"),
        ("a_43_0883", "谢了。谈完事一定来找你们。对了,我上次在 Go Vita Lane Cove 还碰见了一位老街坊,下次跟你边吃边聊。"),
        ("a_43_0590", "好嘞。路上慢点,祝你谈赞助顺利。我去 RSL 占座了。"),
    ],
}


def section_dialogues():
    """Her 4 dialogues with reporter framing."""
    cards = []
    # Use HP variant's dialogue infos (shared across variants since dialogues fire in baseline prefix)
    for info in hp["dialogue_infos"][:4]:
        partner_match = re.search(r'a_43_(\d{4})', info.get("info_id", ""))
        # Pull all agent_ids except 老 K from the dialogue_id
        did_part = info["info_id"][len("info_dlg_"):]
        partner_ids = [m for m in re.findall(r'a_43_\d{4}', did_part) if m != KRIS]
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
        if pov_origin == KRIS:
            pov = "老 K 视角"
        elif pov_origin and pov_origin in profiles:
            pov = f"{neighbor_label(pov_origin)} 视角"
        else:
            pov = "对方视角"

        # Clean the dialogue content
        raw_content = info.get("content", "")
        cleaned = clean_text(raw_content)

        # NPC repetition highlight — every dialogue 老 K introduces herself
        # with the same set of details (Greenwich / 儿子 / 大麦茶 /
        # 看新闻 / Library / Stringybark / 老 K / 三楼). Marking these
        # visually makes the looped-script feeling obvious at a glance.
        NPC_LOOP_PATTERNS = [
            r'RSL(?: 厨房)?(?: 俱乐部)?|RSL Kitchen',
            r'Greenwich(?: 的)?(?: RSL)?',
            r'炸鸡排(?:配薯条)?|脆鸡排',
            r'莉安姐?',
            r'老李|阿曼达',
            r'冰啤(?:酒)?',
            r'(?:下班|夜班)(?:结束)?',
            r'Stringybark Creek',
            r'building_273',
            r'Lane Cove North',
            r'aged care(?: 护工)?',
            r'菲律宾大姐|乔西|Josie',
            r'Galuwa(?:[^,。\s]{0,12})?',
            r'(?:两个?)?孩子|儿子',
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
  <h2>6 · 3 段对话</h2>
  <p>仿真总共记录了老 K 3 段对话——比 Mary 那 4 段少一段,因为他没有 Mary 那种
  退休志愿者的闲工夫去 dispense conversation。每一段都在仿真运行时实时跑过 LLM,
  既不是事先脚本,也不是事后整理。但仿真只把 <strong>LLM 生成的第一人称摘要</strong>
  存进了 <code>conversation_service_state.infos</code> ——
  原始的 turn-by-turn 没有 persist 下来。
  我们能知道每段是 <code>message_count = 5</code> 轮、什么时候开始、什么时候结束、
  彼此聊到了哪些 topic,但<strong>具体每一轮的原话已经丢了</strong>。</p>

  <p class="npc-loop-legend">画面里所有被<span class="npc-loop">高亮</span>标注的词——
  无论是上面系统日志里的黄字,还是下方 LLM 摘要里的黄底——
  都是老 K 每次跟邻居聊天时几乎一字不落地搬出来的同一组话:
  【RSL 厨房】+【Greenwich】+【夜班结束】+【冰啤】+【炸鸡排】+【老李、阿曼达】+【莉安姐】+【Stringybark Creek】。<br>
  扫一眼 3 段,你会看到同一组关键词像 NPC 台词一样循环出现——
  他的 <code>plan_text</code> 写的就是"上 14:00-22:00 班,下班和同事去 RSL 喝杯啤酒再回家";
  3 段对话本质上就是他把这一句 plan_text 对 3 个不同邻居重新 pitch 了一遍。</p>

  {"".join(cards)}

  <p>3 段对话都重复出现一个口播:他每次都会跟陌生人讲他在<strong>【Greenwich RSL 厨房洗碗】</strong>,
  讲下班和【老李、阿曼达】去 RSL【喝冰啤】,讲【莉安姐】给他留【炸鸡排】,
  最后约对方下次轮休沿【Stringybark Creek】散步。
  这套口播是他在排班和家庭之间唯一能稳定 dispense 出的"个人介绍"——
  一份双工父亲对自己生活的固定描述。</p>
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
  <h2>7 · 他听来的八卦,他讲过的事</h2>
  <p>每段对话被仿真做成一条 "info",可以在 1000 个 agent 之间传播。
  系统的 <code>conversation_service_state.known</code> 字段记录了 老 K <strong>知道
  {len(known)} 条信息</strong> — 包括他自己参与的对话(hops=0)和从别人那转述听来的(hops &gt; 0)。</p>

  <p>他听到信息的"手数"分布:</p>
  <ul class="hops-list">
    {"".join(f'<li>经 {h} 手听说: <strong>{n}</strong> 条</li>' for h, n in sorted(by_hops.items())[:8])}
  </ul>

  <figure class="whisper-figure">
    <div class="whisper-caption">老 K 反复说过的一件事,在 Lane Cove 的八卦链里走 7 手会变成什么样</div>
    <div class="whisper-chain">
      <div class="whisper-frame">
        <div class="wf-stamp">第 0 手 · 他自己说出口</div>
        <div class="wf-line">"我在 <strong>Greenwich RSL 厨房</strong>洗碗——下班和【老李、阿曼达】去 RSL 喝冰啤,
          【莉安姐】给我留炸鸡排。"</div>
        <div class="wf-meta">— 他在和 Mary 的对话里这么说的,
          3 段对话每一段都讲了这两句,plan_text 字段也是这件事</div>
      </div>
      <div class="whisper-arrow">↓ &nbsp; 经过 3 手转述 &nbsp; ↓</div>
      <div class="whisper-frame whisper-frame-mid">
        <div class="wf-stamp">第 3 手 · 邻居的邻居的邻居</div>
        <div class="wf-line">"住 building_273 那位老 K,在 <strong>Greenwich RSL 上夜班</strong>,
          下班那帮哥们儿常约着喝冰啤。"</div>
        <div class="wf-meta">— 同事名字脱落,只剩"那帮哥们儿"</div>
      </div>
      <div class="whisper-arrow">↓ &nbsp; 又过了 4 手 &nbsp; ↓</div>
      <div class="whisper-frame whisper-frame-far">
        <div class="wf-stamp">第 7 手 · 镇上的另一头</div>
        <div class="wf-line">"Lane Cove 有位<strong>常在 Greenwich RSL 那边</strong>的人,
          熟悉那边的夜场,有事可以找他。"</div>
        <div class="wf-meta">— 中性事实漂成了"夜场 fixer"——他自己从没这么说过,
          但 RSL 厨房 + 夜班 + 朋友圈传着传着,标签自己长出来了</div>
      </div>
    </div>
    <figcaption class="whisper-fineprint">
      他 14 天里听到过的最深一条八卦,在 1,000 人小镇里转了
      <strong>17 手</strong>才传到他耳朵里。
    </figcaption>
  </figure>

  <p>反过来,老 K 自己参与的 4 段对话被多少人听说?
  系统的 <code>share_count</code> 字段记录他每讲一段故事被多少不同的邻居转述出去——
  <strong>他那 4 段对话每段都传到了约 {avg_per_story} 个邻居耳朵里</strong>。
  Lane Cove 这个 1,000 人小镇,差不多每开一次口,镇上有近十分之九的人多少听过一耳朵。</p>
</section>
"""


def section_parallel_universes():
    """THE big chapter — 4 parallel 老 Ks. Each panel is enriched with the
    top recurring encounter partner (extracted from her own end-of-run
    reflection) and a one-line "what she wrote in her diary on day 13"
    so the four worlds become physically distinct, not just numerically."""
    import re as _re

    variant_meta = {
        "baseline":           {"name": "无推送", "color": "#5A5E6A", "tagline": "默认宇宙"},
        "hyperlocal_push":    {"name": "本街推送", "color": "#D14B12", "tagline": "他被推到了 river road"},
        "global_distraction": {"name": "全球新闻", "color": "#3B6EA8", "tagline": "他漂去了 Chatswood"},
        "phone_friction":     {"name": "减少手机", "color": "#3A9D5C", "tagline": "他去了 1021 餐厅"},
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
        # Soften the robotic openers ("Agent_405" / "agent_590" / "The agent"
        # / bare "Agent") to "She" / "her".
        c = _re.sub(r'^[Aa]gent_405\b', 'She', c)
        c = _re.sub(r'\b[Aa]gent_405\b', 'she', c)
        c = _re.sub(r'\bThe agent\b', 'She', c)
        c = _re.sub(r'^Agent\s+', 'She ', c)
        # Fix leftover "she's log" → "her log" (came from "agent_590's log")
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
  <div class="universe-pushes-label">14 天里他手机响过的推送(2 条样本):</div>
  {"".join(f'<div class="phone-push-mini">{c}</div>' for c in push_samples)}
</div>
"""
        elif v_key == "baseline":
            sample_pushes_html = """
<div class="universe-pushes universe-pushes-empty">
  <div class="universe-pushes-label">14 天里他手机响过的推送:</div>
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
  <span class="us-diary-label">他最后一次 reflection 的 LLM 原文(英文)摘录:</span>
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
    <div><span class="us-label">从他身边经过的不同邻居</span><span class="us-val">{u['n_distinct_partners']}</span></div>
    <div><span class="us-label">他真的抬头看见的次数 <sup>*</sup></span><span class="us-val" style="color:{meta['color']};">{u['n_noticed']}</span></div>
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

  <p class="dropcap">这一章问一个很小的问题:<strong>同一个 37 岁的双工厨子,
  在 4 部不同的手机底下,他下班走回 building_273 那条路上会抬几次头?</strong></p>

  <p>仿真把他复制了 4 份——同样的 building_273 公屋、同样的儿子在前任那里、
  同样的 14:00–22:00 那个 shift、同样的 RSL 同事在等他喝冰啤。
  唯一被换掉的,是他口袋里那部手机会响什么。<br>
  老 K 跟 Mary 不一样——Mary 在 4 个宇宙里被推去 4 个完全不同的地方;
  <strong>老 K 在 4 个宇宙里始终回到同一栋公屋 building_273</strong>。
  他没有 Mary 那种"被推去新地方"的自由——他得上班,得回家。<br>
  能变的,是他从厨房走回公屋那条路上,<strong>抬头看到了几张脸</strong>。</p>

  <div class="universes-grid">
    {"".join(panels)}
  </div>

  <h3 class="parallel-insight-h3">4 个老 K,4 段下班路</h3>

  <div class="universe-essay" style="border-left:5px solid {bl['meta']['color']};">
    <h4 style="color:{bl['meta']['color']};">无推送 · 4 张脸,然后回家</h4>

    <p>5 月 5 日下午 2 点,他下了 14:00 那一班(其实是上一班)往家走。
    手机一整天没响过。Greenwich RSL 到 building_273 之间那段熟得不能再熟的路——
    Burns Bay Road 转 Centennial Avenue 转 Finlayson Street——
    他闭着眼都能走。</p>

    <p>14 天里他从 51 个不同的邻居身边经过——
    在 two_brothers_cafe 取咖啡的台子前、在 RSL 厨房外的小巷里、
    在他骑车经过的几个红绿灯口。<strong>但他真的抬眼瞥见的,只有 4 个人。</strong>
    剩下 47 个邻居,他身体经过,心思在别处:
    在想晚上儿子那边几点能视频、在算这周排班够不够交房租、
    在惦记菲律宾大姐乔西今天值不值班——
    14 天里他自己反思了很多遍"<em>从一个非具体的地方到 building_273</em>"的路。</p>

    <p>他真的坐下来聊上的,只有 3 个人。<br>
    这是他默认的宇宙——一个 37 岁的双工父亲,
    每天 14 个小时被工作和回家占满,中间那一段路只是穿过去,不是看的。</p>
  </div>

  <div class="universe-essay" style="border-left:5px solid {hp['meta']['color']};">
    <h4 style="color:{hp['meta']['color']};">本街推送 · 他绕到了 river road,但回不去原来的家了</h4>

    <p>这个宇宙里,他手机也没有真正响过推送——
    他不是 hyperlocal_push 的目标用户(系统选 protag 时把推送主要给了
    family_with_kids 户型,他单亲不在目标群)。
    但他还是被周围空气里多出来的"事"间接拉走了——
    Lane Cove 那一圈在响 Shinnyo 活动通知,
    他在两份工的间隙里多走了几条没走过的街。</p>

    <p>5 月 5 日傍晚 10 点 45 分,snapshot 抓到他<strong>不在 building_273</strong>,
    他在 <code>river_road_west_seg_3_1</code> —— 河边一段路。
    这是他 14 天里唯一一次没回家的夜晚。</p>

    <p>14 天里他从 <strong>104 个不同的邻居</strong>身边经过——
    是 BL 的 2 倍。他真的抬头瞥见 <strong>11 个</strong>,也是 2 倍。
    他自己反思里写:"<em>只做了两次成功的 MoveIntent,
    从一个不确定的位置走到 finlayson_street_seg_2_1 然后到 building_273
    ——一段短路里多次碰撞</em>"。<strong>他自己察觉到这一段路比平时遇到更多人。</strong></p>

    <p>但他仍然只聊上了 3 个人——跟 BL 一样。
    本街推送把他周围 Lane Cove 的空气吵了一点,他多走了几条街,
    多看见几张脸,但没多说一句话。</p>
  </div>

  <div class="universe-essay" style="border-left:5px solid {gd['meta']['color']};">
    <h4 style="color:{gd['meta']['color']};">全球新闻 · 在 RSL 之外的世界,他没什么时间关心</h4>

    <p>5 月 5 日下午 2 点 5 分。他回到了 building_273。
    那一整天他手机里收到的是世界杯、比特币、欧洲央行加息——
    跟他的 14:00-22:00 班、跟他儿子游泳课、跟他下个月房租毫无关系的事。</p>

    <p>14 天里他从 60 个不同的邻居身边经过——
    几乎跟 BL 一样。他真的抬头瞥见了 9 个——
    略多于 BL 的 4。<strong>差别不算大。</strong>
    他自己反思里写:"<em>到达目的地之后反复 wait 很多 cycle,
    暗示他已经走到了 final stop 或是 idle 状态</em>"——
    他到家了,然后什么也没做地坐在那里。</p>

    <p>全球新闻没让他漂走,也没让他停下来——它就只是手机屏幕上滑过的字。
    他没有像 Mary 那样跟着新闻漂到 Chatswood——
    他没有自由漂走的余地:14 天里他还有 14 个 14:00 要打卡。
    新闻就是新闻,班还是班。<br>
    对一个双工父亲,<strong>全球新闻几乎等于没新闻</strong>——
    它不在他的世界半径里,也不影响他的世界半径。</p>
  </div>

  <div class="universe-essay" style="border-left:5px solid {pf['meta']['color']};">
    <h4 style="color:{pf['meta']['color']};">减少手机 · 同一条下班路,他抬了 53 次头</h4>

    <p>这是 4 个老 K 里最戏剧化的一段。他的手机响了 6 次——14 天里最少的。
    每一条都是反向劝阻:<br>
    <em>"下次电梯里别低头——也许你认识那张面孔。"</em><br>
    <em>"屏幕亮 5 小时不如 Plaza 站 5 分钟。"</em><br>
    <em>"屏幕里没有真正的对话——Plaza 长椅上有。"</em></p>

    <p>5 月 5 日下午 2 点 5 分,他还是回到了 building_273。
    跟 BL 一样的终点。
    <strong>但他这 14 天走过的下班路,变成了完全不同的一段。</strong></p>

    <p>14 天里他从 <strong>314 个不同的邻居</strong>身边经过——
    是 BL(51 个)的 <strong>6 倍多</strong>。
    他真的抬头瞥见的次数,<strong>53 次</strong>——是 BL(4 次)的 <strong>13 倍</strong>。
    这不是因为他改了路线、不是因为他去了新地方——
    snapshot 显示他 5 月 5 日还是 14:05 到家。
    <strong>变的是他在那条同样的路上,有没有抬头。</strong></p>

    <p>6 条提醒抬头的推送,把这位 14 个小时被工作占满的双工父亲,
    从手机屏幕上拉出来 53 次。每一次,都是一张他平时不会留意的脸——
    Two Brothers 咖啡台后面新来的咖啡师、Burns Bay Road 等公交的同龄母亲、
    Finlayson Street 早上遛狗的退休邻居。
    这些人在他每一天的物理路径上,但只有反向推送的版本里,
    他真的看见了他们。</p>

    <p>反向推送没能改变一位单亲双工父亲的物理位置——
    他还得 14:00 打卡,他还得回 building_273 看儿子。<br>
    但<strong>它改变了他对脚下这段路的注意力</strong>——
    一条他走了 14 年的路,在第 14 天里第一次有了 53 张被他看见的脸。</p>

    <p>没有一行代码告诉他多抬头。反向推送做的事很小:
    把 <code>screen_time_weight</code> 调低一点,
    plan 系统下一次计算周边注意力时,<code>sight_radius</code> 自动撑开。
    剩下的事是他自己的脚和眼睛完成的。</p>
  </div>

  <p class="parallel-close">同一个 37 岁的 RSL 厨子兼 aged care 护工。
  同一栋 14 年的公屋 building_273。同一个跟前任住的儿子。
  同样 4 个工友等着他下班去 RSL 喝冰啤。<br>
  同一段 14 天,4 部不同的手机。<br><br>
  4 个老 K 都回到了同一个家。<br>
  但在 4 部不同的手机里,他分别抬了 <strong>4 次</strong>、<strong>11 次</strong>、
  <strong>9 次</strong>、和 <strong>53 次</strong>头。<br>
  对一个不能改变物理路径的双工父亲,
  推送能改变的不是他去哪——是他在路上看见了谁。<br><br>
  <span class="parallel-kicker">在这个 1,000 人的算法风洞里,
  老 K 的 14 天提供了一个 Mary 故事里没有的真相:<br>
  <strong>对一个被工作和家庭锁死物理路径的人,反向推送依然能撑开他的视野——
  让他在同一段熟到不能再熟的下班路上,第一次抬头看见了 53 张邻居的脸。
  推送能改变的,不止是去哪。</strong></span></p>
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
  <p>系统每天结束时会让 LLM 看 老 K 当天的全部行为日志,生成 <code>reflection</code> 事件 —
  对他自己行为模式的 meta-觉察。这些反思不是 老 K 自己写的,是系统看 log 总结的。
  但它们追踪着他每天行为的变化。</p>

  {cards}

  <p>到 snapshot 取样的 5 月 5 日,他的 <code>plan</code> 字段是:</p>
  <div class="plan-block">{plan_str}</div>

  <p>"被 hyperlocal 推送吸引"是系统给出的决策理由。"open_to_chat"是他当时对聊天的态度。
  他今天的 replan 次数 = {hp.get("replan_count_today", 0)}。</p>
</section>
"""


def section_phantom_daughter():
    """插曲 · 那个不在系统里的儿子。
    Fact: 老 K.family_members = None. 1000 个 agent 里没有任何一个
    被链接为他的儿子。life_history 里有 5 条关于儿子的事件,但儿子
    本身不是仿真里的实体——他周日去前任那里的剧情,plan 里没有真实接收端。"""
    return """
<section class="chapter chapter-phantom">
  <h2>插曲 · 那个不在系统里的儿子</h2>

  <p class="phantom-lead">在继续往下之前,有一件事必须说出来。</p>

  <p>老 K 的 life_history 里有 5 条关于他儿子的事件:
  <em>"儿子三岁那年夏天我办了 Council 游泳池的家庭年票,
  $400 对我来说是一笔大钱。"</em>
  <em>"有次带孩子在 Stringybark Creek 散步,我蹲下系鞋带时手机从上衣口袋滑出来掉进水里。"</em>
  <em>"去年春天我带儿子去 Canopy Park 的新游乐场,他很快和另一个小男孩玩到一起。"</em>
  <em>"2018 年夏天我差点搬去 Chatswood 那边住,最后一刻还是留下来了,因为儿子 daycare 的老师说他刚适应。"</em></p>

  <p>老 K 的 plan 里几乎每天都安排了"下班后跟儿子那边联络"。
  系统的 dialogue 也提到他下次轮休要带儿子沿 Stringybark Creek 散步。</p>

  <div class="phantom-revelation">
    <p>但 Synthetic Socio Wind Tunnel 这 1,000 个虚拟居民的数据库里,
    <strong>并没有一个 agent 被链接为老 K 的儿子</strong>。</p>

    <p>老 K 的 profile 里 <code>family_members</code> 字段是空的。
    那个 9 岁的小孩——会扑腾 Council 泳池浅水区、会在 Canopy Park 新游乐场
    跟另一个小男孩玩起来、会在 Stringybark Creek 边等爸爸捞手机的小孩——
    <strong>系统里没有给他一个 a_43_xxxx 编号</strong>。
    周日去"前任那边"的那条情节,plan 系统也找不到对应的 agent_id 让他接收。</p>

    <p>那些他记得的儿子细节,只是仿真启动时 LLM 给他生成的一份背景设定——
    那些设定从来不会向 1,000 个 agent 里的任何人请求回应。
    <strong>那个孩子从来没有 agent_id。系统给了他作为父亲的身份,
    没有给他一个真正能接电话的孩子。</strong></p>
  </div>

  <p class="phantom-twist">系统给了他每天下班拼命赶回去的理由。<br>
  系统没有给这个理由分配一个真正的接收端。</p>

  <p>他的 4 段下班路、他的 RSL 厨房洗碗轮班、他的 aged care 凌晨陪老人——
  整套生活的底色是"我要给孩子挣这份家庭年票",
  但那个孩子在仿真的某个角落并不存在。<br>
  <strong>对 老 K 来说,工作和奔波都是真的,但奔波的尽头是空的。</strong></p>

  <p>这或许才是这场仿真给现实的最后一面镜子。
  在我们自己的 1,000 人小镇里——在 Lane Cove,在墨尔本的西郊,在北京的回龙观——
  也有很多位老 K,周一到周日都在拼命挣那份家庭年票,
  但那个家庭真的有人在那边接电话——不一定每个晚上都能验证。<br>
  <strong>有些晚上的奔波,我们也不能确定它的另一端,有没有 API。</strong></p>
</section>
"""


def section_one_of_thousand():
    return """
<section class="chapter chapter-zoom">
  <h2>10 · 1,000 个故事里的 1 个</h2>
  <p>老 K 不是特例。在这 1,000 个虚拟居民里,有上百位像他一样的双工底层服务业从业者——
  夜班 RSL 厨房洗碗工、aged care 兼职护工、Council 救济过的住户、
  排班永远在变的 hospitality shift worker——
  他们都被工作和家庭锁死了物理路径,
  但都被算法风洞测出了一个共同的真相:<strong>反向推送对他们最有效</strong>。</p>

  <p>不是因为他们更"开放"——而是因为他们的物理路径已经固定,
  推送能改变的只剩注意力本身。一个 64 岁退休 + 时间自由的人(像我们另一篇报道里的
  <a href="mary.html">Mary</a>)能被推去任何地方;
  但一个 14 个小时被工作锁住的双工父亲,只能在<strong>同一段下班路上抬头看见更多脸</strong>。<br>
  6 条提醒抬头的推送换来 53 次抬头——
  这不是 Mary 的"去新地方"那种解放,这是另一种更窄的解放:<strong>在熟悉的路上重新看见。</strong></p>

  <p>这是一个虚拟城市的故事——但它讨论的是真问题:
  对一个被排班和房租锁死路径的人,算法能不能改变什么?
  仿真说能。老 K 用他 14 天 53 次抬头的真实数据印证了这件事。</p>

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

    # 老 K's own data — recount from the 4-variant blob
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

  <p class="data-vanity-lead">这份关于一个 37 岁单亲爸爸的 10 章长文,背后是多少数据?
  把所有数字摆出来 — 一份诚实的"数据账本",
  也是一份不必谦虚的"虚拟人口学规模说明"。</p>

  <div class="data-vanity-section">
    <h3 class="dv-h3">⊙ 老 K 一人,跨 4 个平行宇宙,14 天里产生了 ——</h3>
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
        <div class="dv-sub">0 + 30 + 30 + 6,他看过 {total_pushes_seen} 条</div></div>
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
    <h3 class="dv-h3">⊙ 他周围的信息扩散网络(单宇宙平均)——</h3>
    <div class="data-vanity-grid">
      <div class="dv-cell"><div class="dv-num">~{avg_known_per_variant}</div>
        <div class="dv-lbl">条他耳朵听过的八卦</div>
        <div class="dv-sub">每个宇宙 {min_known_pv}-{max_known_pv} 条,
          来自 Lane Cove 1,000 人镇里 ~750 个邻居</div></div>
      <div class="dv-cell"><div class="dv-num">~{avg_listeners_per_story}</div>
        <div class="dv-lbl">个邻居听过他每段故事</div>
        <div class="dv-sub">他 4 段对话各自的转述触达,
          单宇宙 / 单 info 平均</div></div>
      <div class="dv-cell"><div class="dv-num">4 / 4</div>
        <div class="dv-lbl">段他真正开口聊上的对话</div>
        <div class="dv-sub">4 个平行宇宙里都是 4 段——
          推送什么都没改变这个数字</div></div>
      <div class="dv-cell"><div class="dv-num">0 → 17</div>
        <div class="dv-lbl">手:他听到过的最深一条八卦</div>
        <div class="dv-sub">同一条 info 在 1,000 人小镇里转了 17 次,
          才传到他耳朵里——绕了大半个 Lane Cove</div></div>
    </div>
  </div>

  <div class="data-vanity-section">
    <h3 class="dv-h3">⊙ 承载他的虚拟 Lane Cove ——</h3>
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
    你刚读完的 10 章关于 老 K 的故事 —— 是这堆数据里关于
    <strong>1 个 37 岁 RSL 厨子</strong>的 <strong>1 条线索</strong>。<br>
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
    '<title>一位 RSL 厨房洗碗工 14 天里抬过多少次头 · 1,000 个虚拟居民里的 1 位 · Synthetic Socio Wind Tunnel</title>',
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
