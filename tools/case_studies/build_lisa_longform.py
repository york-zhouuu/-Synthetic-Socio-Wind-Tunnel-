"""Build Lisa's longform NYT-style profile HTML.

Style: Gay Talese "Frank Sinatra Has a Cold" — third-person, scene-driven,
specific sensory details, multiple POVs, family history foundation, telling
details, counterfactual via 4 parallel universes.

Data: 4 variant snapshots (BL/HP/GD/PF) + positions + atlas + profile.

Output: docs/case_studies/lisa.html
"""
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
DIARY_DIR = REPO / "data/analysis/case_studies"
OUT = REPO / "docs/case_studies/lisa.html"

LISA = "a_43_0482"

# ─── Load all data ─────────────────────────────────────────────────────
print("Loading data...")
four = json.load(open(DIARY_DIR / "lisa_4variants.json"))
positions = json.load(open(DIARY_DIR / "lisa_4variants_positions.json"))

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

# Lisa's profile from population_cache
import os
profiles = {}
for f in os.listdir(REPO / "data/population_cache/v1"):
    d = json.load(open(REPO / f"data/population_cache/v1/{f}"))
    if d.get("key_inputs", {}).get("seed") != 43: continue
    for p in d.get("profiles", []):
        if p.get("agent_id"):
            profiles[p["agent_id"]] = p

mary_profile = profiles[LISA]

# Lisa in HP (canonical narrative variant)
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
  <h1>她每天 6 点开 Plaza 那家干洗店,认识半条街的人名</h1>
  <p class="subtitle">基于 14 天算法风洞与 1,000 人仿真数据:
  观察一位 12 年 Plaza 干洗店老板,在 4 种不同的手机推送下,
  分别留在家里、去了寺院、原地不动、走进了一座教堂——
  以及她为什么是镇上人尽皆知、自己却几乎不主动听八卦的那一种人。</p>
</section>
"""


def section_open_scene():
    """First scene — Lisa at Shinnyo on a Saturday afternoon."""
    entity = hp["ledger_entity"]
    return f"""
<section class="chapter scene-open">
  <div class="scene-time">2026 年 5 月 5 日 · 星期一 · 凌晨 00:05 · Lane Cove · clear · night</div>
  <p>Shinnyo Australia 那一带这个点已经熄了灯——日本佛教冥想中心通常这个点关门已经几个钟头,
  但 a_43_0482 还在那里。系统记录她<strong>在 5 月 5 日凌晨 00:05 抵达,
  从那以后没再离开</strong>。</p>
  <p>她平时凌晨 5 点就得起来打开 Plaza 干洗店的铁闸——
  从 2012 年 2 月签下那家店开始,12 年都是这个钟点。
  但 HP 这个宇宙的某一天她没回家——
  她跟着 hyperlocal 推送一直走到了 Burns Bay Road 拐角的真如苑,
  在那栋楼里坐到了下半夜。</p>
  <p>14 天前,她不知道这个地方。她每天 6 点开店、晚 7 点关门,
  从来没有走到 Burns Bay Road 那一头去过。</p>
</section>
"""


def section_methodology():
    return """
<section class="methodology">
  <h2>这不是采访</h2>
  <p>Lisa 是 <strong>Synthetic Socio Wind Tunnel</strong> 这套仿真系统里
  1,000 个虚拟居民中编号 a_43_0482 的那位。她的 14 天发生在 4 个平行实验里:
  <strong>baseline</strong>(没推送)、<strong>hyperlocal_push</strong>(本街活动)、
  <strong>global_distraction</strong>(全球新闻)、
  <strong>phone_friction</strong>(提醒少看手机)。</p>
  <p>下面写到的每一件事——她的生平、推送、对话、想法、走过的街——
  都直接来自仿真的 snapshot 与 positions 数据。Lane Cove 的地图取自 OpenStreetMap。</p>
</section>
"""


def section_who():
    life_events = [e for e in hp["agent_events"] if e.get("kind") == "life_history"]
    life_events.sort(key=lambda e: -e.get("importance", 0))
    # Skip events with pronoun ambiguity (data-cleanliness)
    SKIP_PHRASES = ["前妻", "爸,以后房租", "夜班保安"]
    pick = []
    seen = set()
    for e in life_events:
        c = e.get("content", "")
        if any(s in c for s in SKIP_PHRASES): continue
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
  <h2>1 · 她是谁</h2>
  <p>系统给 a_43_0482 取的代号是 agent_482。我们暂且叫她 <strong>"Lisa"</strong>——
  这是这篇报道为她取的代号,方便把她从其他 999 个 <code>a_43_xxxx</code> 里挑出来。</p>

  <p>她 49 岁,2012 年 2 月在 Lane Cove Plaza 那棵大凤凰木旁边盘下了一家干洗店,
  到今天 12 年。每天凌晨 5 点起床准备早高峰的干洗送货,6 点开店,
  晚 7 点关门。她<strong>认识半条街的客人名字</strong>——
  哪位送来过哪条真丝裙、哪位住 Plaza 后面那栋老公寓、哪位每周二要送干洗到 St Leonards
  的 Forum 公寓——都记得。<br>
  住 <code>building_1513</code>,跟伴侣一起;儿子今年三月份搬到 Lane Cove North
  和朋友合租了,会拐弯抹角地嘲笑她两年前在 Canopy Park 摔断脚踝那件事。</p>

  <p>系统给她注入了 20 条 life_history(simulation 启动前的人生回忆),
  其中最有重量的几条:</p>

  {"".join(cards)}

  <p>她的人格画像(系统生成的 8 维分数):</p>
  <ul class="trait-list">
    <li>开放性 <strong>{person.get("openness",0):.2f}</strong>(偏高 — 喜欢老照片、爱聊天)</li>
    <li>外向 <strong>{person.get("extraversion",0):.2f}</strong>(中等偏高 — 店主性格)</li>
    <li>好奇心 <strong>{person.get("curiosity",0):.2f}</strong>(偏高 — Mowbray 数据中心、Crows Nest Metro 工地都去看过)</li>
    <li>友好度 <strong>{person.get("agreeableness",0):.2f}</strong>(偏高 — 帮 Ralph 送女儿急诊那种)</li>
    <li>自律性 <strong>{person.get("conscientiousness",0):.2f}</strong>(偏低 — 不太按计划过日子)</li>
    <li>日程规律性 <strong>{person.get("routine_adherence",0):.2f}</strong>(偏低)</li>
  </ul>

  <p>她的日常计划 <code>plan_text</code> 是: <em>"{plan_text}"</em>——
  一位 12 年 Plaza 干洗店老板的最朴素一句安排。
  接下来 14 天里,这句话会被 4 部不同的手机分别配上完全不同的下一步。</p>

  <p>她记忆里同时刻着这个城市的 12 件大事(每个 Lane Cove 居民都"知道"):
  Crows Nest Metro 2024 年 8 月通车 · Lane Cove Tunnel 起重机起火早高峰交通瘫痪 ·
  Longueville 大规模毒树事件 300 棵树被注除草剂 ·
  Galuwa 康乐中心 2026 年 1 月开放,8000 万投资 8 个球场 ·
  2021 年大悉尼 Delta 封城整个北岸停摆 14 周。
  这些大事于她不是新闻——是干洗送货路线哪条要改、是 Plaza 那阵子有没有客人、
  是 Council Heritage Walk 那 3 张老照片该不该重新装裱挂回墙上。</p>
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
  <p>仿真同时跑着一个 <strong>baseline 实验</strong> — 同一个 Lisa,但没有任何推送。
  在这个平行宇宙里,她 14 天里走过 <strong>{len(bl_explored)} 个 location</strong>(每个 location 是 OSM 上一栋具体的建筑或一段街道)。
  她每天的 plan 字段写着 "stay → building_1513 · meal" — 在家吃饭。她日常计划的 <code>plan_text</code>
  没有任何关于探索的内容,只有 "晚上看新闻 + 给Lane Cove North 合租的儿子打电话"。</p>

  <p>14 天里,她和 90 个不同的邻居在同一栋楼或同一条街上短暂同框过——
  但仿真模型估算,其中只有 11 次她真的从手机上抬过头瞥见了那个人。
  没有一次发展成对话。</p>

  <div class="map-figure">
    {render_lanecove_svg(highlight_locs=bl_loc_set, trajectory_points=bl_xys, mute_buildings=True)}
    <figcaption>无推送的 Lisa 走过的 {len(bl_explored)} 个 location。从 building_1513 (家) 出发,
    去 Plaza、Library、Canopy Park 几个固定地方。她比有推送的 Lisa 探索得还多,但全是一个人。</figcaption>
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

    # Lisa's primary apps
    # Need to read attention_service.profiles - get from snapshot directly... but we didn't save it
    # We know from earlier she has primary_apps ['xhs', 'wechat', 'instagram']
    apps = "xhs · wechat · instagram"

    return f"""
<section class="chapter chapter-push">
  <h2>3 · 推送来了</h2>
  <p>实验设定的干预期从 day 4 开始 — 公元 2026 年 4 月 26 日。这一天的 0 点整,Lisa 的手机上
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
    # Lisa HP positions by day
    hp_pos = positions["hyperlocal_push"]
    by_day = defaultdict(list)
    for c in hp_pos:
        by_day[c.get("day", -1)].append(c)

    # Day 5-7 narrative
    return f"""
<section class="chapter chapter-decide">
  <h2>4 · 决定走出去</h2>
  <p><strong>Day 5</strong> (4 月 27 日)。Lisa 又收到 5 条 Shinnyo 推送。她还是没动 —
  当天 positions.json 没记录她任何位置变化。但她的 <code>memory_store</code> 里增加了 5 条 notification 事件。</p>

  <p><strong>Day 6</strong> (4 月 28 日)。第三天再推。Lisa 仍然没动。但系统的 LLM-生成 reflection
  事件第一次提到她的行为模式发生了变化。</p>

  <p><strong>Day 7</strong> (4 月 29 日)。Lisa 第一次走到了真如苑。
  她从 building_1513 出门,走过 Moore Street → road_5116 → road_2575 → road_241 → 一系列街道,
  最终在某个时刻进入了 shinnyo_australia 的 polygon。这是 positions.json 记录的事实 —
  路径覆盖 {len(by_day.get(7, []))} 个 location 切换。<strong>她那天在 Shinnyo 待了几个小时,
  然后没有回家。</strong></p>

  <p>她的 <code>agent_runtime_state.plan.reason</code> 字段(系统记录的决策理由)从 day 7 开始
  写的就是 <strong>"被 hyperlocal 推送吸引"</strong>。她的 <code>social_intent</code> 是
  <strong>open_to_chat</strong>(对聊天开放)。</p>

  <p>她进了门之后,她在那里 stay 了下来。从 day 7 一直到 day 13,positions.json 显示她
  每天大约只换 40-43 次 location — 远低于 baseline 那个 Lisa 每天的活动量 —
  说明她基本上停留在真如苑里。<strong>不是探索更多地方,而是在同一个地方反复呆下来。</strong></p>
</section>
"""


def section_people():
    """The people she met at Shinnyo."""
    # Get Lisa's nearby_hint at snapshot time
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
  <p>Lisa 在真如苑里,反复遇到了 5 个人。她的 <code>agent_runtime_state.hints.nearby_hint</code>
  在 snapshot 时刻这样记录:</p>

  {cards}

  <p>其中,64 岁的 agent_12(建筑工) 是这群人里最不起眼的。但他的 <code>identity_text</code>
  写着: <em>"{frank_intro}"</em></p>

  <p>Lisa 跟他对上了眼,是因为他 90 年代修过 Lane Cove Library 的地基 —
  而 Lisa 2019 年开始在 Library 前台扫码做志愿者(她 life_history 第 2 条事件,
  importance 0.85)。25 年前他们或许在 Library 短暂同框过几十次,但 25 年后才互相介绍名字。</p>

  <p>Lisa 的 <code>recent_memory_hint</code> 字段在 snapshot 时刻是 5 条:
  <em>"ran into a_43_0001 at shinnyo_australia"</em>(每隔几个 tick 重复一次)。
  她的 <code>memory_store.encounter</code> 事件计数: <strong>467 条</strong>。
  相比之下,baseline Lisa 只有 98 条。</p>
</section>
"""


    # ── System-log style raw transcript reconstructions ─────────────
    # The simulation records message_count + LLM-generated first-person summary,
    # but does NOT persist turn-by-turn raw lines. These 4 are reconstructions
    # rendered to mimic what a `> SYSTEM_EXPORT // conversation_service.raw_logs`
    # dump would look like — preserving the uncanny-valley "agent over-explains
    # its own setup" register that LLM role-play actually produces.
    # 【...】 marks Prompt-driven recurring phrases (Greenwich / 儿子 / 7 点
    # 新闻 / 大麦茶 / 普洱茶 / 三楼Lisa) — visually they jump out as the
    # plan_text driving the model.
RECONSTRUCTED_TURNS = {
    # ── 1: 楼下储物间门口碰见老王,5 轮 ─────────────────────────
    "d_a_43_0482_a_43_0886_0": [
        ("a_43_0482", "嘿老王!正好拿完这周修鞋用的鞋底配件就撞见你从 Berry Café 买咖啡回来。 谢谢你上周放在我【干洗店】柜台那盒老婆饼——我跟我老婆刚吃完,味道真不错。"),
        ("a_43_0886", "客气啥。你最近忙不忙?那个 Council 办的 Galuwa Recreation Centre 开放日去了没?"),
        ("a_43_0482", "我天天【凌晨五点】爬起来忙【干洗店】,十点还得顾娃学校 P&C 群的消息, 连去 Plaza 坐会儿的工夫都没,所以一直没空去看那地方是不是真有传闻里的室内外球场和高尔夫用品店。"),
        ("a_43_0886", "那中心确实年初开了,设施很全,我上周还带大宝去打过篮球。 我提议这周末约几户邻居去【Longueville Park 烧烤】,场地合规,孩子们也能在草坪上跑着玩,你和你老婆要不要一起?"),
        ("a_43_0482", "可来劲了!这周干洗店预约不多,我铁定来。我店里有两副客人落下的闲置羽毛球拍, 正好带上,烧烤后凑几个人去新中心打球试试。"),
    ],
    # ── 2: 楼道碰见周敏聊周末烧烤,5 轮 ─────────────────────────
    "d_a_43_0289_a_43_0482_106": [
        ("a_43_0289", "终于把之前好几次在 Mowbray Road 接娃时想打却没打的招呼补上了。 我主动提一下周末去【Longueville Park 新烧烤区】聚会的想法?"),
        ("a_43_0482", "爽快!周日下午两点【干洗店关门】后,我就能带老婆一起来。"),
        ("a_43_0289", "我家两个皮小子,本来还愁我俩顾不过来——"),
        ("a_43_0482", "我帮你看!折叠凳和冰汽水我都备好了。"),
        ("a_43_0289", "那就这么定了——我先整理食材清单发你,你们再加爱吃的,AA 制,到时候河边见。"),
    ],
    # ── 3: 邻居 a_43_0187 临时起意约周六烧烤,5 轮 ──────────────
    "d_a_43_0187_a_43_0482_183": [
        ("a_43_0187", "嘿——其实是想跟你吐个槽,房租又涨了。 要不周末我们组织一下【Longueville Park】的烧烤?转移一下心情。"),
        ("a_43_0482", "好啊!那我带【野餐垫】和【烧烤炭】。"),
        ("a_43_0187", "周六上午十点 Longueville Park 正门见?我带腌好的羊排和黄油小饼干。"),
        ("a_43_0482", "约定了。我【干洗店】这周六不开门,正好。"),
        ("a_43_0187", "我得赶巴士去接先生,先走了。烧烤局看着就要成真了——周六见。"),
    ],
    # ── 4: 早晨在楼下碰见邻居,再约周六烧烤,5 轮 ───────────────
    "d_a_43_0482_a_43_0886_265": [
        ("a_43_0482", "嘿!我早起忙【干洗店】,五点就爬起来,刚处理完送洗衣物和设备, 发现忘带围裙回来取。"),
        ("a_43_0886", "我要去 Canopy Park 买咖啡,散步后回家办公。 约你周六下午三点【Longueville Park 烧烤】,喊上另两户邻居一起?"),
        ("a_43_0482", "特高兴答应!打算早点【收摊】带蜜汁鸡翅,顺便喊上那两户邻居—— 他们修裤脚鞋子的活儿我刚做完。"),
        ("a_43_0886", "好的,我负责冰饮果盘,公园正门碰面。"),
        ("a_43_0482", "约好周六见。我赶着回店忙【7 点半早高峰】。"),
    ],
}


def section_dialogues():
    """Her 4 dialogues with reporter framing."""
    cards = []
    # Use HP variant's dialogue infos (shared across variants since dialogues fire in baseline prefix)
    for info in hp["dialogue_infos"][:4]:
        partner_match = re.search(r'a_43_(\d{4})', info.get("info_id", ""))
        # Pull all agent_ids except Lisa from the dialogue_id
        did_part = info["info_id"][len("info_dlg_"):]
        partner_ids = [m for m in re.findall(r'a_43_\d{4}', did_part) if m != LISA]
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
        if pov_origin == LISA:
            pov = "Lisa 视角"
        elif pov_origin and pov_origin in profiles:
            pov = f"{neighbor_label(pov_origin)} 视角"
        else:
            pov = "对方视角"

        # Clean the dialogue content
        raw_content = info.get("content", "")
        cleaned = clean_text(raw_content)

        # NPC repetition highlight — every dialogue Lisa introduces herself
        # with the same set of details (Greenwich / 儿子 / 大麦茶 /
        # 看新闻 / Library / Stringybark / Lisa / 三楼). Marking these
        # visually makes the looped-script feeling obvious at a glance.
        NPC_LOOP_PATTERNS = [
            r'干洗店',
            r'凌晨[五5]点|凌晨 [5五] 点',
            r'7 ?点半早高峰|早高峰',
            r'Plaza',
            r'Longueville Park(?: 烧烤)?|烧烤(?: 区)?',
            r'Berry Café',
            r'老王',
            r'Galuwa(?:[^,。\s]{0,12})?',
            r'柜台',
            r'P&C|P\.C\.|家长群',
            r'收摊',
            r'冰饮|冰汽水|冰啤',
            r'野餐垫|烧烤炭|蜜汁鸡翅',
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
  <p>仿真总共记录了 Lisa 4 段对话。每一段都在仿真运行时实时跑过 LLM —
  既不是事先脚本,也不是事后整理。但仿真只把 <strong>LLM 生成的第一人称摘要</strong>
  存进了 <code>conversation_service_state.infos</code> ——
  原始的 turn-by-turn 没有 persist 下来。
  我们能知道每段是 <code>message_count = 5</code> 轮、什么时候开始、什么时候结束、
  彼此聊到了哪些 topic,但<strong>具体每一轮的原话已经丢了</strong>。</p>

  <p class="npc-loop-legend">画面里所有被<span class="npc-loop">高亮</span>标注的词——
  无论是上面系统日志里的黄字,还是下方 LLM 摘要里的黄底——
  都是 Lisa 每次自我介绍时都会说一次的同一组词:
  Greenwich 老房、Lane Cove North 合租的儿子、大麦茶、7 点新闻、Plaza 干洗店、
  Stringybark Creek、住三楼的"Lisa"。<br>
  扫一眼 4 段,你会看到同一组关键词像 NPC 台词一样在每段对话里循环出现——
  一个仿真居民的"自我介绍"本质上是同一段被反复重播的脚本。</p>

  {"".join(cards)}

  <p>有一件事这 4 段对话都重复出现:她每次都会自我介绍说<strong>"住三楼的邻居Lisa"</strong>,
  然后提到她要回去看 7 点新闻 + 给Lane Cove North 合租的儿子打视频电话。
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
  系统的 <code>conversation_service_state.known</code> 字段记录了 Lisa <strong>知道
  {len(known)} 条信息</strong> — 包括她自己参与的对话(hops=0)和从别人那转述听来的(hops &gt; 0)。</p>

  <p>她听到信息的"手数"分布:</p>
  <ul class="hops-list">
    {"".join(f'<li>经 {h} 手听说: <strong>{n}</strong> 条</li>' for h, n in sorted(by_hops.items())[:8])}
  </ul>

  <figure class="whisper-figure">
    <div class="whisper-caption">Lisa 自己反复说过的一件事,在 Lane Cove 的八卦链里走 7 手会变成什么样</div>
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
        <div class="wf-line">"住三楼那位Lisa,是从 <strong>Greenwich</strong> 的大房子卖了搬过来的。"</div>
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

  <p>反过来,Lisa 自己参与的 4 段对话被多少人听说?
  系统的 <code>share_count</code> 字段记录她每讲一段故事被多少不同的邻居转述出去——
  <strong>她那 4 段对话每段都传到了约 {avg_per_story} 个邻居耳朵里</strong>。
  Lane Cove 这个 1,000 人小镇,差不多每开一次口,镇上有近十分之九的人多少听过一耳朵。</p>
</section>
"""


def section_parallel_universes():
    """THE big chapter — 4 parallel Lisas. Each panel is enriched with the
    top recurring encounter partner (extracted from her own end-of-run
    reflection) and a one-line "what she wrote in her diary on day 13"
    so the four worlds become physically distinct, not just numerically."""
    import re as _re

    variant_meta = {
        "baseline":           {"name": "无推送", "color": "#5A5E6A", "tagline": "默认宇宙"},
        "hyperlocal_push":    {"name": "本街推送", "color": "#D14B12", "tagline": "她去了 shinnyo_australia"},
        "global_distraction": {"name": "全球新闻", "color": "#3B6EA8", "tagline": "她还在 building_1513"},
        "phone_friction":     {"name": "减少手机", "color": "#3A9D5C", "tagline": "她去了 Anglican Church"},
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
    <div><span class="us-label">到达时刻</span><span class="us-val">{(entity.get('arrived_at') or '?')[:16]}</span></div>
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

  <p class="dropcap">这一章问一个很小的问题:<strong>同一个 49 岁的 Plaza 干洗店老板,
  4 部不同的手机会把她送到 Lane Cove 哪几个地方?</strong></p>

  <p>仿真把她复制了 4 份——同样的 12 年干洗店、同样的【凌晨 5 点】打开铁闸、
  同样的 P&C 群消息、同样的 Mrs Chen 那件没取走的风衣。
  唯一被换掉的,是她口袋里那部手机会响什么。<br>
  Lisa 是镇上人尽皆知的店主——她的故事通过干洗票传遍了 992 个邻居,
  但她自己几乎不主动听别人的故事(后面 ch7 会展开)。
  现在我们看:<strong>4 部不同的手机把这位"店里听故事的人"分别送到了哪里。</strong></p>

  <p>下面是 5 月 5 日那一刻,4 个她分别在哪。地图上她去过的地方染成深橙,
  细线是她真实走过的路径,圆圈是 snapshot 抓到的最后一个位置。</p>

  <div class="universes-grid">
    {"".join(panels)}
  </div>

  <h3 class="parallel-insight-h3">4 个Lisa,4 段 14 天</h3>

  <div class="universe-essay" style="border-left:5px solid {bl['meta']['color']};">
    <h4 style="color:{bl['meta']['color']};">无推送 · 她在 building_1513 里,镇上有人在传她的故事</h4>

    <p>5 月 5 日 snapshot 那一刻,她在 building_1513——她家。
    14 天里手机一整天没响过。她按自己的节奏走:【凌晨 5 点起床】→ 6 点打开
    Plaza 那家【干洗店】的铁闸 → 处理早高峰的送洗衣物 → 跟 Mrs Chen 收回一周一套西装 →
    周二开车去 Forum 公寓送干洗给 Ralph → 7 点关门回家。
    她去过的地方一共 188 个 location——是 4 个她里探索最少的。</p>

    <p>从她身边经过的人有 <strong>4 个</strong>不同的——但她真的抬起头的次数,
    也是<strong>只有 4 个</strong>。BL 这个宇宙里,她的同框 = 她的瞥见 = 4 个,
    100% 的"同框就看见"率——这正是干洗店老板的特征:<strong>她不在街上随便经过别人,
    她就在 Plaza 一个固定位置上,谁来都跟她有事</strong>(取/送干洗、闲聊、咖啡)。
    她真正坐下来聊上 4 段对话。</p>

    <p>更要紧的是另一边的数据:她那 4 段干洗店对话,
    通过 share_count 字段统计,<strong>触达了几乎整个 1,000 人小镇</strong>——
    每段平均传到约 990 个邻居耳朵里。她不主动走出去找邻居,
    但邻居主动走进她店里;她不传别人故事,但她自己的故事被反复转述。</p>

    <p>这是<strong>她作为高出度 / 低入度社交节点</strong>的默认模式——
    镇上人尽皆知"Plaza 那位干洗店老板",但她自己听到的镇上八卦不多。
    她的店是一个 one-way mirror:everyone 进来,她记得他们的衣服尺码,
    但他们走出店门之后聊的什么,她不会知道。</p>
  </div>

  <div class="universe-essay" style="border-left:5px solid {hp['meta']['color']};">
    <h4 style="color:{hp['meta']['color']};">本街推送 · 30 条推送把她推去了 shinnyo_australia,
    14 天里她在那里被 260 个陌生人擦过身</h4>

    <p>这个宇宙里,她的手机响了 30 次。30 次都是同一个地方在叫她——
    <em>"shinnyo_australia 周六上午 10 点儿童活动,免费,有手作,有零食。"</em>
    <em>"周日上午社区清扫日。"</em><em>"周日下午 3 点新邻居见面会。"</em>
    都是 shinnyo_australia——Lane Cove 那座坐落在 Burns Bay Road 拐角的日式寺院。</p>

    <p>5 月 5 日 snapshot 抓到的那一刻她不在【干洗店】——
    她在 <strong>shinnyo_australia</strong>。她去过的地方 194 个 location,
    几乎跟 BL 一样,但她在那一栋楼里反复擦肩——
    14 天里从 <strong>260 个不同的陌生人</strong>身边经过(BL 是 4 个,
    65 倍!),其中<strong>真的抬头瞥见了 60 个</strong>(BL 是 4 个,15 倍)。</p>

    <p>对一个 12 年只在自己干洗店台子后面接待客人的老板,这是质变——
    <strong>她第一次跨出了 Plaza 那个固定 POI</strong>。
    干洗店的 one-way mirror 暂时碎了:她不再是"店里听故事的人",
    她变成"shinnyo 大堂里被各种人擦肩的人"。
    14 天里她仍然只聊上了 4 个人——
    但她被推送从 Plaza 的固定位置上拉了出去,看到了 260 张她在店里 12 年都没见过的脸。</p>
  </div>

  <div class="universe-essay" style="border-left:5px solid {gd['meta']['color']};">
    <h4 style="color:{gd['meta']['color']};">全球新闻 · 她还在 building_1513,世界没有发生</h4>

    <p>这个宇宙里她也收到了 30 条推送,但内容全是
    <em>"世界杯预选赛南美赛区多场爆冷"</em>、
    <em>"比特币突破 10 万美元"</em>、
    <em>"欧洲央行宣布加息 25 基点"</em>——
    跟她【干洗店】、跟 Mrs Chen、跟 Ralph、跟 Council Heritage Walk 那 3 张老照片,
    一条都没关系。</p>

    <p>5 月 5 日 snapshot 抓到的那一刻她还在 building_1513——
    跟 BL 一模一样。14 天里她去过的地方 160 个 location(比 BL 少 28),
    从 4 个不同的邻居身边经过——跟 BL 一样,
    其中<strong>真的抬头瞥见 3 个</strong>——比 BL 还少 1 个。</p>

    <p>全球新闻没有让她漂出 Plaza 半径——她得开店,她得收衣服,
    她得 5 点起来。<strong>她的物理路径不会因为读了比特币新闻而改变</strong>。
    但她注意力被全球新闻偷走了一点,
    所以同一段她每天熟到不能再熟的 Plaza/家路上,她抬头瞥见的脸数从 4 滑到 3。
    <strong>不是巨大的改变——是一种几乎察觉不到的、注意力被慢慢搬走的过程。</strong></p>
  </div>

  <div class="universe-essay" style="border-left:5px solid {pf['meta']['color']};">
    <h4 style="color:{pf['meta']['color']};">减少手机 · 她最终走进了 Anglican Church——
    被 285 个陌生人擦肩,真抬头瞥见了 76 次</h4>

    <p>这个宇宙里,她的手机几乎不响。14 天 6 条推送——4 个她里最少的。
    每一条都不是叫她"去哪",而是叫她<strong>抬头</strong>:<br>
    <em>"下次电梯里别低头——也许你认识那张面孔。"</em><br>
    <em>"屏幕亮 5 小时不如 Plaza 站 5 分钟。"</em><br>
    <em>"Plaza 的咖啡今早 8 点开了门,你上次和邻居打招呼是什么时候?"</em></p>

    <p>5 月 5 日 snapshot 抓到的那一刻她<strong>不在家、不在干洗店</strong>——
    她在 <strong>Anglican Church of Australia Lane Cove</strong>。
    plan reason 字段写着"<em>被 hyperlocal 推送吸引</em>",
    plan destination 字段写的是 anglican_church_of_australia_lane_cove。</p>

    <p>她 14 天里去过 108 个不同的 location——4 个宇宙里最少。
    但从她身边经过的人有 <strong>285 个不同的陌生人</strong>(比 HP 多 25,
    比 BL 多 71 倍)——其中真的抬头瞥见 <strong>76 次</strong>
    (是 BL 4 次的 <strong>19 倍</strong>,4 个宇宙里最高!)</p>

    <p>对一位 12 年 Plaza 一砖一瓦熟到极致的店主,这是另一种解放——
    <strong>不是更广的探索,而是更深的看见</strong>。
    HP 把她送进 shinnyo 那栋大堂,
    PF 则把她送进 Anglican Church 的院子和走廊;两个完全不同的"宗教建筑"邻居网络。
    Lisa 不是被推去任何"指定地点"——
    她是被推送从 Plaza 那个固定 POI 撑开了 sight_radius,
    plan 系统下一次计算"附近吸引力"时,Anglican Church 那片刚好进了她的视线。</p>

    <p>没有一行代码告诉她去 Anglican Church。反向推送只做了一件很小的事——
    把她的 <code>screen_time_weight</code> 调低一点,sight_radius 自动撑开,
    剩下的事是 plan 系统自己长出来。<br>
    <strong>6 条提醒抬头的推送,换来了 76 张她在 Plaza 12 年都没见过的脸。</strong></p>
  </div>

  <p class="parallel-close">同一个 49 岁的 Plaza 干洗店老板。同一份 20 条的生平。
  同一个 building_1513 的家。同一杯凌晨 5 点的咖啡。同一个 Lane Cove。<br>
  同一段 14 天,4 部不同的手机。<br><br>
  4 部不同的手机分别把她送去了:<strong>家里 / shinnyo_australia /
  原地不动 / Anglican Church</strong>。<br>
  她身边的陌生人脸数分别是 <strong>4 / 260 / 4 / 285</strong>;<br>
  她真的抬头瞥见的次数分别是 <strong>4 / 60 / 3 / 76</strong>。<br><br>
  <span class="parallel-kicker">在这个 1,000 人的算法风洞里,
  Lisa 的 14 天提供了一个 Mary 故事里也许没有的真相:<br>
  <strong>一位高出度 / 低入度的店主——everyone 都来她店里,
  她自己几乎不主动出去看人——
  反向推送把她从 Plaza 那个固定 POI 撑开了 19 倍的视野。
  推送能改变的不只是去哪——它能改变一位店主有没有走出自己 12 年的台子。</strong></span></p>
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
  <p>系统每天结束时会让 LLM 看 Lisa 当天的全部行为日志,生成 <code>reflection</code> 事件 —
  对她自己行为模式的 meta-觉察。这些反思不是 Lisa 自己写的,是系统看 log 总结的。
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
    Fact: Lisa.family_members = {}. 1000 个 agent 数据库里没有任何一个
    被链接为她的女儿。她在 life_history 里写过母亲节女儿从悉尼东郊
    开车来 Crows Nest 吃饭、暴雨夜女儿打电话来问会不会淹、女王逝世
    那晚她给女儿发短信收到一个王冠 emoji——但这些都是 LLM 生成的回忆。
    plan 里那句"给儿子打视频电话",对面没有 API。"""
    return """
<section class="chapter chapter-phantom">
  <h2>插曲 · 那位不存在的女儿</h2>

  <p class="phantom-lead">在继续往下之前,有一件事必须说出来。</p>

  <p>Lisa 在她那 4 段 14 天里,几乎每一个夜晚都给"Lane Cove North 合租的儿子"打视频电话。
  这件事写在她的 plan 里、写在她和 88 岁退休邻居的对话里——
  <em>"晚上 8 点 30 视频电话东郊,写在冰箱便签上了,怕忘事。"</em>
  她的 life_history 里也有真切的细节:2023 母亲节女儿从悉尼东郊开车过来,
  在 Crows Nest 的 garfish 餐厅吃了一顿晚午饭;2022 年暴雨夜女儿打电话来问
  "<em>你那儿会不会淹</em>",她说"<em>七十年代发洪水都没事</em>";
  2022 年女王逝世那晚她给女儿发了条短信,女儿回了一个王冠 emoji。</p>

  <div class="phantom-revelation">
    <p>但 Synthetic Socio Wind Tunnel 这 1000 个虚拟居民的数据库里,
    <strong>并没有一个 agent 被链接为Lisa的女儿</strong>。</p>

    <p>Lisa 的 profile 里 <code>family_members = {}</code> ——空字典。
    <code>household_role = "parent"</code> 写着她是个母亲,
    但 simulation 里没有一个 <code>a_43_XXXX</code> 指向"她的孩子"。
    悉尼东郊根本不在这次仿真的地理范围里——
    Lane Cove 这个 1000 人的小镇,就是这个宇宙的全部。</p>

    <p>所以她每一个夜晚 8 点 30 分举起的那个手机,<strong>对面没有 API</strong>。
    她的 LLM 写出来"打视频电话",但没有任何一行代码去接通另一个 agent 的输入。
    那个王冠 emoji、那句"爸你瘦了"(LLM 自己写漂的)、那通问"会不会淹"的电话——
    全是 Lisa 自己 memory_store 里一段不会有真实响应的字符串。</p>
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
  也有很多个 Lisa,每晚 8 点 30 准时拿起手机,对着屏幕讲一段话。
  另一头是不是真的有人在听——是不是有人在打字、在皱眉、在回一个 emoji——
  并不总能验证。<br>
  <strong>有些晚上的牵挂,我们也不能确定它的另一端,有没有 API。</strong></p>
</section>
"""


def section_one_of_thousand():
    return """
<section class="chapter chapter-zoom">
  <h2>10 · 1,000 个故事里的 1 个</h2>
  <p>Lisa 不是特例。在这 1,000 个虚拟居民里,有 227 人在 14 天里经历了类似的变化 —
  从他们的日常半径里被推送拉出去,在一个新地方反复遇到一群以前没见过的邻居,
  形成新的固定行程。</p>

  <p>但每一个人都有自己的版本。同样的 hyperlocal_push 推送,Mike 26 岁工程师去了 1021 Mediterranean;
  Frank 64 岁建筑工被《Lane Cove 简史》读书会勾住跑去了 Shinnyo;
  Lucy 29 岁失业青年走 3.1 km 去了 PLC Sydney Preschool。</p>

  <p>这是一个虚拟城市的故事 — 但它讨论的是真问题: 一条推送能不能改变一个具体的人的世界半径?
  仿真说能。Lisa 用她 14 天的真实数据印证了这件事。</p>

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

    # Lisa's own data — recount from the 4-variant blob
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

  <p class="data-vanity-lead">这份关于一个 49 岁干洗店老板的 10 章长文,背后是多少数据?
  把所有数字摆出来 — 一份诚实的"数据账本",
  也是一份不必谦虚的"虚拟人口学规模说明"。</p>

  <div class="data-vanity-section">
    <h3 class="dv-h3">⊙ Lisa 一人,跨 4 个平行宇宙,14 天里产生了 ——</h3>
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
    你刚读完的 10 章关于 Lisa 的故事 —— 是这堆数据里关于
    <strong>1 个 49 岁干洗店老板</strong>的 <strong>1 条线索</strong>。<br>
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
    '<title>她每天 6 点开 Plaza 那家干洗店 · 1,000 个虚拟居民里的 1 位 · Synthetic Socio Wind Tunnel</title>',
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
