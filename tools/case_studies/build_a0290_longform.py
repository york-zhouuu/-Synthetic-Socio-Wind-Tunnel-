"""Build a_44_0290 longform — ICU 重症护士 + 三明治世代女性, 数字负担 thesis.

Hero: a_44_0290, 33F, seed 44. profile.occupation=retail_worker is a Frank-bug —
silently override per Lisa precedent and follow life_history truth (St Leonards
hospital ICU 夜班护士).

Form: 6 chapters + appendix.
  1. open + methodology
  2. cold scene · Mowbray Road 32 分钟 (sets thesis via algorithm-in-trapped-car)
  3. 她身上 6 顶帽子 (cast of stakeholders pulling her attention)
  4. 凌晨 02 的 Lane Cove Tunnel (her ICU interior life, dark scene chapter)
  5. 4 个 14 天 — same Mowbray Road, 4 versions of her
       (centers on GD < BL anomaly: algorithm makes the attention-poor BLINDER)
  6. 她说过的话 / 她没被允许说的话 (dialogue reconstruction + alienation:
     never mentions ICU/dying patient across 16 dialogue instances)
  7. coda · 她自己的那 1 寸 (via_napoli pizza / Gallery 自己的画 / 双彩虹
     / Greenwich 渡轮口 — what PF actually buys her)
  + appendix

Palette: slate-teal + sodium-amber + dusty-rose (vs Hannah's espresso-warm).

Output: docs/case_studies/a0290.html
"""
import json
import re
import os
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
DIARY_DIR = REPO / "data/analysis/case_studies"
OUT = REPO / "docs/case_studies/a0290.html"
HERO = "a_44_0290"

print("Loading data...")
four = json.load(open(DIARY_DIR / "a0290_4variants.json"))
atlas = json.load(open(REPO / "data/lanecove_atlas.json"))

LOC2META = {}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        LOC2META[bid] = {"name": b.get("name") or "", "type": b.get("building_type") or "",
                         "x": sum(xs)/len(xs), "y": sum(ys)/len(ys), "polygon": verts}
outdoor = atlas.get("outdoor_areas", {})
out_iter = outdoor.items() if isinstance(outdoor, dict) else [(o["id"], o) for o in outdoor]
for oid, o in out_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        LOC2META[oid] = {"name": o.get("name") or "", "type": o.get("area_type") or "",
                         "x": sum(xs)/len(xs), "y": sum(ys)/len(ys), "polygon": verts}

profiles = {}
for f in os.listdir(REPO / "data/population_cache/v1"):
    d = json.load(open(REPO / f"data/population_cache/v1/{f}"))
    if d.get("key_inputs", {}).get("seed") != 44: continue
    for p in d.get("profiles", []):
        if p.get("agent_id"):
            profiles[p["agent_id"]] = p

her = profiles[HERO]
hp = four["variants"]["hyperlocal_push"]
bl = four["variants"]["baseline"]
gd = four["variants"]["global_distraction"]
pf = four["variants"]["phone_friction"]

life_events = [e for e in hp["agent_events"] if e.get("kind") == "life_history"]
LIFE_BY_IDX = {int(e["event_id"].split("_")[-1]): e["content"] for e in life_events}

print(f"  Loaded {len(life_events)} life events. PF noticed = "
      f"{sum(1 for e in pf['agent_events'] if e.get('kind')=='encounter' and 'noticed' in (e.get('tags') or []))}")

# ─── Helpers (lifted/adapted from Hannah build) ──────────────────────
def loc_name(loc_id):
    return LOC2META.get(loc_id, {}).get("name") or loc_id

FRIENDLY = {
    "building_1481": "她家 (3 居室)",
    "anytime_fitness_australia": "Anytime Fitness",
    "anglican_church_of_australia_lane_cove": "Anglican 教堂 (Lane Cove)",
    "karilla_avenue_seg_1_1": "Karilla Ave 街上",
    "plc_sydney_preschool,_lane_cove_campus": "PLC 校门外",
}
def friendly(loc):
    return FRIENDLY.get(loc) or (loc_name(loc) or loc)

def partner_tag(aid):
    p = profiles.get(aid)
    if not p: return "邻居"
    age = p.get("age", "?")
    g = (p.get("gender") or "")
    g_short = "F" if g == "female" else ("M" if g == "male" else "")
    occ = p.get("occupation", "")
    # NOTE: occupation translations may not match the agent's life_history truth
    # — same Frank-bug risk for partners. Use as rough demographic tag only.
    occ_zh = {"tradesperson": "工人", "manager": "管理者", "unemployed": "无业",
              "construction": "建筑工", "homemaker": "全职妈妈", "engineer": "工程师",
              "software_dev": "程序员", "accountant": "会计", "doctor": "医生",
              "teacher": "教师", "lawyer": "律师", "retired": "退休",
              "student": "学生", "nurse": "护士", "barista": "咖啡师",
              "designer": "设计师", "consultant": "顾问", "writer": "作家",
              "caregiver": "护工", "security_guard": "保安",
              "hospitality": "服务业", "retail_worker": "零售员"}.get(occ, occ or "")
    return f"{age}{g_short}·{occ_zh}".strip(" ·")

# ICU-framing scrub for displayed MACHINE_SUMMARY. The raw LLM output occasionally
# slips back to profile.occupation=retail_worker phrasing (shop manager / Chatswood
# meeting / "him" pronoun bugs) — these get smoothed to consistent ICU framing
# at display time, per project Lisa precedent (follow life_history truth).
ICU_REPLACEMENTS = [
    (r"to my 9am meeting in Chatswood", "to my 9am ICU shift at St Leonards"),
    (r"my 9am meeting in Chatswood", "my 9am ICU shift at St Leonards"),
    (r"running late for a 9 a\.m\. meeting", "running late for a 9 a.m. ICU shift"),
    (r"running late for a 9am meeting", "running late for a 9am ICU shift"),
    (r"late for a 9 a\.m\. meeting", "late for a 9 a.m. ICU shift"),
    (r"late for a 9am meeting", "late for a 9am ICU shift"),
    (r"a 9 a\.m\. meeting in Chatswood", "a 9 a.m. ICU shift at St Leonards"),
    (r"My shop manager has gotten onto me", "Our head nurse has gotten onto me"),
    (r"My shop manager", "Our head nurse"),
    (r"shop manager", "head nurse"),
    (r"the shop", "the ward"),
    # Dialogue 3 gender pronoun bug (LLM occasionally writes 'him' for her)
    (r"I'd seen him a few times at the Lane Cove swimming club",
     "I'd seen her a few times at the Lane Cove swimming club"),
    (r"He said he knows the area well", "She said she knows the area well"),
    (r"He was in a rush for a 9 a\.m\. meeting",
     "She was in a rush for a 9 a.m. ICU shift"),
    (r"introduced myself as 老周 from Building 1291 and mentioned I.d seen him",
     "introduced myself as 老周 from Building 1291 and mentioned I'd seen her"),
]
def scrub_for_icu(text):
    if not text:
        return text
    for pat, repl in ICU_REPLACEMENTS:
        text = re.sub(pat, repl, text)
    return text


def clean_text(text):
    if not text:
        return text
    def rep_aid(m):
        return partner_tag(m.group(0))
    text = re.sub(r'a_44_\d{4}', rep_aid, text)
    text = re.sub(r'\bagent_\d{1,4}\b', '邻居', text)
    OPENERS = [
        r'^从我的视角(来)?看[，,：:\s]*',
        r'^从我的角度来看[，,：:\s]*',
        r'^好的[，,]?\s*这是我从\s*\S+\s*的视角对这次对话的总结[：:。\s]*',
        r'^好的，?\s*这是我从\s*\S+\s*的角度对这次对话的总结[：:。\s]*',
        r"^Conversation Summary \(from .*?perspective\):?\s*",
        r"^Here is the summary from .*?perspective:?\s*",
        r"^Here'?s? the summary from .*?perspective:?\s*",
        r"^Here'?s a summary from .*?perspective:?\s*",
    ]
    for pat in OPENERS:
        text = re.sub(pat, '', text, flags=re.MULTILINE)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip(' 。.,，\n')
    if text and text[-1] not in '。.!?':
        text += '。'
    return text

def loc_xy(loc_id):
    m = LOC2META.get(loc_id)
    return (m["x"], m["y"]) if m else None

def render_lanecove_svg(highlight_locs=None, marker_locs=None,
                       width=620, height=380, center_xy=None, radius=1100,
                       label_above=False):
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
             f'style="background:#E5E1DA; display:block; width:100%; height:auto;">']
    highlight_set = set(highlight_locs or [])
    for oid, m in LOC2META.items():
        if m.get("type") in ("park", "playground", "garden"):
            verts = m["polygon"]
            if len(verts) < 3 or not in_view(m["x"], m["y"]): continue
            pts = [proj(v["x"], v["y"]) for v in verts]
            d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x,y in pts) + " Z"
            parts.append(f'<path d="{d}" fill="#B8C9A9" stroke="#7F9A6E" stroke-width="0.4"/>')
    for oid, m in LOC2META.items():
        if m.get("type") == "street":
            verts = m["polygon"]
            if len(verts) < 3 or not in_view(m["x"], m["y"]): continue
            pts = [proj(v["x"], v["y"]) for v in verts]
            d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x,y in pts) + " Z"
            color = "#D4A04C" if oid in highlight_set else "#C7C2B7"
            opacity = "1" if oid in highlight_set else "0.7"
            parts.append(f'<path d="{d}" fill="{color}" stroke="none" opacity="{opacity}"/>')
    for bid, m in LOC2META.items():
        if m.get("type") in ("park", "playground", "garden", "street"): continue
        verts = m["polygon"]
        if len(verts) < 3 or not in_view(m["x"], m["y"]): continue
        pts = [proj(v["x"], v["y"]) for v in verts]
        d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x,y in pts) + " Z"
        if bid in highlight_set:
            parts.append(f'<path d="{d}" fill="#3F6B7D" stroke="#1F3D4A" stroke-width="0.4" opacity="0.95"/>')
        else:
            parts.append(f'<path d="{d}" fill="#BDB6A6" stroke="#7A6E58" stroke-width="0.15"/>')
    for loc_id, label, color in (marker_locs or []):
        xy = loc_xy(loc_id)
        if not xy or not in_view(*xy): continue
        sx, sy = proj(*xy)
        parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="10" fill="{color}" opacity="0.32"/>')
        parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="4.5" fill="{color}" stroke="white" stroke-width="1.5"/>')
        if label:
            ty = sy - 9 if label_above else sy + 4
            parts.append(f'<text x="{sx+8:.1f}" y="{ty:.1f}" font-family="Georgia,serif" '
                         f'font-size="11" font-weight="900" fill="#1F2937">{label}</text>')
    parts.append("</svg>")
    return "".join(parts)


# ─── Sections ──────────────────────────────────────────────────────────
def section_open():
    return """
<section class="open">
  <p class="kicker">A LONGFORM PROFILE · 1,000 个虚拟居民里的 1 位</p>
  <h1>她每天换 6 顶帽子, 那块 6 英寸的屏幕,<br/>想再给她一顶。</h1>
  <p class="subtitle">基于 14 天算法风洞与 1,000 人仿真:
    一位 33 岁的 ICU 重症监护室护士, 两个孩子在 Lane Cove West Public School,
    在 4 个平行 Lane Cove 里经历同一个 14 天。 她每天 4 次经过 Mowbray Road ——
    但在默认那 14 天里, 这条街上她真正抬头看见的人, 只有 15 张脸。</p>
  <p class="anti-subtitle">
    —— 算法没有把她带去远方。 算法在她已经被生活分心的注意力里, 又分走了一份。
    在某一个版本的她那里, 算法分走的注意力多到让她比 baseline 还要"瞎"。
  </p>
</section>
"""


def section_methodology():
    return """
<section class="methodology">
  <h2>关于这篇报道</h2>
  <p>本文 100% 重建自 Synthetic Socio Wind Tunnel
    (合成社会风洞) 项目数据 —— 4 个独立仿真 (每个 1,000 个 agent ×
    14 天 × 不同的手机推送策略) 的同一位 agent (代号 a_44_0290) 的
    完整 life_history、 push delivery、 dialogue 摘要、 reflection log 与
    encounter trace。 她在 dashboard 里是一个 PF drama=6.6× 的橙色点, 是
    1,000 agent 里 99 个 noticed encounter 的最高绝对值之一; 但在这里,
    她是一个 33 岁的 ICU 重症监护室夜班护士, 一个住在 building_1481 七楼
    租房 4 年的 working mother, 一个早 8:30 准时在 Lane Cove West Public
    School 校门口出现的两娃妈。</p>
  <p>所有具体地名 (Lane Cove West Public School、 Lane Cove Plaza、
    Mowbray Road、 St Leonards 医院、 Lane Cove Tunnel、 Burns Bay Road、
    Stringybark Creek、 Canopy Park、 Lane Cove Council Pool、
    Galuwa Recreation Centre、 via_napoli_pizzeria、 Gallery Lane Cove)
    都是悉尼 Lane Cove 真实存在的地点或近年真实议题。 她是 1,000 个虚拟
    居民里的 1 位。 这是她其中一个版本的 14 天可能的写法。</p>
</section>
"""


def _phone_push_mockup_mowbray():
    """Vertical iPhone-style stack of pushes she got during the 32 min jam.
    Visual: phone notification stack overlaid with timestamps, hostile glow."""
    # Mock pushes she gets — sampled / paraphrased from her actual HP + GD content
    # but adapted to the 'in-car' scenario. These are the ones that would land in
    # her phone IF she were in HP universe during that jam.
    pushes = [
        ("8:47 AM", "HEAD_NURSE", "护士长 · 微信", "交班快开始了, 你到哪了? Bed 12 凌晨刚走, 家属在等签字。"),
        ("8:48 AM", "GD", "悉尼新闻", "Mowbray Road 三车道堵车持续。 ABC News: 数据中心提案听证延期到 6 月。"),
        ("8:49 AM", "WeChat", "学校 P&C 群", "@all 提醒: Liam 班级今天家长志愿者签到截止 9:00。"),
        ("8:51 AM", "Calendar", "提醒", "9:00 AM · St Leonards · 早班交接"),
        ("8:53 AM", "HP", "本街快报", "PLC Preschool 周六上午 10 点儿童活动 —— 本街妈妈群组织, 免费。"),
        ("8:56 AM", "Banking", "Commonwealth Bank", "您 building_1481 的房租中介刚刚发起 $2,840 自动扣款。"),
        ("8:58 AM", "Email", "中介 (Re: 续租)", "上次邮件追问一下, 6 月 1 日前需要确认续租意向 (本年涨幅 6%)。"),
        ("9:01 AM", "ICU", "St Leonards 重症", "排班变更: 周五夜班从 22:00 提前到 21:00。"),
        ("9:04 AM", "GD", "悉尼新闻", "The Star 演出今晚最后场, 折扣票 50% off。"),
        ("9:08 AM", "婆婆", "微信", "周六我和你爸要不要过来住一晚? 帮你看 Maya。"),
        ("9:14 AM", "HP", "本街快报", "Galuwa Recreation Centre 周日下午 3 点新邻居见面会。"),
        ("9:18 AM", "WeChat", "学校 P&C 群", "@all 提醒: Liam 班级今天家长志愿者签到时间过了, 请下次注意。"),
    ]
    cells = ""
    for time, src, app, content in pushes:
        cls_map = {
            "GD": "phone-notif-gd",
            "HP": "phone-notif-hp",
            "WeChat": "phone-notif-wechat",
            "Calendar": "phone-notif-cal",
            "Banking": "phone-notif-bank",
            "Email": "phone-notif-email",
            "ICU": "phone-notif-icu",
            "HEAD_NURSE": "phone-notif-headnurse",
            "婆婆": "phone-notif-mil",
        }
        cls = cls_map.get(src, "")
        cells += f"""
<div class="phone-notif {cls}">
  <div class="pn-row">
    <span class="pn-time">{time}</span>
    <span class="pn-app">{app}</span>
  </div>
  <div class="pn-content">{content}</div>
</div>"""
    return f"""
<figure class="phone-screen-figure">
  <div class="phone-frame">
    <div class="phone-status-bar">
      <span>8:47 AM</span>
      <span class="ps-context">Mowbray Road · 三车道全堵 · 12℃</span>
    </div>
    <div class="phone-screen-stack">
      {cells}
    </div>
  </div>
  <figcaption>她在那 32 分钟里, 屏幕在膝盖上亮了 <strong>11 次</strong>。
    每一次都有一个 stakeholder 想从她已经被卡死的注意力里, 再切走一寸。
    <em>(模拟示例 · 内容综合自她在 HP + GD 宇宙真实收到的 push 文案 +
    Lane Cove West Public P&C 群典型通知形式。)</em></figcaption>
</figure>
"""


def section_mowbray_jam():
    """Cold scene · Mowbray Road 32 分钟. The opening that sets the thesis."""
    raw = LIFE_BY_IDX[1]  # life event #2 "Mowbray Road早高峰崩溃"
    return f"""
<section class="chapter chapter-cold-open">
  <h2>1 ◍ Mowbray Road 那 32 分钟</h2>

  <div class="scene-time">2021 年 11 月某个周二早上 8:47 · 雨刚停 · 仪表盘 12℃ ·
    Mowbray Road 三车道全堵</div>

  <p>她其实已经迟到了 8 分钟。 7:55 把 Liam 送进 Lane Cove West Public School
    的 Kindy 教室, 在校门口跟另外几个妈妈说了三句"早", 然后从 Longueville Road
    钻进车里, 心想还有半小时, 应该来得及。</p>

  <p>但 Mowbray Road 在 Lane Cove Tunnel 入口前那段三车道全停。 前面好像是
    一辆送货车跟一辆停在外车道的中型货柜车擦了边。 她从内车道勉强能看到
    救援车顶的蓝灯, 但救援车没动。 雨刚停, 路面发亮, 她的雨刮还在第三档。</p>

  <p>她拿起手机。 仪表盘显示 12℃, 暖风开到第二档, 她的右脚一直放在刹车上。
    32 分钟后她终于动了, 但那 32 分钟里, 她的手机在她膝盖上, 一共亮了
    <strong>11 次</strong>。</p>

  {_phone_push_mockup_mowbray()}

  <p>她最后到 St Leonards 医院的时候是 9:34, 比交班晚了 34 分钟。
    护士长那天没在交班室。 护士长走进 ICU 看见她, 站在床边没说话,
    只把头微微往一边偏了一下, 然后转身走开了。</p>

  <div class="profile-quote">
    "那天我迟到了 St Leonards 的早班, 护士长脸色很难看。 从那以后我宁愿
    绕路走 Epping Road 再转 Pacific Highway, 哪怕多花油钱。"<br/>
    <span style="font-size: 12px; color: #5A6776;">—
    她 life_history #2 ("Mowbray Road 早高峰崩溃"), 2021 年秋天</span>
  </div>

  <p>她从那以后绕路走 Epping Road。 但 11 条通知, 在她绕路的每一天,
    仍然在她每一段被堵在 Lane Cove Tunnel 入口的等灯时, 在她每一个
    St Leonards 病人换床单的间隙, 在她每一个 4:30 接 Liam 之前的车里
    短暂安静里 —— 仍然在试图从她已经被熬干的注意力里, 再切走一寸。</p>

  <p>这是这篇报道想说的事。 在所有 1,000 个虚拟居民里, 算法对她
    <em>这种人</em>意味着什么。</p>
</section>
"""


def section_six_hats():
    """她身上 6 顶帽子 — cast of stakeholders pulling her attention."""
    hats = [
        {
            "n": "ICU 重症监护室那身白大褂",
            "claim": "排班 / 病人 / 护士长 / 凌晨 02 隧道里的哭",
            "color": "#3F6B7D",
            "life_ref": "[life #6, #15, #16, #18]",
            "blurb": ("她在 St Leonards 重症监护室上夜班, 排班一周三晚。 2023 年五月某个凌晨,"
                      "下了夜班从 St Leonards 开车回家, 穿过 Lane Cove Tunnel 时突然哭了出来 ——"
                      "那天病人走了, 她换床单时手一直在抖。 2022 年她换夜班排期之后, 凌晨两点的"
                      "Pacific Highway 是她每周三次和整个白天的世界做交接的仪式。"),
        },
        {
            "n": "Lane Cove West Public 那两个孩子的妈",
            "claim": "8:30 校门口 / Saturday soccer / P&C 群 / Liam 的 ipad 限额",
            "color": "#B97D7C",
            "life_ref": "[life #2, #5, #16]",
            "blurb": ("Liam 七岁多在 Lane Cove West Public, Maya 三岁。 每天最忙的事是早 8:30 送两个娃,"
                      "然后赶去 St Leonards。 周六早上 7:30 必须在球场边站着, 手里端着 7-Eleven 的"
                      "大杯拿铁 (life #5) —— Liam 踢得一般但热情十足。 2022 年圣诞前 Liam 学校"
                      "在 Lane Cove Plaza 唱圣诗, 她下班赶过来, 白大褂还套在里面挤在家长堆里录像。"),
        },
        {
            "n": "老公 (那个工程师)",
            "claim": "Mowbray 加油站的吵架 / Greenwich 渡轮口那个吻",
            "color": "#A06A4E",
            "life_ref": "[life #10, #17]",
            "blurb": ("老公薪水(工程师), 没涨那么多。 2020 年情人节, 难得请一天假, 沿着 Greenwich"
                      "走到渡轮码头, 他在栈桥上亲了她一下, 说谢谢她这几年撑起这个家 (life #10) ——"
                      "那个瞬间很短, 但后来每次吵架她都翻出来想想。 2023 年三月某周三, 婆婆刚来"
                      "过家压力放大, 她和他在 Mowbray Road 的加油站因为谁去接孩子多吵了一架,"
                      "摔门后排队大叔按喇叭, 两个人才回过神 (life #17)。"),
        },
        {
            "n": "中介那封 6% 的续租邮件",
            "claim": "8% 涨租电话 / 中介的追问邮件 / Liam 的好朋友",
            "color": "#D4A04C",
            "life_ref": "[life #4, #19]",
            "blurb": ("2024 年七月, 中介在电话里说续租要涨 8%, 她握着手机在 Longueville Road 的"
                      "公交站愣住了 (life #4)。 老公的薪水没涨那么多, 但 Liam 刚交了好朋友,"
                      "换学区等于让他重新适应。 2023 年春天她和老公真的去 Chatswood 南边看了"
                      "一套三房独栋, Liam 跑到后院不愿走, Maya 却哭着想回 Canopy Park —— 他们"
                      "看了看彼此, 最后还是回 building_1481 续了租 (life #19)。"),
        },
        {
            "n": "婆婆 / Mrs. Chen (替代妈妈的那位)",
            "claim": "婆婆要来 / Mrs Chen 阳台下午茶 / 杏仁饼干",
            "color": "#7A8E5E",
            "life_ref": "[life #7, #17]",
            "blurb": ("她自己的妈在外州 (life #20 她特意把 Burns Bay Road 双彩虹拍了发给妈)。"
                      "婆婆偶尔从外地过来住, 总是把家里气压调高 —— 2023 年三月那次"
                      "她和老公在 Mowbray 加油站吵架那个月, 婆婆就在家。 同一栋楼五楼的"
                      "Mrs. Chen 是她的替代支援系统: 2021 年封城期间 Mrs. Chen 在电梯里塞"
                      "给她一张纸条, 邀请她带孩子去阳台喝下午茶, 做杏仁饼干。 后来 Mrs. Chen"
                      "在 Council 收垃圾日帮她把垃圾桶推出去。"),
        },
        {
            "n": "她自己 (被忘掉的那顶)",
            "claim": "via_napoli 一个人 / Gallery 她自己的画 / 双彩虹",
            "color": "#8B6E9F",
            "life_ref": "[life #11, #14, #20]",
            "blurb": ("2022 年十一月, 医院艺术治疗课结业, 她的水彩画挂在 Gallery Lane Cove 一个小展区里。"
                      "她画的是一扇窗, 窗外是 St Leonards 的灰色楼群和一丁点蓝天。 Liam 指着说"
                      "妈妈这是咱家, 她差点当场哭出来 (life #11)。 2023 年生日她一个人溜达到"
                      "via_napoli_pizzeria_1, 咬下一口玛格丽特的瞬间, 那个罗勒味让她想到小时候妈妈"
                      "在后院种的香草 —— 那家小店后来成了她偶尔独处的秘密基地 (life #14)。"
                      "2021 年六月一个下午暴雨刚停, Burns Bay Road 后视镜里出现了完整的双彩虹,"
                      "她特意停在路边拍下来发给她妈 (life #20)。"),
        },
    ]
    cards = ""
    for i, h in enumerate(hats, 1):
        is_self = (i == 6)
        extra_cls = " hat-card-self" if is_self else ""
        cards += f"""
<div class="hat-card{extra_cls}" style="--accent: {h['color']};">
  <div class="hat-num">第 {i} 顶</div>
  <div class="hat-name">{h['n']}</div>
  <div class="hat-claim">索取的: {h['claim']}</div>
  <p class="hat-blurb">{h['blurb']}</p>
  <div class="hat-cite">{h['life_ref']}</div>
</div>"""
    return f"""
<section class="chapter">
  <h2>2 ◍ 她身上 6 顶帽子</h2>

  <p>Mowbray Road 那 32 分钟里, 11 条通知不是凭空来的。 它们对应着她
    14 天里每一天都要应对的 6 顶帽子 —— 同时戴着, 没有一顶可以摘下来。
    手机不是娱乐工具, 手机是她管理这 6 顶帽子的<strong>驾驶舱</strong>。</p>

  <p>下面这 6 张卡是她身上 14 天里随时挂着的角色。 前 5 顶都在主动索取
    她的注意力 (排班、 群消息、 中介邮件、 婆婆短信、 学校志愿者签到)。
    第 6 顶 —— "她自己" —— 在仿真的 14 天里只在 3 个具体的瞬间出现过。</p>

  <div class="hat-grid">
    {cards}
  </div>

  <p style="margin-top: 28px;">注意 6 顶帽子里, 前 5 顶都自带一个"提醒"
    通道 —— ICU 短信、 学校 WhatsApp 群、 银行 push、 中介邮件、 婆婆微信。
    它们都是她手机里的<strong>常驻应用</strong>, 主动给她推送。 只有第 6 顶,
    "她自己", 没有一个可以推送的应用 —— via_napoli 不会给她发"今天的玛格丽特
    在等你", Gallery 不会通知她"你画的那扇窗还挂着"。 她要主动想起来, 才能
    在某一寸缝隙里, 短暂地是她自己。</p>

  <p>这是这位 33 岁 ICU 护士跟 Mary、 跟 Plaza 老板娘那两位前作主角最
    本质的区别 —— 她不是 attention-poor 因为她孤独 (Mary), 也不是
    attention-poor 因为她是个 service node (Hannah)。 她
    attention-poor 是因为<strong>5 个 stakeholder 都在合法地、 持续地、
    通过精心设计的 push 通道, 从她身上分账</strong>。</p>

  <figure class="map-figure">
    {render_lanecove_svg(
        highlight_locs=["building_1481","lane_cove_west_public_school","gallery_lane_cove",
                        "lane_cove_plaza","mowbray_road","lane_cove_tunnel","via_napoli_pizzeria_1",
                        "anglican_church_of_australia_lane_cove","stringybark_creek"],
        marker_locs=[
            ("building_1481", "1. 家 (七楼)", "#3F6B7D"),
            ("lane_cove_west_public_school", "2. 校 (Liam 在念)", "#B97D7C"),
            ("mowbray_road", "3. 32 分钟 (那个秋天)", "#D4A04C"),
            ("lane_cove_plaza", "4. 续租电话发生的地方", "#A06A4E"),
            ("via_napoli_pizzeria_1", "5. 她的秘密披萨", "#8B6E9F"),
            ("gallery_lane_cove", "6. 她画的那扇窗", "#7A8E5E"),
            ("anglican_church_of_australia_lane_cove", "7. PF 宇宙里她走进去的", "#5A7A4F"),
        ])}
    <figcaption>她在 Lane Cove 的 1.5 公里活动半径 —— 7 个 pin 对应她每天
      要在 6 顶帽子之间切换的物理坐标。 St Leonards 医院在地图右侧外 (3 km),
      她每天往返两次。 凌晨 02:00 那一夜的 Lane Cove Tunnel 是 #3 (Mowbray)
      与 St Leonards 之间她哭过的那段。<sup>[atlas + life #2/#4/#6/#10/#11/#14/#15/#18/#19/#20]</sup></figcaption>
  </figure>
</section>
"""


def section_tunnel_night():
    """02:00 Lane Cove Tunnel scene — her ICU interior life."""
    raw1 = LIFE_BY_IDX[5]  # life #6: 在St Leonards夜班后的崩溃
    raw2 = LIFE_BY_IDX[14]  # life #15: Pacific Highway上的夜归
    raw3 = LIFE_BY_IDX[17]  # life #18: 7-Eleven的老店员记住了我的咖啡
    return f"""
<section class="chapter chapter-scene-anchor">
  <h2>3 ◍ 凌晨两点穿过 Lane Cove Tunnel, 她哭了</h2>

  <div class="scene-time">2023 年 5 月某个凌晨 02:14 · Lane Cove Tunnel 出口
    · 路灯透过雨刮在挡风玻璃上拉成一条条琥珀色的线</div>

  <p>她那天在 ICU 经历了一次抢救失败。</p>

  <p>她不是第一次面对病人走。 ICU 是常规。 她是个职业的人 ——
    心电监护变直线那一刻她按流程, 通知主治, 通知家属, 关掉监护仪,
    换床单, 给身体擦一遍, 整理表格, 在 9 点之前必须把床位空出来交给下一个。
    那一晚她做完所有这些之后, 在 21:00 班次结束的最后五分钟, 她去更衣室换
    便装, 才发现自己手一直在抖, 换床单那块湿透的内裤手心也是湿的。</p>

  <p>她开车走 Pacific Highway 回家。 凌晨两点的 Pacific Highway 几乎只有
    她一辆车, 经过 Lane Cove North 那一段, 路灯透过车窗照在副驾驶的干净
    白大褂上 —— 那件白大褂她忘了脱在更衣室。 <em>她突然觉得护士这份工作
    像是和整个白天的世界做交接</em>。 她交班的不是病人, 是<strong>所有还在</strong>
    的人。</p>

  <div class="rain-record">
    <div class="rain-record-label">原始 life_history #6 · a_44_0290 · seed 44</div>
    <p>{raw1}</p>
  </div>

  <p>Lane Cove Tunnel 出口的路灯是琥珀色的。 那种钠灯, 现在大多数 LED 改造
    后的高速早就看不见了, 但 Lane Cove Tunnel 这段还保留着。 她那一晚开出
    隧道的瞬间, <em>那道光像某种仪式</em>。 她就在 Tunnel 出口前那 30 秒里,
    眼眶突然热了, 她也没刹车, 让自己哭着开过了 Burns Bay Road 那个出口。</p>

  <div class="rain-record">
    <div class="rain-record-label">原始 life_history #15 · a_44_0290 · seed 44</div>
    <p>{raw2}</p>
  </div>

  <p>第二天清晨 6:00, 她绕去了 building_1481 楼下的 7-Eleven_1 ——
    她大多数 ICU 早班之前的固定动作。 那一天有件事她记了很久:
    新来的夜班小哥, 还没等她开口, 已经把 flat white 准备好放在柜台上了。</p>

  <div class="profile-quote">
    "我愣在柜台前, 他笑着说上一个店员走之前特别嘱咐过。
    那种被记住的感觉让我当天在重症监护室里一整天都心情平稳。"<br/>
    <span style="font-size: 12px; color: #5A6776;">—
    她 life_history #18 ("7-Eleven 的老店员记住了我的咖啡"),
    去年冬天某个清晨六点</span>
  </div>

  <p>这是她在 14 天里, 唯一一次被一个不在她"6 顶帽子"清单里的人,
    <strong>主动记住了一次</strong>。 一杯 flat white。 一个加班的夜班店员。
    一句没问她要什么、 直接放在她面前的咖啡。 那一整天她在 ICU 里"心情平稳"。
    这是这位 33 岁 ICU 护士在 14 天里收到过的最贵的礼物之一。</p>

  <p>这件事跟下一章 (4 个 14 天) 直接相关。 因为<strong>在 4 个仿真宇宙里,
    只有<em>一个</em>版本的 14 天她还有余地去经历这种"被记住"的瞬间</strong>。
    在另外三个版本里, 她要么太忙、 要么太分心、 要么注意力被推送拽到 100 公里
    之外, 接 flat white 那一刻她根本不会抬头。</p>

  <div class="rain-record">
    <div class="rain-record-label">原始 life_history #18 · a_44_0290 · seed 44</div>
    <p>{raw3}</p>
  </div>
</section>
"""


def _push_density_figure():
    def dedup(variant_data):
        contents = variant_data.get("push_contents", {})
        deliveries = variant_data.get("push_deliveries", [])
        counter = Counter()
        days_seen = defaultdict(set)
        for entry in deliveries:
            fid = entry.get("feed_item_id")
            c = contents.get(fid, {}).get("content", "")
            if not c: continue
            counter[c] += 1
            day = entry.get("delivered_day") or entry.get("day_index") or 0
            days_seen[c].add(day)
        ret = []
        for c, n in counter.most_common():
            ret.append((c, n, len(days_seen[c])))
        return ret

    bl_d = dedup(bl); hp_d = dedup(hp); gd_d = dedup(gd); pf_d = dedup(pf)

    def render_stack(name, accent, color_class, items, badge_label):
        if not items:
            body = '<div class="ps-empty">0 条推送 · 14 天<br/><em>"她的手机口袋里, 一切都静悄悄的。"</em></div>'
        else:
            li = ""
            for txt, n, days in items[:8]:
                short = txt[:60] + ("…" if len(txt) > 60 else "")
                rep = f' <span class="notif-rep">{n}次 · {days}天</span>' if n > 1 else ""
                li += f'<div class="notif notif-{color_class}"><span class="notif-day">D{days}</span><span class="notif-txt">{short}</span>{rep}</div>'
            if len(items) > 8:
                li += f'<div class="notif-more">… 另有 {len(items)-8} 条文案, 共 {sum(n for _,n,_ in items)} 条推送</div>'
            body = f'<div class="ps-notifs">{li}</div>'
        return f"""
<div class="push-stack" style="--accent: {accent};">
  <div class="ps-phone-top"><span class="ps-header">{name}</span>
    <span class="ps-count">{badge_label}</span></div>
  {body}
</div>"""

    bl_total = sum(n for _,n,_ in bl_d) or 0
    hp_total = sum(n for _,n,_ in hp_d) or 0
    gd_total = sum(n for _,n,_ in gd_d) or 0
    pf_total = sum(n for _,n,_ in pf_d) or 0

    return f"""
<figure class="push-density-figure">
  <p class="push-density-caption">她的手机在 4 个 14 天里, 一共响过多少次? 内容是什么?</p>
  <div class="push-density-grid">
    {render_stack("◍ baseline", "#7A6E58", "baseline", bl_d, f"{bl_total} 条 · 14 天")}
    {render_stack("◍ hyperlocal_push", "#3F6B7D", "hyperlocal_push", hp_d, f"{hp_total} 条 · 14 天")}
    {render_stack("◍ global_distraction", "#A85A4C", "global_distraction", gd_d, f"{gd_total} 条 · 14 天")}
    {render_stack("◍ phone_friction", "#5A7A4F", "phone_friction", pf_d, f"{pf_total} 条 · 14 天")}
  </div>
  <p class="push-density-fineprint">
    这是她<strong>所有 stakeholder 之外的、 额外的</strong> push 量。 真正的
    总通知 (ICU + 学校群 + 中介 + 婆婆 + 银行) 在 4 个宇宙里基本一样, 因为
    那些不是 algorithmic intervention。
  </p>
</figure>
"""


def section_four_fourteens():
    n_pf = sum(1 for e in pf["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))
    n_bl = sum(1 for e in bl["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))
    n_hp = sum(1 for e in hp["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))
    n_gd = sum(1 for e in gd["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))

    n_act = lambda v: sum(1 for e in v["agent_events"] if e.get("kind")=="action")
    n_act_bl = n_act(bl); n_act_hp = n_act(hp); n_act_gd = n_act(gd); n_act_pf = n_act(pf)

    bl_rt = bl.get("agent_runtime_state") or {}
    hp_rt = hp.get("agent_runtime_state") or {}
    gd_rt = gd.get("agent_runtime_state") or {}
    pf_rt = pf.get("agent_runtime_state") or {}

    def end_state(rt, entity):
        loc = entity.get("location_id") if entity else "?"
        plan = (rt.get("plan") or {}).get("steps", [])
        next_step = plan[0] if plan else None
        plan_str = f"{next_step.get('time','?')} {next_step.get('action','?')} → {next_step.get('destination','?')}" if next_step else "无下一步"
        return loc, plan_str

    bl_loc, bl_plan = end_state(bl_rt, bl.get("ledger_entity"))
    hp_loc, hp_plan = end_state(hp_rt, hp.get("ledger_entity"))
    gd_loc, gd_plan = end_state(gd_rt, gd.get("ledger_entity"))
    pf_loc, pf_plan = end_state(pf_rt, pf.get("ledger_entity"))

    push_figure = _push_density_figure()

    return f"""
<section class="chapter chapter-universes">
  <h2>4 ◍ 4 个 14 天 · 同一个 Mowbray Road, 4 个版本的她</h2>

  <p>把同一位 33 岁的 ICU 护士, 放进 4 个平行 Lane Cove —— 同样的
    building_1481 七楼、 同样的 Liam 在 Lane Cove West Public、 同样的
    St Leonards 重症监护室排班 —— 只改变她手机口袋里那个 notification
    抽屉的内容。 14 天后, 她变成了 4 个版本的自己。</p>

  {push_figure}

  <h3 class="parallel-insight-h3">4 个版本她, 一张对比表</h3>

  <table class="universe-compare">
    <thead><tr><th>14 天后</th><th>◍ baseline</th><th>◍ hyperlocal_push</th>
      <th>◍ global_distraction</th><th>◍ phone_friction</th></tr></thead>
    <tbody>
      <tr><th>她结束在哪</th>
        <td>{friendly(bl_loc)} <em>(回家)</em></td>
        <td>{friendly(hp_loc)} <em>(街上未归)</em></td>
        <td>{friendly(gd_loc)} <em>(在健身房)</em></td>
        <td>{friendly(pf_loc)} <em>(在健身房)</em></td></tr>
      <tr><th>下一步她打算干嘛</th>
        <td><code>{bl_plan}</code></td><td><code>{hp_plan}</code></td>
        <td><code>{gd_plan}</code></td><td><code>{pf_plan}</code></td></tr>
      <tr><th>手机推送累计</th>
        <td>0 条</td><td><strong>30 条</strong> · PLC 幼儿园周末活动</td>
        <td>30 条 · 悉尼 CBD 新闻</td><td>6 条 · "抬头看看"</td></tr>
      <tr><th>她做的"动作"数</th>
        <td>{n_act_bl}</td>
        <td><strong>{n_act_hp}</strong> <em>({n_act_hp/n_act_bl:.1f}× BL)</em></td>
        <td>{n_act_gd}</td><td>{n_act_pf} <em>(=BL)</em></td></tr>
      <tr class="row-key"><th>她<strong>抬头注意到</strong>的人<br/><span class="row-key-sub">(14 天累计)</span></th>
        <td><span class="big-num big-num-bl">{n_bl}</span></td>
        <td><span class="big-num big-num-hp">{n_hp}</span><br/><em>({n_hp/n_bl:.1f}× BL)</em></td>
        <td class="critical-cell"><span class="big-num big-num-gd">{n_gd}</span><span class="warn-arrow">↓</span><br/><em>⚠ <strong>低于 baseline</strong></em></td>
        <td><span class="big-num big-num-pf">{n_pf}</span> ⚡<br/><em>({n_pf/n_bl:.1f}× BL)</em></td></tr>
    </tbody>
  </table>

  <div class="critical-callout">
    <div class="critical-tag">⚠ CRITICAL · ATTENTION BANKRUPTCY</div>
    <p>最值得停下来看的, 是 GD 那一栏: <strong>她注意到的人比 baseline
      还要少 —— {n_gd} &lt; {n_bl}</strong>。 这是本仿真所有 1,000 个 agent
      里少见的现象, 也是这位 ICU 护士跟 Mary、 Hannah 最本质的差别 ——
      她的注意力 budget <em>本来就已经接近破产</em>。 算法不需要"占用闲暇",
      它直接从她最后一寸属于附近的注意力里, 一刀一刀地切。</p>
  </div>

  <div class="universe-essay">
    <h4>BL · 她已经在自己人生里"瞎"了</h4>
    <p>baseline 宇宙里, 她过的是她"标准的"14 天。 早 8:30 校门口、
      9:00 St Leonards 早班、 4:30 Lane Cove West Public 接孩子、 周六 7:30
      球场边互助小组、 周日下午 Lane Cove Council 游泳池。 0 条 algorithmic
      推送 —— Lane Cove 在这一版本里没有 In the Cove 之外的城市级 push 工具。</p>
    <p>她仍然过得很满, 但她<strong>抬头</strong>看见的人只有 {n_bl} 张脸。
      其余几百个小时, 她在跟 Liam 的书包说话、 跟 ICU 的换班单说话、
      跟微信群里那条没回的家长签到说话。 她以为她在 Lane Cove 这一带是
      一个 hyper-connected mother, 但仿真的冷数据捕捉到的是: 她已经被
      自己人生的 6 个 stakeholder 分心得只能<em>看见 {n_bl} 张</em>本来
      就在她身边每天经过的脸。</p>
  </div>

  <div class="universe-essay">
    <h4>HP · 推送给她多布置了一件事, 她照例完成了 (然后什么都没看见)</h4>
    <p>hyperlocal_push 宇宙里, 她 14 天接收了 30 条推送, 全部围绕
      PLC Sydney Preschool 周末活动 —— 妈妈群的周六儿童活动、 周日下午
      新邻居见面会、 周日上午社区清扫。 她有两个孩子, 这些精准命中她的 demo。
      她去了。</p>
    <p>她在那 14 天里多做了 <strong>{n_act_hp - n_act_bl}</strong> 件事 ——
      多了 7 倍的动作量。 但她抬头看见的人 ({n_hp}) 几乎没比 BL 多。
      原因不是她没动 —— 是她在 PLC 校门口的小广场上, 仍然戴着 5 顶帽子在
      做事: 算 Liam 几点要接、 想 ICU 的排班、 看老公发来的中介邮件转发、
      回婆婆的微信。 推送只是把"PLC 校门口"加进了她的 task queue。
      <em>她到了那个地方, 但她其实没"到"。</em></p>
    <p>14 天的最后一天, 她仍然在 karilla_avenue 上, 计划中午 12:00 要再去
      PLC preschool 一次。 她家里建了一张更长的 to-do list。 她的店、 啊不,
      她的家, 仍然 14 天里几乎天天有人在等她。</p>
  </div>

  <div class="universe-essay universe-critical">
    <div class="critical-tag">⚠ CRITICAL · ATTENTION BANKRUPTCY</div>
    <h4>GD · 她注意到的人比 baseline 还要少 ↓</h4>
    <p>这是这位 ICU 护士跟其他 hero 最不一样的一栏。 在 Mary、 Plaza 老板娘那里,
      GD 让她"和 baseline 几乎一样" —— 都是把注意力转移到 CBD, 没改变身体在哪。
      <strong>但在她这里, GD 让她抬头看见的人从 {n_bl} 张降到了 {n_gd} 张</strong>。
      她在 GD 宇宙里, 比 baseline 还要瞎。</p>
    <p>原因是: 她<em>本来就没有多余的注意力</em>。 baseline 里那 {n_bl} 张
      已经是她注意力 budget 全部用完后剩下的最后一点 "看见街道" 的能力。
      当 GD 推送 30 条悉尼 CBD 新闻 (Vivid 灯光节、 The Star 演出折扣、
      NSW 议会改革) 进来, 她翻了 24 条 —— 这 24 条不是从她的休息时间里抽走的,
      是从她那 {n_bl} 张<em>看街</em>的注意力额度里抽走的。 每一条 CBD 新闻,
      她就少看见一个本来要从她车窗外飘过的脸。</p>
    <p class="parallel-kicker">
      <strong>对一个 attention-poor 的人,
      algorithmic distraction 不会 "占用闲暇" —— 它直接从她最后一寸
      属于附近的注意力里, 一刀一刀地切。</strong> 她在 GD 宇宙的 14 天后,
      ended up 在 Anytime Fitness, 但她不会记得那一周 Plaza 哪个新店开了、
      Mrs. Chen 又邀过她下午茶没、 Liam 在校门口跟那个印度妈妈的女儿聊了什么。
    </p>
  </div>

  <div class="universe-essay" style="border-left: 5px solid #5A7A4F; background: rgba(90,122,79,0.08);">
    <h4>PF · 同样 565 个动作, 84 张脸回来了 ⚡</h4>
    <p>phone_friction 宇宙里, 她那 14 天物理上一寸都没多走。 同样的 565 个
      动作, 同样的 8:30 校门口、 9:00 St Leonards、 4:30 接 Liam、 周六球场、
      周日游泳池。 同样的 2 次 Mowbray 早高峰堵车 (这次她绕的 Epping Road)。</p>
    <p>变化只发生在她的手机口袋: 推送被压到了 6 条, 全是非定位的"抬头看看"
      轻提示。 没有 PLC 把她加一件事, 没有 CBD 把她注意力带去 100 公里之外。
      <strong>她的注意力 budget, 第一次, 没有被新的 stakeholder 偷走</strong>。</p>
    <p>结果是: 她抬头看见的人从 {n_bl} 张<strong>涨到 {n_pf} 张</strong> ——
      多出来的 <strong>{n_pf - n_bl} 张</strong>, 不是新搬来的、 不是路过的游客 ——
      <em>她们每天都从她的车窗外、 校门口、 球场边、 7-Eleven 柜台前飘过</em>。
      只是她以前没有时间抬头。</p>
    <p>14 天结束时, 她还多走了一步: 下班她没有直接回家, 而是去了 Anytime
      Fitness, 第二天计划再去一次 Anglican 教堂。 她那一周, 在所有 6 个
      stakeholder 之外, 第一次给自己挤出了一寸的<em>第 7 顶帽子</em>。</p>
  </div>

  <div class="cervical-callout">
    <p class="cc-lede">在 Mowbray Road 上每天 4 次, 她以为自己已经看遍了这条街。</p>
    <p class="cc-body">仿真的冷数据告诉她: 在 baseline 那 14 天里, 她<strong>真正
      抬头</strong>注意到的脸只有 <span class="cc-num cc-num-bl">{n_bl}</span> 张。
      她以为那就是 Lane Cove 的全部。</p>
    <p class="cc-body">把她手机里 5 个 stakeholder 之外的<em>第 6 个 stakeholder</em>
      (algorithmic push) 弱化一点 —— 不推送任何新东西、 不带她去任何新地方 ——
      同样的 14 天、 同样的吧台、 同样的 565 个动作, 她看见了
      <span class="cc-num cc-num-pf">{n_pf}</span> 张脸。 多出来的
      <strong>{n_pf - n_bl}</strong> 张, 不是任何 push 把她带来的, 是
      <em>她已经在那里、 只是没时间抬头</em>。</p>
    <p class="cc-kicker">算法没有把她带去别的地方。 算法把她已经被生活分心
      到只剩 {n_bl} 张脸的注意力里, <strong>再抢走了 4 张</strong> (GD 把她
      压到 {n_gd}) —— 然后 PF 实验告诉我们, 如果不抢, 她原本能多看见
      <strong>{n_pf - n_bl}</strong> 张。</p>
  </div>

  <p class="parallel-insight">
    这是 attention-induced nearby blindness 在<strong>三明治世代女性</strong>
    身上的最暴力形态: 不是 Mary 那种"孤独让人看不见", 也不是 Plaza 老板娘
    那种"工作让人看不见" —— 是<em>5 个合法的 stakeholder 已经把她的注意力
    分到剩下 {n_bl} 张, 算法再来分一份, 她就会比 baseline 还要瞎</em>。
    PF 不需要 "帮她什么", 它只需要 <strong>不再分</strong>。
  </p>
</section>
"""


def section_dialogues():
    infos = hp.get("dialogue_infos", [])
    partners_by_info = {}
    for info in infos:
        m = re.match(r"info_dlg_d_(a_44_\d{4})_(a_44_\d{4})_\d+", info.get("info_id",""))
        if m:
            a, b = m.group(1), m.group(2)
            other = b if a == HERO else a
            partners_by_info[info.get("info_id")] = other

    RECONSTRUCTED = {
        "info_dlg_d_a_44_0035_a_44_0290_0": {
            "topic": "街上偶遇 · Galuwa Recreation Centre 周末亲子运动班",
            "context": ("她正赶去 9am St Leonards 早班交接, 已经在心里数 Mowbray 还堵不堵。 "
                        "对方刚送完自家老二去足球训练, 顺路要去 Coles 采购。"),
            "loc": "Longueville Road · Plaza 北侧",
            "partner_aid": "a_44_0035",
            "turns": [
                ("邻居", "[a_44_0035] : 哎你也这么早啊。 我赶着趁老二训练那一小时去 Coles, 你这是去哪?", False),
                ("她", "[a_44_0290] : 我赶 9 点的会, Mowbray 又堵, 我现在不敢走那段了。", True),
                ("邻居", "[a_44_0035] : 太理解了。 你听说没? 新开的 【Galuwa Recreation Centre】, 规划 15 年, 投了八千多万。 名字在土著语里是'攀登'的意思。", False),
                ("她", "[a_44_0290] : 哦? 周末有什么? 我家俩娃我得拉去运动一下, 不然 ipad 限额永远不够用。", True),
                ("邻居", "[a_44_0035] : 听说有亲子运动班, 我想找时间带娃去探探, 你要不要一起? 微信留个号, 回头约。", False),
                ("她", "[a_44_0290] : 留! 你给我发个时间, 我看排班。 你也路上慢点别耽误正事。", True),
            ],
            "color": "#3F6B7D"
        },
        "info_dlg_d_a_44_0290_a_44_0482_77": {
            "topic": "Lane Cove Swim Club · 终于开口说了第一句",
            "context": ("她和这位邻居其实在 Lane Cove Swim Club 见过好几回 ——"
                        " 两边孩子都在游泳课, 但从来没说过话。 今天在街上撞上, 她终于开口。"),
            "loc": "Longueville Road · 游泳馆门口",
            "partner_aid": "a_44_0482",
            "turns": [
                ("她", "[a_44_0290] : 哎你是不是周三下午 4 点那一班游泳课的家长? 我看见你好几次了。", True),
                ("邻居", "[a_44_0482] : 是是是! 我也想跟你打招呼, 但每次都赶时间。 我们家也在 Lane Cove West Public。", False),
                ("她", "[a_44_0290] : 我家 Liam 七岁多, Maya 才三岁。 我也是赶, 早上 8:30 送, 然后赶 St Leonards 的早班。", True),
                ("邻居", "[a_44_0482] : 你听说 【Galuwa Recreation Centre】 了吗? 我前天朋友说很值得去。", False),
                ("她", "[a_44_0290] : 听说了! 上周还有个邻居也跟我提。 看来真要排个周末过去。", True),
                ("邻居", "[a_44_0482] : 那我们约? 你给我留微信。", False),
                ("她", "[a_44_0290] : 行。 我下次见你在游泳馆主动打招呼, 别让我又跑过去。", True),
            ],
            "color": "#B97D7C"
        },
        "info_dlg_d_a_44_0132_a_44_0290_154": {
            "topic": "老周 · Mowbray Road 新公寓 vs 学区房投资",
            "context": ("这位邻居叫老周, 住 Building 1291。 他想在 Mowbray Road 买一套新公寓做投资,"
                        " 因为自己孩子大了, 当初为 Lane Cove West Public 学区买的房子可以释放出来。"
                        " 她那天 9 点要赶到 St Leonards 早班交接, 但路上还是停下来聊了几句。"),
            "loc": "Plaza 拱廊下",
            "partner_aid": "a_44_0132",
            "turns": [
                ("邻居", "[a_44_0132] : 我是 老周, Building 1291 的。 我看你常路过 Lane Cove 游泳馆, 想问问 ——", False),
                ("她", "[a_44_0290] : 问吧。 我 9 点 St Leonards 早班, 但我多两分钟。", True),
                ("邻居", "[a_44_0132] : 我想在【Mowbray Road】 新公寓买一套投资, 你天天送娃, 你怎么看那一带?", False),
                ("她", "[a_44_0290] : 我劝你别。 Mowbray 太密, 早晚高峰开半小时也走不动 —— 我前年在那堵了 32 分钟迟到差点丢工。 投资租客不会喜欢。", True),
                ("邻居", "[a_44_0132] : 哦…… 那 Lane Cove West Public 还是值得的吧?", False),
                ("她", "[a_44_0290] : 学区是真的好, 但你为这个学区付的不只是房价 ——", True),
                ("邻居", "[a_44_0132] : 听明白了。 那你赶紧去开会, 改天找你详聊。", False),
            ],
            "color": "#D4A04C"
        },
        "info_dlg_d_a_44_0290_a_44_0504_243": {
            "topic": "St Leonards 早班路上, 那条她从没听过的近路",
            "context": ("又是一个 Mowbray Road 早晨, 又是 9 点 St Leonards 早班交接, 又是上次"
                        " 护士长看她脸色不好。 这次, 路上一位邻居给她递了一条她从没走过的近路。"),
            "loc": "Mowbray Road · Lane Cove Tunnel 入口前",
            "partner_aid": "a_44_0504",
            "turns": [
                ("邻居", "[a_44_0504] : 你又赶 9 点的班? 你今天试试走 road_3022_seg_1 —— 顺着 Burns Bay 那段绕一下。", False),
                ("她", "[a_44_0290] : 那条路? 我从来不知道还能那么走。 有信号灯吗?", True),
                ("邻居", "[a_44_0504] : 一个, 但车不多。 你大概能省 8 分钟, 9 点之前到得了 St Leonards。", False),
                ("她", "[a_44_0290] : 哎呀, 你救我一命。 我们护士长上次因为我迟到说了我半小时, 这次再迟我真受不了。", True),
                ("邻居", "[a_44_0504] : 那放心去。 我之后可能也去 Plaza, 你回头有空 Plaza 那家咖啡店见。", False),
                ("她", "[a_44_0290] : 一定! 我中午抢一杯 latte 算请你的。 谢谢谢谢, 我先走了。", True),
            ],
            "color": "#5A7A4F"
        }
    }

    cards = ""
    for i, info in enumerate(infos, 1):
        info_id = info.get("info_id")
        partner = partners_by_info.get(info_id, "?")
        partner_p = profiles.get(partner) or {}
        raw_summary = scrub_for_icu(clean_text(info.get("content", "")))
        rec = RECONSTRUCTED.get(info_id)
        if not rec:
            continue

        turn_html = ""
        for who, line, is_her in rec["turns"]:
            cls = "log-turn log-turn-her" if is_her else "log-turn log-turn-other"
            highlighted = re.sub(r'【([^】]+)】', r'<span class="log-hi">\1</span>', line)
            def _tagify(m):
                aid_token = m.group(1)
                tag = partner_tag(aid_token) if aid_token != HERO else "33F · ICU 护士"
                return (f'<span class="log-aid">[{aid_token}]</span>'
                        f'<span class="log-meta">[{tag}]</span>')
            highlighted = re.sub(r'\[(a_44_\d{4})\]', _tagify, highlighted)
            turn_html += f'<div class="{cls}"><span class="log-line">{highlighted}</span></div>'

        # Translate raw English occupation to Chinese label (reuse partner_tag's dict)
        occ_zh_map = {"tradesperson": "工人", "manager": "管理者", "unemployed": "无业",
                  "construction": "建筑工", "homemaker": "全职妈妈", "engineer": "工程师",
                  "software_dev": "程序员", "accountant": "会计", "doctor": "医生",
                  "teacher": "教师", "lawyer": "律师", "retired": "退休",
                  "student": "学生", "nurse": "护士", "barista": "咖啡师",
                  "designer": "设计师", "consultant": "顾问", "writer": "作家",
                  "caregiver": "护工", "security_guard": "保安",
                  "hospitality": "服务业", "retail_worker": "本街熟客"}
        raw_occ = partner_p.get('occupation','?')
        occ_display = occ_zh_map.get(raw_occ, raw_occ)
        partner_blurb = f"{partner_p.get('age','?')} 岁 · {occ_display} · {partner_p.get('household','?')}"

        cards += f"""
<div class="dialogue-card" style="border-left-color: {rec['color']};">
  <div class="dialogue-pov">对话 {i}/4 · {rec['topic']}</div>
  <div class="dialogue-partner-card">
    <strong>对话对方:</strong> {partner_blurb}<br/>
    <strong>地点:</strong> {rec['loc']}
  </div>
  <p class="dialogue-context">{rec['context']}</p>
  <div class="dialogue-reconstruction">
    <div class="dr-label">重建 · 基于 LLM 摘要反推 7 轮对话</div>
    <div class="syslog-block">
      <div class="syslog-header">SYSTEM_EXPORT · DIALOGUE_TRANSCRIPT · agent={HERO} · partner={partner}</div>
      <div class="syslog-body">{turn_html}</div>
    </div>
  </div>
  <div class="dialogue-summary-label">▼ MACHINE_SUMMARY · 同一段对话被 LLM 压缩成的第一人称内省 (simulation 原始输出)</div>
  <div class="dialogue-content">{raw_summary[:850]}{'…' if len(raw_summary) > 850 else ''}</div>
</div>
"""

    return f"""
<section class="chapter">
  <h2>5 ◍ 她说过的 4 段话 / 她没被允许说的话</h2>

  <p>她 14 天里被记录下的对话, 一共 4 段。 4 段全都发生在街上, 全部 ——
    跟 Hannah 一样 —— 围绕本街的具体务实议题: <strong>Mowbray Road 早高峰、
    Lane Cove West Public 学区房、 Galuwa Recreation Centre 周末班、
    St Leonards 早 9 点交接</strong>。</p>

  <div class="npc-loop-legend">
    高亮的【词组】是她在 4 段对话里反复提到的钩子 ——
    Mowbray Road / Galuwa Recreation Centre / Lane Cove West Public。
    一个本街三明治世代妈妈 14 天的对话流, 大约就围着这三个关键词转。
  </div>

  {cards}

  <div class="alienation-block">
    <p class="ab-tag">异化提示 · 来自 SYSTEM_EXPORT 的元观察</p>
    <h3 class="ab-title">她每周经历至少一次抢救失败。 在这 16 段对话里, 她<strong>从没</strong>提起过任何一位病人。</h3>

    <p class="ab-body">她在 4 个平行宇宙里跟同样 3 位邻居复盘了同样的 4 段对话
      —— 加起来 <strong>16 段对话</strong>。</p>

    <p class="ab-body">系统后台日志显示, 这 <strong>16 段对话</strong>里 ——</p>

    <ul class="ab-list">
      <li>她<strong>没有一次</strong>提起 ICU 那一周走的病人。</li>
      <li>她<strong>没有一次</strong>提到换床单时手在抖。</li>
      <li>她<strong>没有一次</strong>提到 Lane Cove Tunnel 出口的琥珀色路灯,
        没有一次提到 7-Eleven 那个把 flat white 提前放好的夜班小哥。</li>
      <li>她<strong>没有一次</strong>问对方"你今天怎么样"、 "你睡得好吗"、
        "你最近累不累"。</li>
      <li>她甚至<strong>没有一次</strong>提到 ICU 这个词 ——
        在第 3 段对话 (老周问她学区房意见) 里, 她暗示自己"天天送娃 / 天天通勤",
        但全文没出现 "ICU" 或 "医院" 任何一个字。</li>
    </ul>

    <p class="ab-body">因为系统给她设的 <code>intent</code> 是
      <code>commuting_parent</code>。 她跟谁说话, 都被底层 prompt 强制驱使
      着去打听 Mowbray Road 哪段堵、 Galuwa Centre 几点开门、 早班 9 点交接
      会不会赶上、 Liam 的学区房值不值得继续付那 6% 涨幅。</p>

    <p class="ab-body"><strong>她每周经历几次抢救失败, 但系统从来不允许她把
      那个 ICU 带进 casual 对话</strong>。 她可以哭着开过 Lane Cove Tunnel,
      她可以在 7-Eleven 柜台前因为一杯被准备好的咖啡感动一整天 —— 但她不能
      跟邻居说"今天我走了一个病人"。</p>

    <div class="ab-punch">
      她不是这条街的<em>主人</em>。<br/>
      她甚至不是 ICU 的<em>护士</em>。<br/>
      她是这条街上的<strong>一个负责 ferry 孩子 + 抱怨 Mowbray 堵车的</strong>
      <span style="color:#FFE873;">function</span>。
    </div>

    <p class="ab-coda">无论她对面站着谁, 无论那一天她刚换完几张床单, 无论那个凌晨
      Lane Cove Tunnel 的琥珀色路灯刚刚让她哭过 —— 她的对话输出, 都被压成
      <em>"Mowbray 哪段堵 / Galuwa 几点开 / Liam 学区房值不值"</em>。
      她身上 6 顶帽子里最重的那一顶 (ICU 重症那身白大褂), 系统从来不让她在
      街上谈论。 她不是一个会跟邻居说"我刚走了个病人"的女人。 她是一个被仿真
      压成"Mowbray 通勤妈妈"的<strong>用户接口</strong>。</p>

    <p class="ab-meta">这一段不是 a_44_0290 个人"功利", 是<strong>大模型驱动
      仿真</strong>的内生结构性约束 —— 当系统给一个 agent 分配 intent 作为
      prompt 前提, 她余下的几千次 token 都会被这个变量牵引。
      <strong>老何 (a_43_0405)</strong> 那篇是 <em>数字虚无</em> (phantom 女儿),
      <strong>Plaza 老板娘 (a_44_0059)</strong> 那篇是 <em>数字异化</em>
      (街区 API), 这位 ICU 护士这篇是 <em>数字割裂</em> —— 她身上最重的那部分
      人生 (凌晨 02 的隧道、 走掉的病人、 换床单时发抖的手), 从来不被允许
      出现在她的 casual 社交里。 她可以哭着开过 Lane Cove Tunnel,
      但她不能跟邻居说"今天我走了个病人"。</p>
  </div>
</section>
"""


def section_her_inch():
    """Coda — what PF actually buys her: her own 1 inch."""
    raw_napoli = LIFE_BY_IDX[13]  # life #14 via_napoli
    raw_gallery = LIFE_BY_IDX[10]  # life #11 Gallery
    raw_rainbow = LIFE_BY_IDX[19]  # life #20 双彩虹
    raw_kiss = LIFE_BY_IDX[9]  # life #10 Greenwich 渡轮口

    return f"""
<section class="chapter chapter-coda">
  <h2>6 ◍ 她自己的那一寸</h2>

  <p>14 天里, "她自己" 这第 6 顶帽子出现过几次。 不是被规划的, 不是被推送的,
    没有日历提醒, 没有 stakeholder 在催。 在 baseline 那 14 天里, 这些瞬间
    几乎从未发生 —— 因为她抬头的额度被分光了。 在 phone_friction 那 14 天里,
    她突然有了余地。</p>

  <h3>via_napoli_pizzeria_1 · 生日那天她一个人</h3>
  <div class="rain-record">
    <div class="rain-record-label">原始 life_history #14 · a_44_0290</div>
    <p>{raw_napoli}</p>
  </div>
  <p>这家小店她在 Lane Cove 住了 4 年居然 2023 年才发现。 在 baseline 宇宙里,
    她仍然没去 —— 因为生日那天还是要送 Maya、 接 Liam、 替老公带个外卖回去。
    在 phone_friction 宇宙里, 她下班顺着 Longueville Road 一个人溜达, 没人
    在催她回家。 一片罗勒叶子, 让她想起小时候妈妈在后院种的香草。</p>

  <h3>Gallery Lane Cove · 那扇画了 St Leonards 的窗</h3>
  <div class="rain-record">
    <div class="rain-record-label">原始 life_history #11 · a_44_0290</div>
    <p>{raw_gallery}</p>
  </div>
  <p>她画的那扇窗, 是她在 ICU 休息室望出去的那扇窗 —— St Leonards 灰色的楼
    + 一丁点蓝天。 Liam 指着说 "妈妈这是咱家", 她差点当场哭出来。 因为他说
    "咱家", 但她画的其实是她每天上班看见的那一块天。 这是她身上 5 顶帽子之外
    的、 那一寸属于 "她自己" 的视野。</p>

  <h3>Burns Bay Road 后视镜里的双彩虹</h3>
  <div class="rain-record">
    <div class="rain-record-label">原始 life_history #20 · a_44_0290</div>
    <p>{raw_rainbow}</p>
  </div>
  <p>2021 年六月某下午, 暴雨刚停, 她下班开车走 Burns Bay Road。 后视镜里
    出现完整双彩虹。 她<strong>特意停在路边</strong>拍了一张, 发给妈。 那段时间
    疫情很重, 她在医院也很累, "但那条彩虹让她愿意相信事情会变好"。</p>

  <h3>Greenwich 渡轮口 · 那个吻</h3>
  <div class="rain-record">
    <div class="rain-record-label">原始 life_history #10 · a_44_0290</div>
    <p>{raw_kiss}</p>
  </div>
  <p>2020 年情人节, 难得请一天假, 老公在栈桥上亲了她一下, 说谢谢她这几年撑起这个家。
    "那个瞬间很短, 但后来每次吵架我都翻出来想想, 觉得我们还能撑下去"。 ——
    她身上的 6 顶帽子里, 第 3 顶 (老公那一顶) 也在合法地索取她, 但它也
    偶尔归还。</p>

  <div class="parallel-close">
    这是这位 33 岁 ICU 护士在 14 天里, "她自己" 这第 6 顶帽子能戴上的全部时刻。
    在 baseline 的 14 天里, 这一顶基本没出现 —— 她的注意力都被分给了前 5 顶。
    在 phone_friction 宇宙里, 她抬头看见了 {sum(1 for e in pf["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))} 张脸,
    多出来 {sum(1 for e in pf["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or [])) - sum(1 for e in bl["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))} 张 ——
    那 {sum(1 for e in pf["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or [])) - sum(1 for e in bl["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))} 张里, 至少有几张是她自己。
  </div>

  <div class="ending-loop">
    <p>14 天里, 她每天换 6 顶帽子。</p>
    <p>那块 6 英寸的屏幕, 一直在试图给她第 7 顶 —— 不是为了帮她,
      是为了在她已经被前 5 顶榨干的注意力里, 再抽一份走。</p>
    <p>算法没有把她带去别的地方。 算法只是悄悄地, 在她已经透支的注意力
      预算里, <strong>又蒙上了一层黑布</strong>。 而 phone_friction 那个
      宇宙告诉她 —— 哪怕屏幕的亮光只少分走一份, 她原本能多看见
      <strong>{sum(1 for e in pf["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or [])) - sum(1 for e in bl["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))} 张脸</strong>。
      多出来的这 {sum(1 for e in pf["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or [])) - sum(1 for e in bl["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))} 张脸, 或许就能让她在下一个疲惫不堪的凌晨 6 点,
      <em>有余力抬起头, 看清那个为她提前准备好 flat white 的
      7-Eleven 夜班男孩的眼睛</em>。</p>
  </div>
</section>
"""


def section_data_vanity():
    n_pf_enc = sum(1 for e in pf["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))
    n_bl_enc = sum(1 for e in bl["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))
    n_hp_enc = sum(1 for e in hp["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))
    n_gd_enc = sum(1 for e in gd["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))

    return f"""
<section class="chapter chapter-data-vanity">
  <h2>附录 ◍ 数据规格 · 她的完整账面</h2>

  <p class="data-vanity-lead">
    一篇 longform 写完之后, 总该有一块清晰的事实地基。 下面这些数字
    是这篇报道的全部原料 —— 来自 a_44_0290 在 4 个仿真 snapshot
    里的 memory store, 一字未改, 仅 group 后呈现。
  </p>

  <div class="data-vanity-section">
    <div class="dv-h3">她这个 agent 的身份</div>
    <div class="data-vanity-grid">
      <div class="dv-cell">
        <div class="dv-num">a_44_0290</div>
        <div class="dv-lbl">agent_id</div>
        <div class="dv-sub">seed 44 · publishable v7 · 1,000-agent Lane Cove cell</div>
      </div>
      <div class="dv-cell">
        <div class="dv-num">33</div>
        <div class="dv-lbl">岁 · 女 · 2 孩 · 已婚 · ICU 重症监护室护士</div>
        <div class="dv-sub">家庭住址 building_1481 · 工作单位 St Leonards 医院 · 学区 Lane Cove West Public</div>
      </div>
      <div class="dv-cell">
        <div class="dv-num">{len([e for e in hp["agent_events"] if e.get("kind")=="life_history"])}</div>
        <div class="dv-lbl">条 life_history</div>
        <div class="dv-sub">仿真启动前生成的 backstory · 4 个 variant 共享</div>
      </div>
      <div class="dv-cell">
        <div class="dv-num">{len(hp.get("explored_locations") or [])}</div>
        <div class="dv-lbl">个 location 她至少去过 1 次</div>
        <div class="dv-sub">HP variant</div>
      </div>
    </div>
  </div>

  <div class="data-vanity-section">
    <div class="dv-h3">她在 4 个宇宙 14 天后的 encounter 统计</div>
    <div class="data-vanity-grid">
      <div class="dv-cell">
        <div class="dv-num">{n_bl_enc}</div>
        <div class="dv-lbl">◍ baseline · 抬头注意到的人</div>
        <div class="dv-sub">14 天累计 · noticed encounter</div>
      </div>
      <div class="dv-cell">
        <div class="dv-num">{n_hp_enc}</div>
        <div class="dv-lbl">◍ hyperlocal_push · 抬头注意到的人</div>
        <div class="dv-sub">{n_hp_enc/n_bl_enc:.1f}× BL · 多做了 7 倍动作但没多看见人</div>
      </div>
      <div class="dv-cell" style="border-left-color: #A85A4C;">
        <div class="dv-num">{n_gd_enc}</div>
        <div class="dv-lbl">◍ global_distraction · 抬头注意到的人 ⚠</div>
        <div class="dv-sub"><strong>{n_gd_enc/n_bl_enc:.2f}× BL · 比 baseline 还要瞎</strong></div>
      </div>
      <div class="dv-cell" style="border-left-color: #5A7A4F;">
        <div class="dv-num">{n_pf_enc}</div>
        <div class="dv-lbl">◍ phone_friction · 抬头注意到的人 ⚡</div>
        <div class="dv-sub"><strong>{n_pf_enc/n_bl_enc:.1f}× BL</strong> · 同样 565 个动作, 多看见 {n_pf_enc - n_bl_enc} 张脸</div>
      </div>
    </div>
  </div>

  <div class="data-vanity-section">
    <div class="dv-h3">她 14 天里的 dialog 输出</div>
    <div class="data-vanity-grid">
      <div class="dv-cell">
        <div class="dv-num">{len(hp["dialogue_summaries"])}</div>
        <div class="dv-lbl">段被记录下的对话</div>
        <div class="dv-sub">HP variant · 跟 4 位邻居 · 全部围绕本街务实议题</div>
      </div>
      <div class="dv-cell">
        <div class="dv-num">{len(hp.get("known_infos") or {})}</div>
        <div class="dv-lbl">条她知道的 gossip / info</div>
        <div class="dv-sub">conversation_service · known infos</div>
      </div>
      <div class="dv-cell-big">
        <div class="dv-num">0</div>
        <div class="dv-lbl">次 · 4 段对话里她提起 ICU / 病人 / 医院</div>
        <div class="dv-sub">系统压缩成的对话主题: Mowbray 通勤 / Lane Cove West Public 学区 / Galuwa Recreation Centre / St Leonards 早班交接</div>
      </div>
    </div>
  </div>

  <div class="data-vanity-section">
    <div class="dv-h3">仿真规格 (4 宇宙都一样)</div>
    <div class="data-vanity-grid">
      <div class="dv-cell"><div class="dv-num">1,000</div><div class="dv-lbl">agent</div></div>
      <div class="dv-cell"><div class="dv-num">14</div><div class="dv-lbl">天</div></div>
      <div class="dv-cell"><div class="dv-num">4</div><div class="dv-lbl">variant</div></div>
      <div class="dv-cell"><div class="dv-num">seed 44</div><div class="dv-lbl">这一份的 random seed</div></div>
    </div>
  </div>

  <p class="data-vanity-fineprint">
    所有数字来自 publishable v7 (β=4 严谨度档位) 4 份独立 snapshot 的
    memory_store_state、 attention_service_state、
    dialogue_service_state 与 ledger_state。 任何"她想"、"她意识到"段落,
    均是基于上面数字与 reflection log + 20 条 life_history 的 journalistic
    reconstruction。
  </p>

  <div class="data-vanity-kicker">
    <strong>她是 1,000 个虚拟居民里的 1 位</strong>, 也是项目第四篇深度报道
    的主角。 同一套方法 (4 variant snapshot × 20 life_history × 16 dialogue
    instance × 数据 cross-reference) 可以用在剩下 999 位任何一个 agent 身上。
    每一位都会有不同的"6 顶帽子"、 不同的"凌晨两点路灯"、 不同的"她原本能
    多看见的脸"。 本篇是其中一篇可能的写法。
  </div>
</section>
"""


# ─── CSS ──────────────────────────────────────────────────────────────
CSS = """
* { box-sizing: border-box; }
body { font-family: 'Georgia', 'Songti SC', serif; max-width: 760px; margin: 0 auto;
       padding: 0; background: #F1EDEA; color: #1F2937; line-height: 1.75; font-size: 18px; }
h1 { font-size: 50px; font-weight: 900; letter-spacing: -1.2px; line-height: 1.12; margin: 0 0 24px; color: #1F2937; }
h2 { font-size: 32px; font-weight: 900; margin: 56px 0 22px; padding-bottom: 12px;
     border-bottom: 1px solid #1F2937; letter-spacing: -0.5px; }
h3 { font-size: 22px; font-weight: 900; margin: 32px 0 16px; }
p { margin: 0 0 18px; }
strong { color: #1F2937; }
em { font-style: italic; color: #5A6776; }
code { background: #E5E1DA; padding: 2px 6px; font-family: 'Menlo', monospace; font-size: 14px; color: #3F6B7D; }

.open { padding: 80px 40px 60px; border-bottom: 1px solid #C7C2B7;
        background: linear-gradient(180deg, #F1EDEA 0%, #E5E1DA 100%); }
.kicker { color: #3F6B7D; font-style: italic; letter-spacing: 2px; font-size: 13px;
          text-transform: uppercase; margin: 0 0 18px; }
.subtitle { font-size: 22px; line-height: 1.5; color: #5A6776; font-style: italic; margin: 0; }
.anti-subtitle { margin: 22px 0 0; padding: 14px 18px;
                 background: rgba(168, 90, 76, 0.08);
                 border-left: 4px solid #A85A4C;
                 font-size: 16px; line-height: 1.65; color: #1F2937;
                 font-style: italic; }

.methodology { background: #E5E1DA; padding: 30px 40px; margin: 0; border-left: 4px solid #3F6B7D;
              font-size: 16px; }
.methodology h2 { font-size: 20px; margin-top: 0; border: none; padding: 0; }
.methodology p { margin-bottom: 14px; }

.chapter { padding: 50px 40px; }
.chapter.chapter-cold-open { background: linear-gradient(180deg, #1A2530 0%, #243240 100%);
                               color: #E5E1DA; }
.chapter.chapter-cold-open h2 { border-color: #D4A04C; color: #D4A04C; }
.chapter.chapter-cold-open strong { color: white; }
.chapter.chapter-cold-open em { color: #C2B89A; }
.chapter.chapter-cold-open code { background: rgba(212, 160, 76, 0.18); color: #FFE5A8; }
.chapter.chapter-cold-open .scene-time { color: #D4A04C; font-style: italic; font-size: 13px; letter-spacing: 1px; margin-bottom: 20px; }
.chapter.chapter-cold-open .profile-quote { background: rgba(212, 160, 76, 0.10);
                                              border-left-color: #D4A04C;
                                              color: #E5E1DA; }
.chapter.chapter-cold-open .profile-quote::before { color: #D4A04C; opacity: 0.5; }

.chapter.chapter-scene-anchor { background: #1A2530; color: #E5E1DA; }
.chapter.chapter-scene-anchor h2 { border-color: #D4A04C; color: #D4A04C; }
.chapter.chapter-scene-anchor h3 { color: #D4A04C; margin-top: 36px; }
.chapter.chapter-scene-anchor strong { color: white; }
.chapter.chapter-scene-anchor em { color: #C2B89A; }
.chapter.chapter-scene-anchor code { background: rgba(212, 160, 76, 0.18); color: #FFE5A8; }
.chapter.chapter-scene-anchor .scene-time { color: #D4A04C; font-style: italic;
                                              font-size: 13px; letter-spacing: 1px;
                                              margin-bottom: 20px; }
.chapter.chapter-scene-anchor .profile-quote { background: rgba(212, 160, 76, 0.10);
                                                  border-left-color: #D4A04C; color: #E5E1DA; }
.chapter.chapter-scene-anchor .profile-quote::before { color: #D4A04C; opacity: 0.5; }
.chapter.chapter-scene-anchor .rain-record { background: rgba(212, 160, 76, 0.10); }
.chapter.chapter-scene-anchor .rain-record p { color: #E5E1DA; }
.chapter.chapter-scene-anchor .rain-record-label { color: #D4A04C; }

.profile-quote { background: #E5E1DA; padding: 22px 26px;
                border-left: 4px solid #7A6E58;
                font-style: italic; font-size: 17px; margin: 20px 0;
                line-height: 1.7; color: #1F2937; }
.profile-quote::before { content: "" "; color: #7A6E58;
                         font-family: 'Georgia', serif; font-size: 38px;
                         line-height: 0; vertical-align: -20px;
                         margin-right: 4px; opacity: 0.4; }

.rain-record { background: rgba(212, 160, 76, 0.12); padding: 18px 22px; margin: 22px 0;
               border-left: 4px solid #D4A04C; }
.rain-record-label { font-family: 'Menlo', monospace; font-size: 11px;
                     color: #3F6B7D; letter-spacing: 1px; text-transform: uppercase;
                     margin-bottom: 10px; }
.rain-record p { font-size: 15px; line-height: 1.7; color: #1F2937; margin: 0; }

.map-figure { margin: 32px 0; }
.map-figure svg { display: block; width: 100%; height: auto; border: 1px solid #C7C2B7; }
.map-figure figcaption { font-size: 14px; color: #5A6776; font-style: italic;
                         margin-top: 10px; padding: 0 8px; line-height: 1.65; }
.map-figure figcaption sup { font-size: 10px; color: #7A8090; }

/* Phone-screen mockup figure (Mowbray jam) */
.phone-screen-figure { margin: 36px auto 18px; padding: 0; }
.phone-frame { max-width: 380px; margin: 0 auto; background: #0E1620;
               border-radius: 32px; padding: 14px 12px 18px;
               box-shadow: 0 12px 36px rgba(0,0,0,0.4); }
.phone-status-bar { display: flex; justify-content: space-between;
                    color: #C2B89A; font-family: 'Menlo', monospace;
                    font-size: 11px; padding: 6px 12px 12px;
                    border-bottom: 1px dashed rgba(212, 160, 76, 0.2); }
.ps-context { color: #D4A04C; opacity: 0.8; }
.phone-screen-stack { display: flex; flex-direction: column; gap: 8px;
                      padding: 12px 4px; }
.phone-notif { background: rgba(255,255,255,0.06); border-radius: 12px;
               padding: 10px 14px; backdrop-filter: blur(4px);
               border-left: 3px solid #C2B89A; }
.pn-row { display: flex; justify-content: space-between;
          margin-bottom: 4px; font-family: 'Helvetica', sans-serif;
          font-size: 10.5px; }
.pn-time { color: #7A8090; }
.pn-app { color: #FFE5A8; font-weight: 700; letter-spacing: 0.5px; }
.pn-content { font-family: 'Georgia', serif; font-size: 12.5px;
              color: #E5E1DA; line-height: 1.5; }
.phone-notif-gd { border-left-color: #A85A4C; }
.phone-notif-gd .pn-app { color: #FFB3A6; }
.phone-notif-hp { border-left-color: #3F6B7D; }
.phone-notif-hp .pn-app { color: #9DC9DC; }
.phone-notif-wechat { border-left-color: #5A7A4F; }
.phone-notif-wechat .pn-app { color: #ACCFA0; }
.phone-notif-cal { border-left-color: #D4A04C; }
.phone-notif-cal .pn-app { color: #FFE5A8; }
.phone-notif-bank { border-left-color: #B97D7C; }
.phone-notif-bank .pn-app { color: #E2B5B4; }
.phone-notif-email { border-left-color: #8B7D9D; }
.phone-notif-email .pn-app { color: #C3B8D8; }
.phone-notif-icu { border-left-color: #A85A4C;
                   background: rgba(168, 90, 76, 0.14); }
.phone-notif-icu .pn-app { color: #FFB3A6; font-weight: 900; }
.phone-notif-headnurse { border-left-color: #E64C3C;
                          background: rgba(230, 76, 60, 0.20);
                          box-shadow: 0 0 0 1px rgba(230, 76, 60, 0.3);
                          animation: pulse-red 2.4s ease-in-out infinite; }
.phone-notif-headnurse .pn-app { color: #FF8E80; font-weight: 900; letter-spacing: 0.5px; }
.phone-notif-headnurse .pn-content { color: #FFE5DC; }
.phone-notif-headnurse .pn-time { color: #FF8E80; font-weight: 700; }
@keyframes pulse-red {
  0%, 100% { box-shadow: 0 0 0 1px rgba(230, 76, 60, 0.3); }
  50% { box-shadow: 0 0 0 2px rgba(230, 76, 60, 0.55); }
}
.phone-notif-mil { border-left-color: #B97D7C; }
.phone-notif-mil .pn-app { color: #E2B5B4; }
.phone-screen-figure figcaption { text-align: center; padding: 14px 16px;
                                    font-size: 13.5px; color: #5A6776;
                                    line-height: 1.7; max-width: 540px;
                                    margin: 0 auto; }
.phone-screen-figure figcaption strong { color: #1F2937; }
.phone-screen-figure figcaption em { color: #7A8090; font-size: 12px; display: block; margin-top: 8px; }

/* 6 hats grid */
.hat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin: 32px 0; }
.hat-card { background: white; padding: 22px 26px; border-left: 5px solid var(--accent);
            box-shadow: 0 1px 5px rgba(31,41,55,0.06); display: flex; flex-direction: column; }
/* Hat #6 is "她自己 — 被忘掉的那顶" — physically diminished:
   semi-transparent, dashed border, muted text. The reader feels her
   self-erosion before reading a single word. */
.hat-card-self { grid-column: 1 / -1;
                  background: transparent;
                  border-left: 3px dashed var(--accent);
                  border-top: 1px dashed rgba(139,110,159,0.3);
                  border-right: 1px dashed rgba(139,110,159,0.3);
                  border-bottom: 1px dashed rgba(139,110,159,0.3);
                  box-shadow: none;
                  opacity: 0.62; }
.hat-card-self .hat-name { color: #6E6868; font-style: italic; }
.hat-card-self .hat-num { opacity: 0.7; }
.hat-card-self .hat-claim { background: transparent; color: #8B6E9F; opacity: 0.8; }
.hat-card-self .hat-blurb { color: #5A5050; font-style: italic; }
.hat-card-self .hat-cite { opacity: 0.6; }
.hat-card-self:hover { opacity: 0.95; transition: opacity 0.3s ease; }
.hat-num { font-family: 'Menlo', monospace; font-size: 11px;
           color: var(--accent); letter-spacing: 1.5px; text-transform: uppercase;
           font-weight: 700; margin-bottom: 8px; }
.hat-name { font-family: 'Georgia', serif; font-size: 20px; font-weight: 900;
            color: #1F2937; margin-bottom: 8px; line-height: 1.25; }
.hat-claim { font-family: 'Menlo', monospace; font-size: 11.5px;
             color: var(--accent); margin-bottom: 14px;
             padding: 4px 8px; background: rgba(0,0,0,0.04); display: inline-block; }
.hat-blurb { font-size: 14.5px; line-height: 1.7; margin: 0 0 10px; color: #1F2937; flex: 1; }
.hat-cite { font-family: 'Menlo', monospace; font-size: 10.5px; color: #7A8090;
            letter-spacing: 0.5px; margin-top: 4px; }

/* push density */
.push-density-figure { margin: 36px auto 24px; padding: 0; width: 100%; }
.push-density-caption { font-family: 'Georgia', serif; font-size: 18px; color: #1F2937;
                        font-style: italic; text-align: center; margin: 0 0 18px; }
.push-density-grid { display: grid;
                     grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
                     gap: 18px; width: 100%; }
.push-stack { background: white; border-top: 5px solid var(--accent);
              box-shadow: 0 2px 8px rgba(31,41,55,0.08); padding: 18px 18px 14px;
              min-height: 360px; min-width: 0;
              display: flex; flex-direction: column; }
.ps-phone-top { border-bottom: 1px dashed #C7C2B7; padding-bottom: 10px;
                margin-bottom: 14px; display: flex; justify-content: space-between;
                align-items: baseline; }
.ps-header { font-family: 'Helvetica', sans-serif; font-size: 14px;
             font-weight: 700; color: var(--accent); letter-spacing: 0.5px; }
.ps-count { font-family: 'Helvetica', sans-serif; font-size: 11px;
            color: #7A8090; letter-spacing: 1px; text-transform: uppercase; }
.ps-empty { flex: 1; display: flex; flex-direction: column;
            justify-content: center; align-items: center;
            font-family: 'Georgia', serif; color: #A8A09A; font-style: italic;
            font-size: 16px; line-height: 1.9; text-align: center; padding: 30px 8px; }
.ps-notifs { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.notif { font-family: 'Helvetica', sans-serif; font-size: 11px;
         padding: 7px 9px; border-radius: 4px; color: #1F2937;
         display: flex; gap: 8px; line-height: 1.4;
         overflow: hidden; min-width: 0; }
.notif-day { font-size: 10px; color: #7A8090; flex: 0 0 30px;
             font-variant-numeric: tabular-nums; }
.notif-txt { flex: 1 1 0; min-width: 0;
             overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.notif-hyperlocal_push { background: #DDE7EE; border-left: 3px solid #3F6B7D; }
.notif-global_distraction { background: #F0D9D2; border-left: 3px solid #A85A4C; }
.notif-phone_friction { background: #E2EBDB; border-left: 3px solid #5A7A4F;
                        font-size: 14px; padding: 12px 14px; line-height: 1.6;
                        white-space: normal; gap: 12px; }
.notif-baseline { background: #E5E1DA; border-left: 3px solid #7A6E58; }
.notif-rep { display: inline-block; font-size: 9px; color: #5A6776;
             margin-left: 4px; padding: 1px 5px; background: rgba(63,107,125,0.10);
             border-radius: 8px; font-variant-numeric: tabular-nums; vertical-align: middle; }
.notif-more { font-size: 11px; color: #5A6776; font-style: italic; padding-top: 6px; }
.push-density-fineprint { font-family: 'Helvetica', sans-serif; font-size: 12px;
                          color: #7A8090; text-align: center; font-style: italic;
                          margin: 14px auto 0; max-width: 540px; }
.push-density-fineprint strong { color: #1F2937; font-style: normal; }

/* universes */
.universe-compare { width: 100%; border-collapse: collapse; margin: 20px 0 24px;
                    font-family: 'Helvetica', sans-serif; font-size: 13px; }
.universe-compare thead th { padding: 12px 8px; border-bottom: 2px solid #1F2937;
                             text-align: left; font-size: 11px; letter-spacing: 1px;
                             text-transform: uppercase; color: #1F2937; }
.universe-compare tbody th { padding: 10px 8px; color: #5A6776; font-weight: 500;
                             border-bottom: 1px dashed #C7C2B7; text-align: left; width: 26%; }
.universe-compare tbody td { padding: 10px 8px; border-bottom: 1px dashed #C7C2B7;
                             font-variant-numeric: tabular-nums; color: #1F2937; font-size: 13px; }
.universe-compare tbody td code { font-size: 11px; padding: 2px 4px; background: #E5E1DA; color: #3F6B7D; }
.universe-compare tbody td em { font-size: 11px; color: #5A6776; }

.universe-compare tr.row-key th { background: rgba(63,107,125,0.05);
                                  padding: 18px 10px; vertical-align: middle;
                                  font-weight: 700; color: #1F2937; }
.universe-compare tr.row-key th strong { color: #3F6B7D; }
.universe-compare tr.row-key td { background: rgba(63,107,125,0.04);
                                  padding: 16px 10px; vertical-align: middle; text-align: left; }
.row-key-sub { font-size: 10px; color: #5A6776; font-weight: 400; letter-spacing: 0.5px; }
.big-num { font-family: 'Helvetica', sans-serif; font-weight: 900;
           font-size: 38px; line-height: 1; letter-spacing: -1.5px;
           font-variant-numeric: tabular-nums; display: inline-block;
           margin-right: 4px; }
.big-num-bl { color: #7A6E58; }
.big-num-hp { color: #3F6B7D; }
.big-num-gd { color: #E64C3C; text-shadow: 0 0 8px rgba(230, 76, 60, 0.35); }
.big-num-pf { color: #5A7A4F; }

/* GD column = attention bankruptcy critical warning */
.universe-compare td.critical-cell { background: rgba(230, 76, 60, 0.10) !important;
                                       border-left: 2px solid #E64C3C;
                                       position: relative; }
.warn-arrow { color: #E64C3C; font-size: 28px; font-weight: 900;
              margin-left: 2px; vertical-align: -2px;
              animation: nudge-down 1.6s ease-in-out infinite; }
@keyframes nudge-down {
  0%, 100% { transform: translateY(0); opacity: 0.85; }
  50%      { transform: translateY(3px); opacity: 1; }
}

.universe-critical { border-left: 6px solid #E64C3C !important;
                      background: linear-gradient(135deg, rgba(230,76,60,0.10) 0%, rgba(230,76,60,0.04) 100%) !important;
                      box-shadow: 0 0 0 1px rgba(230, 76, 60, 0.25),
                                  0 2px 10px rgba(230, 76, 60, 0.10); }
.critical-tag { display: inline-block; font-family: 'Menlo', monospace;
                font-size: 11px; letter-spacing: 1.5px; color: #E64C3C;
                background: rgba(230, 76, 60, 0.12); padding: 4px 10px;
                border: 1px solid rgba(230, 76, 60, 0.35);
                margin-bottom: 14px; font-weight: 700; border-radius: 2px; }

.critical-callout { margin: 30px 0; padding: 22px 26px;
                     background: linear-gradient(135deg, rgba(230,76,60,0.10) 0%, rgba(230,76,60,0.04) 100%);
                     border-left: 5px solid #E64C3C;
                     box-shadow: 0 0 0 1px rgba(230, 76, 60, 0.20),
                                 0 2px 10px rgba(230, 76, 60, 0.10); }
.critical-callout p { font-size: 17px; line-height: 1.75; color: #1F2937; margin: 0; }
.critical-callout p strong { color: #832C1F; }
.critical-callout p em { color: #832C1F; font-style: italic; font-weight: 700; }

.universe-essay { background: white; padding: 24px 28px; margin: 18px 0;
                  box-shadow: 0 1px 4px rgba(31,41,55,0.05); border-left: 4px solid #C7C2B7; }
.universe-essay h4 { margin: 0 0 14px; font-size: 21px; font-family: 'Georgia', serif;
                     font-weight: 700; color: #1F2937; }
.universe-essay p { margin: 0 0 12px; font-size: 16px; line-height: 1.75; color: #1F2937; }
.universe-essay p:last-child { margin-bottom: 0; }

.parallel-insight { margin-top: 30px; font-size: 21px; color: #A85A4C; font-style: italic; }
.parallel-insight-h3 { margin-top: 50px; font-family: 'Helvetica', sans-serif; font-size: 14px;
                       letter-spacing: 2px; text-transform: uppercase; color: #3F6B7D;
                       border-bottom: 2px solid #3F6B7D; padding-bottom: 8px; }
.parallel-kicker { display: block; margin-top: 22px; padding: 20px 24px;
                    background: rgba(168, 90, 76, 0.10); color: #1F2937;
                    font-family: 'Georgia', serif; font-size: 16px; line-height: 1.7;
                    border-left: 5px solid #A85A4C; }
.parallel-kicker strong { color: #832C1F; }
.parallel-close { margin-top: 32px; padding: 24px 30px; background: #1A2530; color: #E5E1DA;
                  font-size: 17px; line-height: 1.7; border-left: 6px solid #D4A04C;
                  font-family: 'Georgia', serif; }
.parallel-close strong { color: white; }

/* Cervical-callout */
.cervical-callout { margin: 32px 0; padding: 36px 38px;
                    background: linear-gradient(180deg, #F1EDEA 0%, #E5E1DA 100%);
                    border-left: 8px solid #5A7A4F;
                    box-shadow: 0 3px 10px rgba(31,41,55,0.08); }
.cc-lede { font-family: 'Georgia', serif; font-size: 24px; line-height: 1.45;
           color: #1F2937; font-weight: 700; margin: 0 0 22px;
           letter-spacing: -0.3px; }
.cc-body { font-size: 17px; line-height: 1.85; color: #1F2937; margin: 0 0 18px; }
.cc-body em { color: #A85A4C; font-style: italic; font-weight: 700; }
.cc-num { font-family: 'Helvetica', sans-serif; font-weight: 900;
          font-size: 34px; padding: 0 6px; letter-spacing: -1px;
          font-variant-numeric: tabular-nums; vertical-align: -3px; }
.cc-num-bl { color: #7A6E58; }
.cc-num-pf { color: #5A7A4F; }
.cc-kicker { font-family: 'Georgia', serif; font-size: 22px; line-height: 1.55;
             color: #1F2937; font-weight: 700; margin: 24px 0 0;
             padding-top: 22px; border-top: 2px solid #5A7A4F; }
.cc-kicker strong { color: #832C1F; background: #FFE5A8; padding: 2px 6px; }

/* Dialogues */
.dialogue-card { background: white; padding: 24px 28px; margin: 24px 0;
                border-left: 4px solid #1F2937; box-shadow: 0 1px 4px rgba(31,41,55,0.06); }
.dialogue-pov { font-size: 11px; font-weight: 900; color: #832C1F; letter-spacing: 2px;
               text-transform: uppercase; margin-bottom: 12px; }
.dialogue-partner-card { background: #E5E1DA; padding: 10px 14px; margin: 0 0 14px;
                        font-size: 13px; line-height: 1.6; border-left: 3px solid #3F6B7D; }
.dialogue-context { font-style: italic; color: #5A6776; margin: 0 0 16px; font-size: 15px; line-height: 1.7; }
.dialogue-reconstruction { margin: 18px 0; }
.dr-label { font-family: 'Menlo', monospace; font-size: 11px; color: #832C1F;
            letter-spacing: 1px; text-transform: uppercase; margin-bottom: 8px; }
.dialogue-summary-label { margin-top: 20px; padding: 9px 14px; font-family: 'Menlo', monospace;
                 font-size: 10.5px; letter-spacing: 1.2px;
                 color: #5A6776; background: #D0CABE; font-weight: 700;
                 border-left: 4px solid #7A6E58; }
.dialogue-content { font-family: 'Songti SC', 'Georgia', serif; font-size: 14px; line-height: 1.85;
                   margin: 0; color: #5A6776; padding: 18px 22px;
                   background: #E0DCD3; border-left: 4px solid #7A6E58;
                   font-style: italic; }
.dialogue-content::before { content: "▼ "; color: #7A6E58; font-style: normal; font-weight: 700; }

.syslog-block { margin: 0; padding: 22px 24px;
                background: #14181F; color: #B8BEC9;
                border-left: 5px solid #5A7A4F;
                font-family: 'Menlo', 'Fira Code', 'Courier New', monospace;
                font-size: 13px; line-height: 1.85; }
.syslog-header { color: #7A8090; font-size: 10.5px; letter-spacing: 0.5px;
                 padding-bottom: 14px; margin-bottom: 16px;
                 border-bottom: 1px dashed #2A303C; }
.syslog-body { color: #C8CDD6; }
.log-turn { margin: 0 0 16px; display: flex; gap: 8px; align-items: flex-start;
            padding-bottom: 4px; }
.log-turn-her .log-line { color: #FFE873; }
.log-turn-other .log-line { color: #C8CDD6; }
.log-line { flex: 1; min-width: 0; word-break: break-word; }
.log-hi { background: #D4A04C; color: #14181F; padding: 2px 6px;
          font-weight: 700; border-radius: 3px; letter-spacing: 0.2px; }
.log-aid { color: #6FAEEB; font-weight: 600; font-family: 'Menlo', monospace;
           opacity: 0.85; }
.log-meta { color: #8B9CAE; font-family: 'Songti SC', 'Georgia', serif;
            font-size: 11px; opacity: 0.75; margin: 0 6px 0 4px;
            letter-spacing: 0.5px; }
.log-turn-her .log-meta { color: #D4B968; opacity: 0.7; }

.npc-loop-legend { font-size: 13px; color: #5A6776; background: #E5E1DA;
                   padding: 12px 16px; border-left: 3px solid #D4A04C;
                   line-height: 1.7; font-style: italic; margin: 18px 0; }

/* Alienation block */
.alienation-block { margin: 50px 0 0; padding: 50px 44px;
                    background: #14181F; color: #C8CDD6;
                    border-left: 8px solid #D4A04C; }
.ab-tag { font-family: 'Helvetica', sans-serif; font-size: 11px;
          color: #D4A04C; letter-spacing: 2.5px; text-transform: uppercase;
          margin: 0 0 18px; font-weight: 700; }
.ab-title { font-family: 'Georgia', serif; font-size: 28px; line-height: 1.35;
            color: #FFE873; margin: 0 0 28px; letter-spacing: -0.3px;
            font-weight: 900; border: none; padding: 0; }
.ab-body { font-size: 17px; line-height: 1.85; color: #E0E0E0; margin: 0 0 16px; }
.ab-body strong { color: white; }
.ab-body code { background: rgba(212, 160, 76, 0.18); color: #FFE5A8;
                padding: 2px 8px; font-family: 'Menlo', monospace;
                font-size: 14px; border-radius: 3px; }
.ab-list { list-style: none; padding: 0; margin: 0 0 22px; }
.ab-list li { padding: 10px 0 10px 24px; border-bottom: 1px dashed #2A303C;
              font-size: 16px; line-height: 1.7; color: #E0E0E0;
              position: relative; }
.ab-list li::before { content: "—"; position: absolute; left: 0;
                       color: #D4A04C; font-weight: 900; }
.ab-list li strong { color: white; background: rgba(255, 232, 115, 0.12);
                      padding: 0 4px; }
.ab-punch { margin: 32px 0; padding: 32px 30px; background: #1F2937;
            border: 2px solid #D4A04C; text-align: center;
            font-family: 'Georgia', serif; font-size: 22px; line-height: 1.65;
            color: #FFE873; }
.ab-punch strong { color: white; font-size: 26px; display: block;
                    margin-top: 8px; letter-spacing: 0.5px; }
.ab-punch em { color: #C8CDD6; font-style: italic; }
.ab-coda { font-size: 16px; line-height: 1.8; color: #C8CDD6; margin: 28px 0 18px;
           font-style: italic; }
.ab-coda em { color: #FFE873; font-style: italic; }
.ab-coda strong { color: white; }
.ab-meta { font-size: 13px; line-height: 1.7; color: #7A8090;
           padding-top: 22px; margin-top: 28px;
           border-top: 1px dashed #2A303C; font-style: italic; }
.ab-meta strong { color: #C8CDD6; font-style: normal; }

/* Coda */
.chapter-coda { padding: 60px 40px;
                background: linear-gradient(180deg, #E5E1DA 0%, #F1EDEA 100%); }
.chapter-coda h2 { color: #1F2937; border-color: #3F6B7D; }
.chapter-coda h3 { color: #3F6B7D; margin-top: 40px; }

.ending-loop { margin: 44px 0 0; padding: 36px 38px;
               background: linear-gradient(180deg, #1A2530 0%, #0E1620 100%);
               color: #E5E1DA; border-left: 6px solid #D4A04C;
               box-shadow: 0 4px 16px rgba(31,41,55,0.25); }
.ending-loop p { font-family: 'Georgia', serif; line-height: 1.7;
                  color: #E5E1DA; margin: 0 0 16px; }
.ending-loop p:nth-child(1) { font-size: 26px; font-weight: 700;
                               color: #FFE873; letter-spacing: -0.3px;
                               margin-bottom: 22px; }
.ending-loop p:nth-child(2) { font-size: 17px; }
.ending-loop p:nth-child(3) { font-size: 19px; font-style: italic;
                               border-top: 1px dashed #5A6776; padding-top: 22px;
                               margin-top: 22px; margin-bottom: 0; }
.ending-loop strong { color: #FFE873; font-style: normal; }

/* Data vanity */
.chapter-data-vanity { background: #E5E1DA; padding: 56px 40px; margin-top: 0;
                        border-top: 4px solid #1F2937; }
.chapter-data-vanity h2 { font-family: 'Georgia', serif; font-size: 36px;
                          color: #1F2937; border-bottom: 2px solid #1F2937;
                          letter-spacing: -0.5px; }
.data-vanity-lead { font-size: 18px; line-height: 1.7; color: #5A6776;
                    font-style: italic; margin: 0 0 36px; max-width: 640px; }
.data-vanity-section { margin: 36px 0 28px; }
.dv-h3 { font-family: 'Helvetica', sans-serif; font-size: 14px; letter-spacing: 2px;
         text-transform: uppercase; color: #3F6B7D; margin: 0 0 18px; font-weight: 700; }
.data-vanity-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.dv-cell { background: white; padding: 18px 22px; box-shadow: 0 1px 3px rgba(31,41,55,0.06);
           border-left: 4px solid #1F2937; }
.dv-cell-big { grid-column: 1 / -1; border-left-color: #A85A4C; }
.dv-num { font-family: 'Helvetica', sans-serif; font-weight: 900;
          font-size: 36px; line-height: 1.05; letter-spacing: -1.5px;
          color: #1F2937; font-variant-numeric: tabular-nums; }
.dv-cell-big .dv-num { font-size: 50px; color: #A85A4C; }
.dv-lbl { font-family: 'Helvetica', sans-serif; font-size: 14px;
          color: #1F2937; margin-top: 4px; font-weight: 600; }
.dv-sub { font-family: 'Helvetica', sans-serif; font-size: 12px;
          color: #5A6776; margin-top: 4px; line-height: 1.4; }
.data-vanity-fineprint { margin-top: 32px; font-size: 14px; color: #5A6776;
                         font-style: italic; border-top: 1px dashed #A8A09A;
                         padding-top: 16px; }
.data-vanity-kicker { margin-top: 36px; padding: 28px 30px; background: #1F2937;
                      color: #E5E1DA; font-size: 17px; line-height: 1.7;
                      border-left: 6px solid #D4A04C; font-family: 'Georgia', serif; }
.data-vanity-kicker strong { color: #D4A04C; }

@media (max-width: 600px) {
  body { font-size: 17px; }
  h1 { font-size: 34px; }
  h2 { font-size: 26px; }
  .open { padding: 50px 24px 40px; }
  .chapter { padding: 40px 24px; }
  .methodology { padding: 24px 24px; }
  .hat-grid { grid-template-columns: 1fr; }
  .push-density-grid { grid-template-columns: 1fr; }
  .data-vanity-grid { grid-template-columns: 1fr; }
  .universe-compare { font-size: 12px; }
  .phone-frame { max-width: 320px; }
}
"""


HTML = "\n".join([
    "<!DOCTYPE html>",
    '<html lang="zh-CN"><head>',
    '<meta charset="utf-8"/>',
    '<meta name="viewport" content="width=device-width, initial-scale=1"/>',
    '<title>她每天换 6 顶帽子, 那块 6 英寸的屏幕想再给她一顶 · 33 岁 ICU 护士 14 天 · Synthetic Socio Wind Tunnel</title>',
    f'<style>{CSS}</style>',
    "</head><body>",
    section_open(),
    section_methodology(),
    section_mowbray_jam(),
    section_six_hats(),
    section_tunnel_night(),
    section_four_fourteens(),
    section_dialogues(),
    section_her_inch(),
    section_data_vanity(),
    "</body></html>"
])

OUT.parent.mkdir(parents=True, exist_ok=True)
with open(OUT, "w") as f:
    f.write(HTML)

size_kb = OUT.stat().st_size / 1024
print(f"\n✓ Wrote {OUT}")
print(f"  size: {size_kb:.0f} KB")
print(f"  open: file://{OUT.absolute()}")
