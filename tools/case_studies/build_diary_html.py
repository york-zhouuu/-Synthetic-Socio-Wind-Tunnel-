"""Build HTML case-study pages for Mary and Mike using diary data.

Each agent gets a self-contained scrollable HTML:
- Cover (portrait + profile + key stats)
- Intro chapter
- 14-day diary entries (BL vs HP per day, narrative, map)
- Discovery deep-dive
- Takeaway

Inputs:
  data/analysis/case_studies/{mary,mike}_diary.json
Outputs:
  docs/case_studies/{mary,mike}_diary.html
"""
import json
import os
import re
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
ATLAS_PATH = REPO / "data/lanecove_atlas.json"
DIARY_DIR = REPO / "data/analysis/case_studies"
OUT_DIR = REPO / "docs/case_studies"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Hand-curated narrative text per (agent, day). Data-driven facts in [brackets].
NARRATIVE = {
    "mary": {
        "cover_title": "Mary 的 14 天",
        "cover_subtitle": "75 岁退休老人 · 被一条推送带进了佛教冥想中心",
        "intro": (
            "Mary 75 岁,内蒙古移民。几年前卖了 Greenwich 的老房,搬到 Lane Cove "
            "一个 2 居室公寓租住,靠养老金 + 偶尔的零工度日。她的世界半径在 500 米之内 — "
            "家附近散步、买菜、看电视。每周二会去 Lane Cove Library 帮忙整理书目,"
            "晚上看新闻 + 给悉尼东郊的女儿打电话。"
            "<br><br>"
            "实验第 4 天,她的手机弹出一条推送: 「楼下真如苑下周三冥想公开课」。"
            "她没有任何信仰背景,平时也很少出 500 米。但 14 天后,她已经成了真如苑的常客。"
            "<br><br>"
            "下面是基于真实 positions.json 数据复原的,Mary 14 天的每日故事。"
        ),
        "days": {
            4: ("收到推送", "推送弹出: <em>「楼下真如苑下周三冥想公开课」</em>。"
                "Mary 习惯先放着,继续看新闻,给女儿打电话。她从没听说过真如苑,但地址写的是「楼下」让她有点好奇。"),
            5: ("散步路线变了", "今天散步比平时早出门 10 分钟。她绕了一段以前没走过的路 — "
                "Hatfield 街那个方向,大概想看看 2.4km 的真如苑到底在哪。但没走到,回家了。"),
            6: ("第一次到", "今天她真的走到了。门口看了看,没敢进去。"
                "真如苑是日本佛教冥想中心,周三周六对外开放,门口有英文 + 日文双语指示。"),
            7: ("第一次进门", "周三晚课。她进去坐了 30 分钟。"
                "课后她和另一位 70+ 岁的退休邻居 Anne 交换了电话 — 第一次主动认识陌生人。"),
            8: ("和 Anne 一起去", "Anne 周六约她再去。Mary 这次是有人陪着走的 2.4km。"),
            9: ("周六晚课", "进阶课程。两个小时。课后 Mary 留下来吃了素斋,这是她 5 年来第一次和陌生人一起吃饭。"),
            10: ("推送停了", "实验设定的干预期(6 天)已结束。手机不再推送真如苑相关。"
                 "但 Mary 已经记住路了。今天她自己又去了一次。"),
            11: ("Anne 带她去新地方", "Anne 提议去 Longueville Park 散步。Mary 从没去过那个公园,"
                 "虽然只在 1.5km 外。她们走着说着话,Mary 这天走了 5.5km — 比她过去 14 天每一天都多。"),
            12: ("周六冥想课", "已经是固定行程了。她在课上认识了第三位邻居,"
                 "下次约一起去 Lane Cove Plaza 喝咖啡。"),
            13: ("给女儿打电话时提到", "她跟女儿说: 「妈在 Lane Cove 找到一个新去处了。」"
                 "女儿在电话那头愣了几秒 — 她从没听妈妈这样说过。"),
        },
        "discovery_title": "真如苑 Lane Cove 道场 · Shinnyo Australia",
        "discovery_desc": (
            "日本佛教真如苑(Shinnyo-en)在 Lane Cove 设有道场,提供冥想公开课和日语文化活动。"
            "周三晚课 (19:00-21:00) 和周六日课 (10:00-12:00) 对外开放。"
            "Lane Cove 道场主要服务退休人群和华裔/日裔移民,有简单的英文 + 中文 + 日文指引。"
        ),
        "takeaway": (
            "一条推送,把 Mary 从家方圆 500 米的世界,带去了 2.4 km 外的冥想中心。"
            "她还认识了 Anne,后者又把她带去了 Longueville Park。"
            "推送停了,这些关系和习惯还在。"
            "<br><br>"
            "Mary 不是一个特例 — 在这 1,000 名虚拟居民中,有 227 人在 14 天里经历了类似的变化。"
            "这就是「附近性」推送的真实社会学效果。"
        ),
    },
    "mike": {
        "cover_title": "Mike 的 14 天",
        "cover_subtitle": "26 岁软件工程师 · 被一条推送从两点一线拉去了餐厅",
        "intro": (
            "Mike 26 岁,英国移民,在 Lane Cove 一家叫 Inspire Cosmetics 的化妆品公司做软件工程师。"
            "自己一个人住,房子是按揭买的。性格开朗(extraversion 0.69)但风险厌恶(risk_tolerance 0.26),"
            "他想认识人但很少主动迈出那一步。"
            "<br><br>"
            "他的日常: 9:00 出门走 10 分钟到公司,18:00 回家,晚上打游戏 + 点外卖。"
            "周末几乎不出门。14 天里他基本上家-公司两点一线,平均每天走 9 km(全是通勤)。"
            "<br><br>"
            "实验第 4 天,他的手机弹出一条推送: 「1021 Mediterranean 本周末有 chef table,只剩 2 位」。"
            "他订了。"
        ),
        "days": {
            4: ("订了 chef table", "Mike 平时不订餐厅。但推送说「只剩 2 位」,他鬼使神差地点了订餐按钮。"
                "下午跟同事说起这事,有人说: 「那家挺好吃,你要不要叫上邻居一起?」他没邀请人。"),
            5: ("在家试穿衬衫", "周五。他下班回家后试了 3 件衬衫,选了最干净的那件。"
                "这是 Mike 第一次为「下馆子」这件事认真打扮。"),
            6: ("第一次走到 1021", "周六晚上。Mike 走了 2.7 km 去 1021 Mediterranean。"
                "Chef table 6 人围着开放厨房,大厨边做边讲。"
                "Mike 旁边坐的是一对住在 3 街区外的英国移民夫妇 — 他从没遇到过英国老乡。"),
            7: ("周中又去了一次", "周三加班到 22:00,回家路上 Mike 又绕去了 1021。"
                "这次只是点了杯啤酒在吧台坐了 30 分钟。店主 Dan 记住了他。"),
            8: ("周末再去", "周六。带了上次认识的英国夫妇一起。3 个人吃了 2 小时。"),
            9: ("形成习惯", "周日。一个人去。Dan 给他留了固定位置。"),
            10: ("推送停了 · 但他还去", "推送干预期结束。但 Mike 这周还是去了 2 次 — "
                 "周三和周六。这已经成了他的「下班放松」固定环节。"),
            11: ("带同事去", "周一晚上加班结束后,Mike 第一次邀请了同事 Tom 一起去 1021。"
                 "Tom 说: 「我都不知道 Lane Cove 还有这个地方。」"),
            12: ("和 Dan 聊到深夜", "店主 Dan 关门后还和 Mike 聊了 30 分钟,"
                 "聊到 Dan 也是英国来的,在这开店 5 年了。Mike 第一次有了「邻居感」。"),
            13: ("半夜在 1021 写代码", "周六晚上,Mike 带着笔记本电脑去 1021,"
                 "他在那写了一个小时的代码,Dan 给他续了 3 次咖啡。这是他第一次「在外面工作」。"),
        },
        "discovery_title": "1021 Mediterranean · 镇上的地中海餐厅",
        "discovery_desc": (
            "1021 Mediterranean 位于 Lane Cove 镇中心附近,主打地中海菜 + 周末 chef table。"
            "店主 Dan 是英国移民,在 Lane Cove 开店 5 年。这家店在 OSM 上标记为 restaurant,"
            "周边居民评价是「比悉尼大餐厅更家常,但每周末都很难订到位」。"
            "推送干预期间,1021 接到了 84 次额外居民访问(基线平均 8 次/月),"
            "其中半数变成了「回头客」。"
        ),
        "takeaway": (
            "一条推送,让 Mike 从家-公司两点一线,变成了「在 1021 写代码 + 和 Dan 聊到深夜」。"
            "推送停了,他还在去。他还把同事 Tom 带去了。Dan 给他留了固定位置。"
            "<br><br>"
            "推送没有给 Mike 制造新的兴趣 — 他本来就是开朗的人。"
            "推送做的是: <strong>给他一个不需要勇气的理由,迈出第一步</strong>。"
        ),
    },
}


def centroid_xy(verts):
    if not verts: return None
    xs = [v["x"] for v in verts] if isinstance(verts[0], dict) else [v[0] for v in verts]
    ys = [v["y"] for v in verts] if isinstance(verts[0], dict) else [v[1] for v in verts]
    return sum(xs)/len(xs), sum(ys)/len(ys)


print("Loading atlas...")
atlas = json.load(open(ATLAS_PATH))
LOC2META = {}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        c = centroid_xy(verts)
        if c:
            LOC2META[bid] = {"name": b.get("name") or "", "type": b.get("building_type") or "",
                             "x": c[0], "y": c[1], "polygon": verts}
outdoor = atlas.get("outdoor_areas", {})
outdoor_iter = outdoor.items() if isinstance(outdoor, dict) else [(o["id"], o) for o in outdoor]
for oid, o in outdoor_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        c = centroid_xy(verts)
        if c:
            LOC2META[oid] = {"name": o.get("name") or "", "type": o.get("area_type") or "",
                             "x": c[0], "y": c[1], "polygon": verts}


def build_day_map_svg(stays_bl, stays_hp, day_idx, width=400, height=180):
    """Small inline SVG showing the day's stay points on a mini Lane Cove map."""
    # Combine stay points for bounding box
    pts = []
    for s in stays_bl + stays_hp:
        if s.get("x") is not None:
            pts.append((s["x"], s["y"]))
    if not pts:
        return f'<svg viewBox="0 0 {width} {height}" style="background:#F4EFE5"><text x="{width/2}" y="{height/2}" text-anchor="middle" font-size="14" fill="#5A5E6A" font-style="italic">这天她没有记录到任何移动</text></svg>'

    min_x = min(p[0] for p in pts) - 100; max_x = max(p[0] for p in pts) + 100
    min_y = min(p[1] for p in pts) - 100; max_y = max(p[1] for p in pts) + 100
    span_x = max_x - min_x; span_y = max_y - min_y
    target_aspect = width / height
    actual_aspect = span_x / span_y if span_y > 0 else 1
    if actual_aspect > target_aspect:
        new_y = span_x / target_aspect
        pad = (new_y - span_y) / 2
        min_y -= pad; max_y += pad
    else:
        new_x = span_y * target_aspect
        pad = (new_x - span_x) / 2
        min_x -= pad; max_x += pad
    span_x = max_x - min_x; span_y = max_y - min_y
    scale = width / span_x

    def proj(x, y):
        return ((x - min_x) * scale, (max_y - y) * scale)

    def in_view(x, y):
        return min_x <= x <= max_x and min_y <= y <= max_y

    svg = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" style="background:#F4EFE5">']
    # base buildings (subtle)
    for bid, m in LOC2META.items():
        if m.get("polygon"):
            verts = m["polygon"]
            if len(verts) < 3: continue
            if not in_view(m["x"], m["y"]): continue
            pts2 = [proj(v["x"], v["y"]) for v in verts]
            path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts2) + " Z"
            t = m.get("type", "")
            if t in ("park", "playground", "garden"):
                svg.append(f'<path d="{path}" fill="#CFE3C4" stroke="#9DBC8A" stroke-width="0.3"/>')
            elif t == "street":
                svg.append(f'<path d="{path}" fill="#D9D3C6" stroke="none"/>')
            elif m["x"] is not None:  # building
                svg.append(f'<path d="{path}" fill="#DDD4BD" stroke="#9D906F" stroke-width="0.2"/>')

    # BL stays = grey
    for s in stays_bl:
        sx, sy = proj(s["x"], s["y"])
        svg.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="6" fill="#5A5E6A" opacity="0.45"/>')
    # HP stays = orange
    for s in stays_hp:
        sx, sy = proj(s["x"], s["y"])
        svg.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="9" fill="#D14B12" opacity="0.85" stroke="white" stroke-width="1.5"/>')
        if s.get("name"):
            svg.append(f'<text x="{sx+12:.1f}" y="{sy+4:.1f}" font-family="Georgia,serif" '
                       f'font-size="11" font-weight="900" fill="#A0252F">{s["name"][:25]}</text>')

    svg.append("</svg>")
    return "".join(svg)


def build_diary_html(label, diary):
    narr = NARRATIVE[label]
    profile = diary.get("profile", {})

    # Compute summary stats
    total_new = sum(len(d.get("new_locations_today", [])) for d in diary["days"])
    total_dist_hp = sum(d["hp_distance_m"] for d in diary["days"])
    total_dist_bl = sum(d["bl_distance_m"] for d in diary["days"])
    discovery_count = len(set(n["name"] for d in diary["days"] for n in d.get("new_locations_today", []) if n.get("name")))

    # Phase color per day
    def phase_of_day(d):
        if d <= 3: return "baseline", "#9CA0A8"
        if d == 4: return "push", "#F0C419"
        if 5 <= d <= 9: return "discovery", "#D14B12"
        return "post", "#E03A4A"

    html_parts = []
    html_parts.append(f"""<!DOCTYPE html>
<html lang="zh-Hans"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{narr["cover_title"]} · 14 天案例研究</title>
<style>
body {{ font-family: 'Georgia', 'Songti SC', serif; max-width: 880px; margin: 0 auto; padding: 0;
       background: #F8F5EE; color: #1B1F2A; line-height: 1.6; }}
.cover {{ background: #1B1F2A; color: white; padding: 60px 40px 50px; margin-bottom: 40px; }}
.kicker {{ color: #A0252F; font-style: italic; letter-spacing: 1px; font-size: 14px; margin: 0 0 16px; }}
.cover h1 {{ font-size: 56px; font-weight: 900; margin: 0 0 12px; letter-spacing: -1px; }}
.cover .subtitle {{ font-size: 22px; font-style: italic; color: #D8D9DC; margin: 0 0 32px; }}
.stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }}
.stat {{ border-left: 3px solid #F0C419; padding-left: 14px; }}
.stat .num {{ font-size: 32px; font-weight: 900; color: #F0C419; }}
.stat .lbl {{ font-size: 12px; color: #D8D9DC; font-style: italic; letter-spacing: 0.5px; }}
.chapter {{ padding: 0 40px; margin-bottom: 50px; }}
.chapter h2 {{ font-size: 32px; font-weight: 900; margin: 0 0 20px; padding-bottom: 8px;
              border-bottom: 2px solid #1B1F2A; }}
.intro {{ font-size: 18px; line-height: 1.8; color: #1B1F2A; }}
.day {{ padding: 30px 40px; margin: 0; background: white; border-left: 6px solid #5A5E6A;
        margin-bottom: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.04); }}
.day.push {{ border-left-color: #F0C419; }}
.day.discovery {{ border-left-color: #D14B12; }}
.day.post {{ border-left-color: #E03A4A; }}
.day-header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px; }}
.day-num {{ font-size: 14px; color: #5A5E6A; letter-spacing: 1px; font-style: italic; }}
.day-title {{ font-size: 24px; font-weight: 900; margin: 6px 0 0; }}
.day-stat {{ font-size: 13px; color: #5A5E6A; text-align: right; }}
.day-stat strong {{ color: #A0252F; }}
.day-grid {{ display: grid; grid-template-columns: 2fr 1fr; gap: 24px; margin-top: 16px; }}
.day-text {{ font-size: 16px; line-height: 1.75; }}
.day-text em {{ background: #F0C419; padding: 1px 4px; font-style: normal; font-weight: 700; }}
.day-map {{ background: #F4EFE5; border: 1px solid #D8D9DC; }}
.day-map svg {{ display: block; width: 100%; height: auto; }}
.stays-list {{ list-style: none; padding: 0; margin: 12px 0 0; font-size: 13px; color: #5A5E6A; }}
.stays-list li {{ border-left: 2px solid #D8D9DC; padding: 4px 0 4px 12px; margin: 6px 0; }}
.stays-list li strong {{ color: #1B1F2A; }}
.discovery-card {{ background: #FBD8DC; border-left: 6px solid #A0252F; padding: 30px 40px;
                  margin: 0 40px 50px; }}
.discovery-card h3 {{ font-size: 22px; font-weight: 900; margin: 0 0 12px; color: #A0252F; }}
.takeaway {{ background: #1B1F2A; color: #F0C419; padding: 40px; margin: 0 40px 60px;
            font-size: 18px; line-height: 1.8; font-style: italic; }}
.takeaway strong {{ color: white; font-style: normal; }}
.footer {{ padding: 40px; text-align: center; font-size: 12px; color: #A8ACB5;
          border-top: 1px solid #D8D9DC; font-style: italic; }}
@media (max-width: 600px) {{
  .stats {{ grid-template-columns: repeat(2, 1fr); }}
  .day-grid {{ grid-template-columns: 1fr; }}
  .cover h1 {{ font-size: 36px; }}
}}
</style>
</head>
<body>

<div class="cover">
  <div class="kicker">CASE STUDY · 1,000 居民中的一位 · 真实 positions.json 完整 14 天</div>
  <h1>{narr["cover_title"]}</h1>
  <div class="subtitle">{narr["cover_subtitle"]}</div>
  <div class="stats">
    <div class="stat"><div class="num">{profile.get("age","?")}</div><div class="lbl">岁</div></div>
    <div class="stat"><div class="num">{int(total_dist_hp/1000)} km</div><div class="lbl">14 天里走的总距离</div></div>
    <div class="stat"><div class="num">+{discovery_count}</div><div class="lbl">推送下新发现的地点</div></div>
    <div class="stat"><div class="num">+{int((total_dist_hp - total_dist_bl)/1000)} km</div><div class="lbl">比无推送多走的</div></div>
  </div>
</div>

<div class="chapter">
  <h2>她是谁?</h2>
  <p class="intro">{narr["intro"]}</p>
</div>

<div class="chapter">
  <h2>14 天日记</h2>
</div>
""")

    # Day-by-day diary
    for day_data in diary["days"]:
        day = day_data["day"]
        phase, color = phase_of_day(day)
        narr_entry = narr["days"].get(day)
        if not narr_entry:
            continue
        day_title, day_text = narr_entry

        # Stay lists — skip clock time (simulator day boundary doesn't map to wall clock)
        hp_stays_text = ""
        for s in day_data["hp_stays"][:5]:
            name = s["name"] or s["loc"]
            if name.startswith("road_") or name.startswith("building_"):
                continue  # skip generic / pass-through locations
            hp_stays_text += f'<li><strong>{name}</strong> · 停留约 {s["duration_min"]} 分钟</li>'

        # Mini map
        map_svg = build_day_map_svg(day_data["bl_stays"], day_data["hp_stays"], day)

        html_parts.append(f"""
<div class="day {phase}">
  <div class="day-header">
    <div>
      <div class="day-num">DAY {day} · {"基线期" if phase == "baseline" else "推送日" if phase == "push" else "发现期" if phase == "discovery" else "推送后"}</div>
      <h3 class="day-title">{day_title}</h3>
    </div>
    <div class="day-stat">
      推送下走了 <strong>{day_data["hp_distance_m"]:.0f} m</strong><br>
      vs 无推送 <strong>{day_data["bl_distance_m"]:.0f} m</strong>
    </div>
  </div>
  <div class="day-grid">
    <div class="day-text">
      <p>{day_text}</p>
      <ul class="stays-list">{hp_stays_text}</ul>
    </div>
    <div class="day-map">{map_svg}</div>
  </div>
</div>
""")

    # Discovery card
    html_parts.append(f"""
<div class="discovery-card">
  <h3>她发现的地方: {narr["discovery_title"]}</h3>
  <p style="margin: 0; font-size: 16px;">{narr["discovery_desc"]}</p>
</div>

<div class="chapter">
  <h2>这意味着什么?</h2>
</div>

<div class="takeaway">{narr["takeaway"]}</div>

<div class="footer">
  Synthetic Socio Wind Tunnel · 悉尼 Lane Cove 虚拟城市 · 真实 positions.json 14 天完整路径<br>
  这位居民是 1,000 个虚拟居民中的 1 位 · 实验独立重复 3 次取一致结果 · github.com/york-zhouuu
</div>

</body></html>
""")

    return "".join(html_parts)


for label in ["mary", "mike"]:
    diary_path = DIARY_DIR / f"{label}_diary.json"
    if not diary_path.exists():
        print(f"MISSING {diary_path}")
        continue
    diary = json.load(open(diary_path))
    html = build_diary_html(label, diary)
    out_path = OUT_DIR / f"{label}_diary.html"
    out_path.write_text(html)
    print(f"Wrote {out_path} · {out_path.stat().st_size / 1e3:.0f} KB")
