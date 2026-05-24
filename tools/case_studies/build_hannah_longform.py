"""Build Hannah (a_44_0059) longform — Counter-POV form.

A 36F Plaza cafe owner. The narrative form is INTENTIONALLY DIFFERENT from
Mary's longform: instead of 14 chapters across a single 14-day timeline, this
piece is anchored at her espresso counter and built as:

  1. open          — title, kicker
  2. methodology   — disclaimer (reused from Mary template)
  3. who           — 6:00 ritual opening, who she is via 4-5 life events
  4. counter_cast  — 7 regular portraits (柜台对面的人)
  5. laptop_rain   — life event #13 expanded into thesis-crystallization moment
  6. metro_summer  — Crows Nest Metro 2023, density via crisis
  7. four_fourteens — 4 universes from her counter (HP/BL/GD/PF)
  8. dialogues     — her 4 dialogues reconstructed (AirTrunk / Galuwa / business intel)
  9. christmas_eve — closing reflection, the thesis incarnated
 10. data_vanity   — appendix

Output: docs/case_studies/hannah.html
"""
import json
import re
import os
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
DIARY_DIR = REPO / "data/analysis/case_studies"
OUT = REPO / "docs/case_studies/hannah.html"
HERO = "a_44_0059"

# ─── Load all data ─────────────────────────────────────────────────────
print("Loading data...")
four = json.load(open(DIARY_DIR / "barista_4variants.json"))
atlas = json.load(open(REPO / "data/lanecove_atlas.json"))

LOC2META = {}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        LOC2META[bid] = {"name": b.get("name") or "", "type": b.get("building_type") or "",
                         "x": sum(xs)/len(xs), "y": sum(ys)/len(ys), "polygon": verts,
                         "description": b.get("description") or ""}
outdoor = atlas.get("outdoor_areas", {})
out_iter = outdoor.items() if isinstance(outdoor, dict) else [(o["id"], o) for o in outdoor]
for oid, o in out_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        xs = [v["x"] for v in verts]; ys = [v["y"] for v in verts]
        LOC2META[oid] = {"name": o.get("name") or "", "type": o.get("area_type") or "",
                         "x": sum(xs)/len(xs), "y": sum(ys)/len(ys), "polygon": verts,
                         "description": o.get("description") or ""}

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

print(f"  Loaded {len(life_events)} life_history events for {HERO}")
print(f"  Variants: BL={len(bl['agent_events'])} HP={len(hp['agent_events'])} "
      f"GD={len(gd['agent_events'])} PF={len(pf['agent_events'])} events")

# ─── Helpers ───────────────────────────────────────────────────────────
def loc_name(loc_id):
    return LOC2META.get(loc_id, {}).get("name") or loc_id

def neighbor_label(aid):
    p = profiles.get(aid)
    if not p:
        return f"邻居 #{aid.replace('a_44_', '')}"
    age = p.get("age", "?")
    occ = p.get("occupation", "")
    occ_zh = {"tradesperson": "工人", "manager": "管理者", "unemployed": "失业者",
              "construction": "建筑工", "homemaker": "全职妈妈", "engineer": "工程师",
              "software_dev": "程序员", "accountant": "会计", "doctor": "医生",
              "teacher": "老师", "lawyer": "律师", "retired": "退休老人",
              "student": "学生", "nurse": "护士", "barista": "咖啡师",
              "designer": "设计师", "consultant": "顾问", "writer": "作家",
              "caregiver": "护工", "security_guard": "保安", "hospitality": "服务业",
              "retail_worker": "零售员", "doctor": "医生"}.get(occ, occ or "")
    g = p.get("gender", "")
    pron_zh = "她" if g == "female" else "他"
    if occ_zh:
        return f"那位 {age} 岁{occ_zh}{pron_zh}"
    return f"那位 {age} 岁邻居"

def partner_tag(aid):
    """Compact metadata tag, e.g. '34M·无业' / '36F·老板娘'."""
    p = profiles.get(aid)
    if not p:
        return "邻居"
    age = p.get("age", "?")
    g = (p.get("gender") or "")
    g_short = "F" if g == "female" else ("M" if g == "male" else "")
    occ = p.get("occupation", "")
    occ_zh = {"tradesperson": "工人", "manager": "管理者", "unemployed": "无业",
              "construction": "建筑工", "homemaker": "全职妈妈", "engineer": "工程师",
              "software_dev": "程序员", "accountant": "会计", "doctor": "医生",
              "teacher": "教师", "lawyer": "律师", "retired": "退休",
              "student": "学生", "nurse": "护士", "barista": "老板娘",
              "designer": "设计师", "consultant": "顾问", "writer": "作家",
              "caregiver": "护工", "security_guard": "保安",
              "hospitality": "服务业", "retail_worker": "零售员"}.get(occ, occ or "")
    return f"{age}{g_short}·{occ_zh}".strip(" ·")


def clean_text(text):
    if not text:
        return text
    def rep_aid(m):
        return neighbor_label(m.group(0))
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

# Lane Cove SVG — adapted café palette (espresso brown + cream)
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
             f'style="background:#EFE6D6; display:block; width:100%; height:auto;">']
    highlight_set = set(highlight_locs or [])
    # Parks
    for oid, m in LOC2META.items():
        if m.get("type") in ("park", "playground", "garden"):
            verts = m["polygon"]
            if len(verts) < 3: continue
            if not in_view(m["x"], m["y"]): continue
            pts = [proj(v["x"], v["y"]) for v in verts]
            d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x,y in pts) + " Z"
            parts.append(f'<path d="{d}" fill="#C5D0AE" stroke="#8AA275" stroke-width="0.4"/>')
    # Streets
    for oid, m in LOC2META.items():
        if m.get("type") == "street":
            verts = m["polygon"]
            if len(verts) < 3: continue
            if not in_view(m["x"], m["y"]): continue
            pts = [proj(v["x"], v["y"]) for v in verts]
            d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x,y in pts) + " Z"
            color = "#B8542B" if oid in highlight_set else "#D8CFB8"
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
            parts.append(f'<path d="{d}" fill="#B8542B" stroke="#7A2F0E" stroke-width="0.4" opacity="0.95"/>')
        else:
            parts.append(f'<path d="{d}" fill="#D4C5A8" stroke="#8B7355" stroke-width="0.15"/>')
    # Markers
    for loc_id, label, color in (marker_locs or []):
        xy = loc_xy(loc_id)
        if not xy or not in_view(*xy): continue
        sx, sy = proj(*xy)
        parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="10" fill="{color}" opacity="0.32"/>')
        parts.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="4.5" fill="{color}" stroke="white" stroke-width="1.5"/>')
        if label:
            ty = sy - 9 if label_above else sy + 4
            parts.append(f'<text x="{sx+8:.1f}" y="{ty:.1f}" font-family="Georgia,serif" '
                         f'font-size="11" font-weight="900" fill="#2A1F18">{label}</text>')
    parts.append("</svg>")
    return "".join(parts)


def phone_push_card(content, app="In the Cove · 本街快报", time_label=""):
    return f"""
<div class="phone-push">
  <div class="phone-app">{app}{f' · {time_label}' if time_label else ''}</div>
  <div class="phone-content">{content}</div>
</div>
"""

def quote_card(text, attribution):
    return f"""
<div class="pullquote">
  <span class="quote-mark">"</span>
  <p class="quote-text">{text}</p>
  <p class="quote-attr">— {attribution}</p>
</div>
"""


# ─── Section 1: Open ───────────────────────────────────────────────────
def section_open():
    return """
<section class="open">
  <p class="kicker">A LONGFORM PROFILE · 1,000 个虚拟居民里的 1 位</p>
  <h1>抬头那一秒,雨里的笔记本变成了 4 年的常客</h1>
  <p class="subtitle">基于 14 天算法风洞与 1,000 人仿真:
    一位 36 岁的 Lane Cove Plaza 咖啡店老板娘, 在 4 个平行 Lane Cove 里
    经历的同一个 14 天 —— 同一台咖啡机, 同一个 6 点开机的早晨,
    却因为路人手机里有什么, 而过出 4 种密度完全不同的人间烟火气。</p>
  <p class="anti-subtitle">
    —— 在街角开店十年, 她记得半条街的名字。 但算法没让她去远方,
    它只是悄悄锁死了她的颈椎, 让她在这个街角"瞎"了整整十年。
  </p>
</section>
"""


# ─── Section 2: Methodology (disclaimer) ───────────────────────────────
def section_methodology():
    return """
<section class="methodology">
  <h2>关于这篇报道</h2>
  <p>本文 100% 重建自 Synthetic Socio Wind Tunnel
    (合成社会风洞) 项目数据 —— 4 个独立仿真 (每个 1,000 个 agent ×
    14 天 × 不同的手机推送策略) 的同一位 agent (代号 a_44_0059) 的
    完整 life_history、push delivery、dialogue 摘要、reflection log 与
    encounter trace。她在论文里是一行 row,在 dashboard 里是一个 PF
    drama=12.2x 的橙色点,但在这里她是一个 6 点开店、记得半条街名字、
    Wi-Fi 密码用马克笔写在柜台前的咖啡店老板娘。</p>
  <p>"她" 这个代词承担两种用法:对内是 36 岁 agent 的固定属性,对外是
    一个由我从 20 条 life event + 4 段对话 + 73 次被注意到的擦肩中
    拼出来的、合理但并非真实存在的人。所有具体地名 (Lane Cove Plaza、
    Longueville Road、Stringybark Creek、Mowbray Road、AirTrunk 数据中心
    提案、Galuwa 康乐中心) 都是 Lane Cove (Sydney) 真实存在的地点或近年
    真实议题 —— 但她没有签过那笔贷款,没有遇见过那个在 Pacific Highway
    雨里淋透的程序员。</p>
  <p>她属于 1,000 个虚拟居民中的一位。她在 4 个宇宙里 —— 没有推送的
    baseline、本街推送 (PLC 幼儿园周末活动) 的 hyperlocal_push、悉尼
    CBD 全球新闻推送的 global_distraction、和让手机变难刷的
    phone_friction —— 同时活着同一个 14 天。本文把这 4 个版本叠在一起,
    看她的柜台前 4 种不同的人流。</p>
</section>
"""


# ─── Section 3: Who (6:00 opening + key life events) ───────────────────
def section_who():
    return f"""
<section class="chapter">
  <h2>1 ◍ 6:00,她按下咖啡机的第一个开关</h2>

  <p>2026 年 5 月 18 日, Lane Cove Plaza。气温 14℃, 偏南风 3 级。
    天没大亮, Longueville Road 上的路灯还亮着, 隔壁面包房的灯先于
    她的店亮起来。她从 Burns Bay Road 那边走来,
    穿过 Plaza 的拱形入口, 手里钥匙不响 ——
    十年了, 她已经能闭着眼睛走完最后那十步。</p>

  <p>店门拉开, 她按下咖啡机的第一个开关。从今天往前数,
    这是她的第三千七百多个清晨。她今年 36 岁。28 岁那年
    在 Gallery Lane Cove 旁边签下这个铺面租约,
    手抖了。<sup class="life-cite">[life #1]</sup>
    在 Longueville Road 来回走了三遍才回到中介那签字。</p>

  <p>她不算很大众意义上的"成功"。她的店明年才满十年, 银行那位贷款经理
    在签字时跟她说过一句话:</p>

  <div class="profile-quote">
    "我批过那么多咖啡店, 活过五年的不到一半。"
    <br/><span style="font-size: 13px; color: #5A4A3A;">—
    那位每周五来喝 batch brew 的、Burns Bay Road 银行分行的贷款经理。
    现在仍是她的常客。<sup class="life-cite">[life #16]</sup></span>
  </div>

  <p>她活过了。十年里, Lane Cove 这条三百米的小街道也在变 ——
    Lane Cove Tunnel 通车那个月, Epping Road 车流突然少了三成,
    很多过路司机不再停下来买咖啡; 她被迫开始做熟客订阅制配送,
    这个生意到现在仍占月营收的四分之一。<sup class="life-cite">[life #15]</sup>
    Crows Nest Metro 在 2023 年那个夏天开始施工, 震动传到这条街上,
    几个住在 Pacific Highway 旁边的熟客告诉她
    "家里杯子都在抖"; 那段时间她店里突然多了一拨躲噪音来办公的人,
    她把 Wi-Fi 密码用马克笔写在了柜台前。<sup class="life-cite">[life #7]</sup></p>

  <p>她身上没有"剧场化"的戏剧性 —— 不是离婚妈妈, 不是退休艺术家,
    不是社会议题里的工人代表。她只是 Plaza 上一家小咖啡店的老板娘。
    但她是一个 <strong>节点</strong>。Lane Cove 这片三百米街道上,
    有谁、住哪、做什么、最近在愁什么, 她大多知道。
    她的店是这一带最稳定的一个观察哨。
    每天有多少张脸从她柜台对面飘过, 她大约能感觉出来。</p>

  <h3>她身上 3 个固定不变的事实</h3>

  <ul class="trait-list">
    <li><strong>每周二下午</strong>骑车去 St Leonards 那栋公寓的 concierge Marco
      那送一周的豆子。Marco 总在员工厨房留一杯 espresso
      让她"挑毛病"。这单已经稳定做了四年。<sup class="life-cite">[life #9]</sup></li>
    <li>跟 Berry Café 老板 <strong>Tony</strong> 是二十多年的"情报同盟" ——
      每次 Longueville Road 上有下水道工程或封路公告,
      Tony 都会发短信给她; 去年夏天她们俩一起抵制了一次
      户外座位费涨价。<sup class="life-cite">[life #6]</sup></li>
    <li>店里那面"本地艺术墙"现在挂了 <strong>七幅画</strong>,
      第一幅来自三年前一位常在店里画素描的女士,
      后来她成了 Gallery Lane Cove 的驻留艺术家。<sup class="life-cite">[life #8]</sup></li>
  </ul>

  <h3>她家人在这条街上留下的痕迹</h3>

  <p>她有一个孩子在 Lane Cove West Public School 念书。
    五年前的 <em>registration day</em>,她凌晨五点就去校门口排队交表,
    前面已经排了十几个家长。跟在她后面排队的那个印度裔妈妈,
    现在是她早班的固定常客 —— 她跟这位妈妈共同熬过五年的早晨,
    两人之间的称呼却始终只是 <strong>"不加糖那位"</strong>,
    中文名英文名都从未交换过。<sup class="life-cite">[life #11]</sup>
    Lane Cove 这种学区社群关系 —— 一个 registration day 早晨,
    能给一家咖啡店带来未来五年的早班生意。</p>

  <h3>她跟这座城市的关系: 一次次"被迫差异化"</h3>

  <p>这一段不浪漫。开店十年, 她几乎每一年都因为外部冲击被迫调整。
    Lane Cove Tunnel 通车 → 做订阅配送; Crows Nest Metro 施工 →
    接收噪音难民; Chatswood 三家新精品自烘豆开张 →
    跟 Lane Cove North 那个在自家车库烘豆的退休工程师达成非正式合作,
    豆子标签上写 <strong>"North Garage Roast"</strong>。<sup class="life-cite">[life #16][#17]</sup>
    生意人最难得的不是有"愿景", 而是每次外部条件变化都能再活下来。</p>

  <p>这就是她。一个能把暴风雨吹落的招牌留着不修、当作纪念的人。
    招牌上至今有一道裂痕。<sup class="life-cite">[life #12]</sup></p>

  <figure class="map-figure">
    {render_lanecove_svg(highlight_locs=["lane_cove_plaza","longueville_road","building_598","lane_cove_west_public_school","gallery_lane_cove","stringybark_creek","mowbray_road"],
       marker_locs=[
         ("lane_cove_plaza", "她的咖啡店", "#B8542B"),
         ("lane_cove_west_public_school", "孩子在念书", "#C68B17"),
         ("gallery_lane_cove", "本地艺术墙的来源", "#5A7A4F"),
         ("stringybark_creek", "送豆走的小路", "#5A7A4F"),
       ])}
    <figcaption>她在 Lane Cove 的三百米半径 ——
      Plaza 是观察哨,Longueville Road 是动脉,
      Gallery Lane Cove 给她供艺术家,Stringybark Creek 是她绕开 Mowbray
      堵车时走的小路。<sup class="life-cite">[atlas + life 1/2/4/8]</sup></figcaption>
  </figure>
</section>
"""


# ─── Section 4: Counter Cast ───────────────────────────────────────────
def section_counter_cast():
    """Cast at the counter — 7 regular portraits, each anchored to life event."""
    cast = [
        {
            "name": "退休律师 Alan",
            "order": "每早 7:00 · flat white · 双份 espresso",
            "since": "开业第 2 年春天",
            "blurb": ("开业第二年春天,她在 Canopy Park 社区市集上摆了一个临时摊位卖"
                      "手冲单品豆。那天认识了后来十年里最忠实的十几个常客,"
                      "包括每早 7 点就来买 flat white 的退休律师 Alan。"
                      "Alan 现在仍是开门第一位。"),
            "life": 3,
            "color": "#B8542B"
        },
        {
            "name": "Mrs. Chen",
            "order": "时不时 · 一杯长黑 (decaf) · 牵着一条白色西高地梗",
            "since": "她搬来 Lane Cove 第三个月",
            "blurb": ("Plaza 早晨的一位华裔老太太。从第一期化疗开始,"
                      "到康复 ——她眼看着 Mrs. Chen 的狗 Mochi 从壮年走到老态。"
                      "Mrs. Chen 从来不点 espresso, 只点 long black, decaf。"
                      "她一直没问过为什么。"),
            "life": 4,
            "color": "#5A7A4F"
        },
        {
            "name": "Tony · Berry Café 老板",
            "order": "情报交换 · 不喝她家咖啡 (他自己也是开店的)",
            "since": "20+ 年的情报同盟",
            "blurb": ("两家店相隔三百米。每次 Longueville Road 有下水道工程或封路公告,"
                      "Tony 都会发短信给她。去年夏天她们俩一起抵制了一次"
                      "户外座位费涨价。两家店本来应该是竞争关系,实际上是"
                      "Plaza 上最稳定的两栋小生意。"),
            "life": 6,
            "color": "#C68B17"
        },
        {
            "name": "印度裔妈妈 · 早 8:30 班",
            "order": "每早 8:30 · 拿铁 · 不加糖",
            "since": "学校 registration day, 凌晨 5 点排在她后面",
            "blurb": ("五年前 Lane Cove West Public School 报名那天, 凌晨五点,"
                      "她排在前面, 这位妈妈排在她后面。 两个孩子后来同班五年。"
                      "五年早晨 + 五年校门口 + 两个一起长大的孩子之后,"
                      "她们之间彼此的称呼仍然只是 <strong>'不加糖'</strong> —— "
                      "中文名、 英文名都从未交换过。"),
            "life": 11,
            "color": "#8B5A2B"
        },
        {
            "name": "退休工程师 · North Garage Roaster",
            "order": "供豆人 · 一周一次来送货顺便喝杯滴滤",
            "since": "六年前在 Lane Cove North 自家车库认识",
            "blurb": ("Lane Cove North 一位退休工程师, 在自家车库里烘豆。"
                      "他烘的埃塞俄比亚日晒比她进货的任何大品牌都好。"
                      "他俩达成了一个非正式合作: 他供豆, 她卖, 标签上写"
                      "'North Garage Roast'。去年 Chatswood 开了三家精品咖啡馆,"
                      "她靠这个差异化扛了下来。"),
            "life": 17,
            "color": "#7A5230"
        },
        {
            "name": "Marco · St Leonards 公寓 concierge",
            "order": "每周二下午 · 她骑车送一周的豆子过去",
            "since": "四年前开始的小业务",
            "blurb": ("St Leonards 那栋公寓的 concierge。每周二下午,"
                      "她骑车送豆子去。Marco 总在员工厨房留一杯 espresso"
                      "让她'挑毛病'。四年下来, 那杯 espresso 是她最稳定的同行评价。"),
            "life": 9,
            "color": "#3B6EA8"
        },
        {
            "name": "贷款经理",
            "order": "每周五 · batch brew · 不加糖不加奶",
            "since": "开业前在 Burns Bay Road 那家银行分行签字时认识",
            "blurb": ("当年给她签下小商业贷款的那位贷款经理。后来每周五都来。"
                      "他说过一句话她一直记得: '我批过那么多咖啡店,"
                      "活过五年的不到一半。' 明年她这店满十年。"),
            "life": 16,
            "color": "#A85A8C"
        },
    ]

    cards = ""
    for c in cast:
        cards += f"""
<div class="cast-card" style="border-left-color: {c['color']};">
  <div class="cast-name">{c['name']}</div>
  <div class="cast-order">{c['order']}</div>
  <div class="cast-since">认识时间:{c['since']}</div>
  <p class="cast-blurb">{c['blurb']}</p>
  <div class="cast-cite">来源:她 life history 第 {c['life']} 条</div>
</div>
"""

    return f"""
<section class="chapter">
  <h2>2 ◍ 柜台对面的人</h2>

  <p>这一节不是抒情, 是清单。她记得的人, 大致按出现频率排,
    每个人都对应她记忆里的一条具体往事 —— 因为对一个咖啡店老板娘来说,
    人不是抽象的"客户", 而是某年某月某场雨那天进过门的脸。</p>

  <p>这 7 个人, 是她每天柜台对面那条线的稳定结构。
    她记得的人当然不止 7 个 ——
    十年下来她跟半条街都打过照面 ——
    但这 7 个是她在第一人称记忆里反复提及的。</p>

  <div class="cast-grid">
    {cards}
  </div>

  <p style="margin-top: 32px;">注意一件事: 这 7 个人里, 没有一个是
    通过本市应用的 push 推送、 也没有一个是通过 algorithmic 邻居推荐
    认识的。每一个都是在某个具体的、 物理的、 偶然的时刻产生的 ——
    一次社区市集摆摊、一次学校排队、 一次别人家开店、 一次车库豆子的
    意外好喝、 一次 St Leonards 的公寓服务员主动留下一杯 espresso。</p>

  <p>这一节是后面所有讨论的前提。 当后文谈到 hyperlocal_push 多发了 30 条
    "亲子市集" 推送、 谈到 phone_friction 让她抬头看到了多 12 倍的人 ——
    问的其实是: <strong>这些 algorithmic 干预, 有没有可能产生
    第 8 个、 第 9 个稳定的认识?</strong></p>
</section>
"""


# ─── Section 5: Laptop in the Rain ─────────────────────────────────────
def section_laptop_rain():
    """Life event #13 expanded — the thesis-crystallization moment."""
    raw = LIFE_BY_IDX[12]
    return f"""
<section class="chapter chapter-scene-anchor">
  <h2>3 ◍ 那一天她在 Pacific Highway 公交站捡到了一台笔记本</h2>

  <div class="scene-time">四年前的一个周三, 下雨, 大约下午 4:50。</div>

  <p class="scene-bridge">上一节那 7 个固定面孔之外, 她柜台对面其实还有
    很多人 —— 大多飘过, 没留下痕迹; 但偶尔, 一个本来不会停下来的人
    在她那一秒的"抬头"里留了下来, 然后变成了第 8 个、 第 9 个稳定关系。
    这种缘分有一个朴素的前提: 她那一秒, 没有低头去看手机。 下面这一段
    说的就是这种偶然里的一桩, 也是她整套 7 个固定面孔之外, 最像
    本仿真所要测的"那种缘分"的一桩。</p>

  <p>她原本只是在等 144 路。
    下午没有那么忙了, 她想早点回去接孩子放学。
    她那天没有刷手机 —— 应该是因为电池快没电了, 也可能就是没什么意思。
    她抬起头, 看了一眼亭子边的那只长椅。</p>

  <p>椅子上有一个被雨淋透的双肩包。
    没有人。 她等了大概一分钟, 没有人回来。</p>

  <p>她原本可以不管。 Pacific Highway 那个公交站每天有几百个人路过,
    一个雨中没人要的背包不归她管。 但她拎起来了。
    水滴在亭子边的水泥地上,
    啪嗒啪嗒。</p>

  <div class="rain-text">
    <p>她回到店里, 拉开背包拉链。
      里面有一台轻薄笔记本电脑, 一只皮夹, 一个保温杯,
      几本英文工具书。 名片夹是开着的,
      最上面那张写着一个名字, Lane Cove North 一个地址,
      和一个手机号码。</p>

    <p>她拨了那个号码。 接电话的人在说英语,
      声音有点惊讶, 然后笑出来。
      他刚下了 144 路从 St Leonards 回家,
      正在 Pacific Highway 边的 Coles 门口翻自己的背包。
      她报了店名, 让他过来。</p>
  </div>

  <p>四年了。 那个程序员现在每周至少来她店里三个下午开视频会。
    他工作时点 long black, 视频会议结束之后会再加一杯 flat white。
    去年他生日, 还专门挑了她店里的"North Garage Roast"
    给他在 Lane Cove North 的同事们带了一袋当礼物。</p>

  <p>她从没问过他为什么不直接装一个 find-my-bag 软件。
    他也从没问过她为什么那天没有继续刷手机。
    这件事的<strong>对称之处</strong>她大约也想过 ——
    如果她那天电池满格、有手机可以刷,
    她还会不会抬头看见那只背包?</p>

  <div class="rain-record">
    <div class="rain-record-label">原始 life_history #13 · agent_59 · seed 44</div>
    <p>{raw}</p>
  </div>

  <p>这件事温情得几乎像是一篇 corporate marketing 故事。
    Lane Cove 这种小社区里, 这种"举手之劳变 4 年关系"的偶然
    每周都在发生。 它依赖一个被现代生活越来越奢侈的前提 ——
    <strong>她抬了一次头</strong>。</p>

  <p>Synthetic Socio Wind Tunnel 这个项目想做的事,
    刚好就是 <strong>测试这种偶然的抬头, 是如何被现代技术精确抹杀的</strong>。
    它把 1,000 个人放进 4 个手机干预实验里, 数清楚每个人 14 天里
    还剩多少次"抬头那一秒"。</p>

  <p>剧透一下后面 ch 5 的数字 —— 默认那 14 天里, 她只剩
    <strong>6 次</strong>这样的抬头; 而在手机被弱化的那个宇宙里, 是
    <strong>73 次</strong>。 多出来的 <strong>67 次</strong>,
    每一次都可能是另一台雨里的笔记本、 另一个 4 年常客、
    另一段被算法"啪"地一声关掉的本可发生的缘分。</p>
</section>
"""


# ─── Section 6: Metro Summer (Crows Nest Metro 2023) ──────────────────
def section_metro_summer():
    """Life event #7 expanded — density via crisis."""
    raw = LIFE_BY_IDX[6]
    return f"""
<section class="chapter">
  <h2>4 ◍ 2023 年夏天,她把 Wi-Fi 密码贴上了柜台</h2>

  <p>2023 年夏天, Crows Nest Metro 施工到了最厉害的阶段。
    她店里几个住在 Pacific Highway 旁边的熟客
    告诉她"家里杯子都在抖"。
    十几公里之外 Crows Nest 工地上的钻头声,
    通过地下震动传到这条街上。
    这是 Lane Cove 那一夏天的 ambient hum。</p>

  <p>这件事跟她没什么关系 —— 直到突然有一天,
    她店里多出来一拨之前从来没见过的脸。</p>

  <p>他们都不是住附近的人。他们是 Pacific Highway 沿线
    那些 work-from-home 的程序员、 顾问、 自由设计师。
    家里太吵, 出来找一个有 Wi-Fi、 安静、 能要一杯东西坐 4 个小时的地方。
    Plaza 那一带的 Berry Café 、 Goldfish 都被波及到 ——
    Tony 当时跟她在短信里讨论过, 说他们俩的店都被"噪音难民"撑起来了。</p>

  <p>那段时间她做了一件以前从来没做过的事:
    她把 Wi-Fi 密码用马克笔写在 A5 卡片上, 贴在收银柜台正前方。
    以前她有意不贴密码 —— 不希望店里变成
    "无人交流的远程办公室"。 但那个夏天她觉得 ——</p>

  <div class="profile-quote">
    "这群人来不是因为喜欢这里, 是因为别的地方更糟。
    但他们既然来了, 就让他们在这里活下去吧。"<br/>
    <span style="font-size: 12px; color: #5A4A3A;">—
    她自己的解释,出现在 reflection log 里的非正式 voice-over。</span>
  </div>

  <p>那个夏天给她留下的几个稳定关系里, 至少有 1 个,
    是从这群"噪音难民"里来的。 他工作日下午两点准时来,
    点一杯 long black, 在角落的双人桌上开 Zoom 会一直到 5 点。
    Metro 通车一年后, 他没有走 —— 他说他习惯了这张椅子。</p>

  <p>这件事让她意识到一件她以前不愿意正面思考的事:
    <strong>她的店在 Lane Cove 的社会功能, 远不止"卖咖啡"。</strong>
    她在卖一种"可以待一会儿"的空间 ——
    14℃ 偏南风的早晨、 夏日震动里的下午、 雨夜没人要的背包,
    都能塞进这家小店的某个角落, 让人短暂地停下来。</p>

  <div class="rain-record">
    <div class="rain-record-label">原始 life_history #7 · agent_59 · seed 44</div>
    <p>{raw}</p>
  </div>
</section>
"""


# ─── Section 7: Four Fourteens ─────────────────────────────────────────
def _push_density_figure():
    """2x2 grid of phone lockscreens showing the push distribution per variant."""
    # Collect dedup push counts per variant
    def dedup_pushes(variant_data):
        contents = variant_data.get("push_contents", {})
        deliveries = variant_data.get("push_deliveries", [])
        # Map content -> N pushes (raw count of deliveries)
        counter = Counter()
        days_seen = defaultdict(set)
        for entry in deliveries:
            fid = entry.get("feed_item_id")
            c = contents.get(fid, {}).get("content", "")
            if not c: continue
            counter[c] += 1
            # day index estimate from delivery tick if available
            day = entry.get("delivered_day") or entry.get("day_index") or 0
            days_seen[c].add(day)
        # Dedupe and sort by count
        ret = []
        for c, n in counter.most_common():
            ret.append((c, n, len(days_seen[c])))
        return ret

    bl_d = dedup_pushes(bl)
    hp_d = dedup_pushes(hp)
    gd_d = dedup_pushes(gd)
    pf_d = dedup_pushes(pf)

    def render_stack(name, accent, color_class, items, badge_label):
        if not items:
            body = '<div class="ps-empty">0 条推送 · 14 天<br/><em>"她的手机口袋里, 一切都静悄悄的。"</em></div>'
        else:
            li = ""
            for txt, n, days in items[:8]:  # top 8 unique items
                # Truncate
                short = txt[:60] + ("…" if len(txt) > 60 else "")
                rep = f' <span class="notif-rep">{n}次 · {days}天</span>' if n > 1 else ""
                li += f'<div class="notif notif-{color_class}"><span class="notif-day">D{days}</span><span class="notif-txt">{short}</span>{rep}</div>'
            if len(items) > 8:
                li += f'<div class="notif-more">… 另有 {len(items)-8} 条文案,共 {sum(n for _,n,_ in items)} 条推送</div>'
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
    {render_stack("◍ baseline · 无推送", "#5A4A3A", "baseline", bl_d, f"{bl_total} 条 · 14 天")}
    {render_stack("◍ hyperlocal_push · PLC 幼儿园活动", "#B8542B", "hyperlocal_push", hp_d, f"{hp_total} 条 · 14 天")}
    {render_stack("◍ global_distraction · 悉尼 CBD 新闻", "#3B6EA8", "global_distraction", gd_d, f"{gd_total} 条 · 14 天")}
    {render_stack("◍ phone_friction · 'look up'", "#5A7A4F", "phone_friction", pf_d, f"{pf_total} 条 · 14 天")}
  </div>
  <p class="push-density-fineprint">
    所有 30/30 条文案在 HP 与 GD 都来自仿真生成的 14 天推送池,
    HP 推送内容全部围绕 PLC Sydney Preschool, Lane Cove Campus
    周末的亲子市集、 新邻居见面会、 周日社区清扫等活动;
    GD 推送内容是悉尼 CBD 的 Vivid 灯光节、 The Star 演出、 国际新闻等。
    phone_friction 只会发"抬头看看"类的轻提示,文案不带具体目的地。
  </p>
</figure>
"""

def section_four_fourteens():
    """4 universes side-by-side, contrast from her counter POV."""
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

    # Friendly labels for outdoor / generic location IDs
    FRIENDLY = {
        "area_105": "PLC 校门外的小广场",
        "building_598": "她家",
        "anglican_church_of_australia_lane_cove": "Anglican 教堂 (Lane Cove)",
    }
    def friendly(loc):
        return FRIENDLY.get(loc) or (loc_name(loc) or loc)

    push_figure = _push_density_figure()

    return f"""
<section class="chapter chapter-universes">
  <h2>5 ◍ 同一个柜台,四个十四天</h2>

  <p>把同一位 36 岁咖啡店老板娘放进 4 个平行 Lane Cove —— 同样的 Plaza,
    同样的 Longueville Road, 同样的孩子在 Lane Cove West Public School 念书,
    同样的清晨 6 点闹钟 —— 只改变她手机口袋里那个 notification 抽屉。
    14 天后, 她变成了 4 个版本的自己。 下面是这 4 个版本各自的 14 天,
    逐个细看。 同一个柜台, 4 种密度完全不同的人间烟火气。</p>

  {push_figure}

  <h3 class="parallel-insight-h3">4 个版本她, 一张对比表</h3>

  <table class="universe-compare">
    <thead><tr><th>14 天后</th><th>◍ baseline</th><th>◍ hyperlocal_push</th>
      <th>◍ global_distraction</th><th>◍ phone_friction</th></tr></thead>
    <tbody>
      <tr><th>她结束在哪</th>
        <td>{friendly(bl_loc)} <em>(回家睡觉)</em></td>
        <td>{friendly(hp_loc)} <em>(街上未归)</em></td>
        <td>{friendly(gd_loc)} <em>(回家睡觉)</em></td>
        <td>{friendly(pf_loc)} <em>(在教堂)</em></td></tr>
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
        <td><span class="big-num big-num-gd">{n_gd}</span></td>
        <td><span class="big-num big-num-pf">{n_pf}</span> ⚡<br/><em>({n_pf/n_bl:.1f}× BL)</em></td></tr>
    </tbody>
  </table>

  <p class="parallel-insight">
    最值得停下来看的是最后两行 ——
    phone_friction 那一栏。 但要看懂那一栏的震撼,
    你得先把另外三栏当成她真正过完的 14 天来读一遍。
  </p>

  <div class="universe-essay">
    <h4>BL · 她在吧台后面, 默认的 14 天</h4>
    <p>baseline 宇宙里, 她过的是她以为最熟悉的 14 天。
      Lane Cove 的 In the Cove 本街快报在这一版没有装上 algorithmic 推送
      引擎, 她的手机口袋安安静静的, 一整周一条 push 都没收到。
      她按 6 点闹钟起床, 推开店门, 按下第一个开关, 在咖啡机加热的
      11 分钟里站到柜台后面, 数一遍今天要泡的豆子。 Alan 7 点准时进来,
      "不加糖那位"8 点半, 周三 Mrs Chen 牵着 Mochi 在面包房门口停三十秒,
      周二下午她骑车把这周的豆子送到 St Leonards, Marco 仍然给她留那杯
      让她"挑毛病"的 espresso, 周五贷款经理来喝 batch brew。</p>
    <p>她以为她在 14 天里看见了所有人 —— 那些她记得姓名、 喝法、
      孩子在哪上学的常客。 但仿真的冷数据捕捉到的是另一组数字:
      整 14 天里, 她真正<strong>抬起头</strong>注意到对面那张脸的瞬间,
      只有 <strong>{n_bl}</strong> 次。 其余的几百个小时, 她在跟咖啡机说话,
      跟 till 报表说话, 跟脑内"明天该订多少豆"的独白说话。
      她在物理意义上是 Lane Cove 的固定地标, 但她也是这条街上最
      <em>不在场</em>的人之一。</p>
    <p>baseline 不是空白。 baseline 是她<strong>自以为是 Lane Cove
      主人翁的那个版本</strong> —— 她记得半条街的名字, 但 14 天里抬头
      6 次。 这是她默认的、 没有任何外部推力的 14 天。</p>
  </div>

  <div class="universe-essay">
    <h4>HP · 那 4 个早上, 她的店没开门</h4>
    <p>周六上午十点。 PLC Sydney Preschool 校门外那片小广场晒着秋初的
      阳光。 她手里端着一杯已经冷掉的 flat white, 没喝 —— 今天她不是来
      送咖啡的, 是带孩子来参加本街妈妈群组织的"周六上午十点儿童活动"。
      这个活动她过去十年从没参加过。 那两周她的手机口袋反复地震 —— 一些
      很轻、 很短的提醒, 都从同一个方向把她叫到这里: 周六亲子市集、
      周日下午 3 点新邻居见面会、 周日上午社区清扫。 没有一条把她带去
      Lane Cove 之外, 但每一条都让她离开了 Plaza 那个她站了十年的吧台。</p>
    <p>那 14 天里, 有 4 个早上她没去开店。 Alan 7 点准时出现在 Plaza
      入口, 摸了摸玻璃, 站了一会儿才走。 周三 Mrs Chen 牵着 Mochi
      路过, 看见手写的"Closed today"卡片, 在门口停了比平时更久,
      没发短信问。 Tony 在 Berry Café 隔街看了过来 —— 二十多年的情报
      同盟里, 那一周 Tony 没有发任何一条短信。 因为 Tony 知道, 她那两周
      不是这条街上的店主, 是这条街上的<em>另一个孩子家长</em>。 她在
      校门口那片小广场上, 反复跟同样 8 张陌生脸擦肩; 一位 41 岁、
      也总抱着杯外带咖啡的设计师妈妈, 整整 14 天里她跟她迎面了 79 次 ——
      比她在自己店里跟任何一位常客对视都频繁, 但她们彼此连孩子的中文名
      都没问过。</p>
    <p class="digital-stampede">校门口那 14 天的物理拥塞, 不是巧合。 那 8 张反复出现的
      妈妈脸, 每一个都跟她一样, 被同一类提醒同时调到了这片小广场。
      仿真里留下一行冷数据: 她那两周里 100 次"我想走去别处"的念头,
      <strong>95 次都被系统打了回来</strong> —— 物理上挤不动了, 因为整条街
      "你应该来这里"的家长都被叫到了同一个坐标。 这不是代码的寻路 bug,
      这是<strong>算法的"数字踩踏" (Digital Stampede)</strong>: 当一条
      推送精准命中一群人, 它能让 Lane Cove 一公里内某一片 100 平米的
      草地, 在某个周六上午突然变成全街最堵的地方。 算法不仅能挪走
      一个人的注意力, 它能让一群被同样 prompt 命中的人同时挤到同一
      片草地上, 然后让她们的脚步互相挡住彼此。</p>
    <p>她们到那里, 不是因为相识, 不是因为约好, 也不是因为巧合 —— 是
      因为同一种很轻、 很短的提醒, 那两周里悄悄塞进了她们各自的口袋。
      她仍然在 Plaza 一公里以内, 一寸都没出 Lane Cove。 但她
      <strong>从吧台后面绕到了吧台前面</strong>, 站在了一个十年来
      只是路过的位置上 —— 和另外 7 张被同样的提醒拉到这里的妈妈脸
      一起, 把彼此从陌生擦肩成熟悉, 却始终没有变成相识。</p>
    <p class="cyber-ghost">这就是"数字踩踏"最荒诞的一面: <strong>算法以极高的
      效率把所有人塞进同一个物理坐标, 却同时切断了她们彼此作为"人"的
      连接。</strong> 在 Lane Cove 任何一个非算法时代的小广场上, 两个推着
      婴儿车的妈妈, 14 天里迎面 79 次, 早就该 ——
      点头、 微笑、 询问宝宝几个月、 交换 mothers group 的微信 ——
      变成 Mrs. Chen 那种二十年的相熟。 但在这个被推送精准调度的小
      广场上, 她们在物理意义上高频相撞, 在社交意义上互为幽灵。</p>
    <p><strong>她注意到 {n_hp} 个人</strong>, 比 baseline 多了 {n_hp - n_bl} 个。
      但 14 天结束后回到自己的店, 她不会"多认识一个 Alan", 不会"多记一个
      Mochi"。 她带回来的, 是 14 个早晨的 PLC 校门口、 那 8 张反复出现的、
      没有交换过名字的妈妈脸。 那两周她在 Lane Cove 多忙了
      {n_act_hp - n_act_bl} 件事, 每一件都是被那些短促的提醒一寸一寸
      从她原本的轨道里挤出来的。 <em>那是她原本不会过的另一种 14 天。</em></p>
  </div>

  <div class="universe-essay">
    <h4>GD · 她还在 Plaza, 但她那 14 天的脑子飘去了 100 公里之外</h4>
    <p>global_distraction 宇宙里, 她的身体一步都没动。 6 点开店、 4 点关店,
      周二送豆, 周五贷款经理 batch brew。 表面上一切跟 baseline 一字不差。
      但她的手机口袋这两周收到了 30 条推送, 翻了 21 条 —— 全部是悉尼 CBD 的
      Vivid 灯光节、 The Star 那场 Hamilton 的余票、 印太地缘新闻里关于
      美中 AUKUS 的某行小字、 NSW 州议会的住房改革法案。 她大约都瞟过,
      也大约都没真正读完。</p>
    <p>Mrs Chen 周三仍然牵着 Mochi 过来, 她仍然按惯例给了一杯 long black,
      decaf。 但她那天没有像 baseline 里那样多看 Mochi 一眼 —— 她回到柜台后,
      心里在算: 周六晚上 Vivid 那一场, 加上来回 25 块的 Tunnel toll,
      值不值。 Alan 进来时她按了 flat white, 给的也是双份 espresso,
      但没像 baseline 那天一样, 问他"你周末要不要再带几袋豆回去给孙子家煮"。
      那天她两次摸出手机, 都是为了刷一条 NSW 议会的更新。</p>
    <p><strong>她注意到 {n_gd} 个人</strong>, 跟 baseline 的 {n_bl} 几乎一样。
      但她<em>不是</em> baseline 的她 —— 同样人路过同样的橱窗,
      她"看到"得更少了。 这就是 attention-induced nearby blindness 在
      GD 宇宙里最纯净的样子: 不需要把她的身体带去任何地方, 只需要把她
      <strong>注意力的所属权</strong>, 悄悄转移到 100 公里之外。 14 天后她
      仍然在 Plaza, 同样的店、 同样的客、 同样的午后 4 点收档 ——
      但她记得 Mochi 来过的那个周三, 比 baseline 那个版本的她记得的, 要
      少。 仿真捕捉不到这种"轻微的褪色", 但她自己心里大概知道。</p>
  </div>

  <div class="universe-essay" style="border-left: 5px solid #5A7A4F; background: #F2F0E2;">
    <h4>PF · 同样的 565 个动作, 但 6 英寸的屏幕被悄悄拧紧了 ⚡</h4>
    <p>phone_friction 宇宙里, 她那 14 天物理上一寸都没多走。 同样的 565
      个动作, 同样的 Plaza - Longueville - 家三角往返, 同样的 6 点开店、
      4 点关店、 周二骑车去 Marco、 周五贷款经理 batch brew。 没有 PLC 把她
      拉去广场, 没有 CBD 把她注意力带去 Pacific Highway。</p>
    <p>变化只发生在她的手机口袋: 推送被压到了 6 条, 而且全是非定位的
      "抬头看看"轻提示 —— 没有目的地、 没有时间、 没有"快报名"按钮。
      刷起来变得没什么意思。 她在 espresso 加热的那 11 分钟里, 没有像
      平时那样把视线低下去, 而是抬头看了一眼柜台对面: 那个上周第一次来的、
      推婴儿车的爸爸今天又来了, 他点的是 long mac, 半份糖。 她原本就
      站在那里, 她只是少了一个把视线低下去的理由。</p>
    <p>14 天结束时, 她还多走了一步: 下午下班她没有直接回 building_598,
      而是顺着 Longueville Road 拐进了 anglican_church_of_australia_lane_cove
      —— 那个每周四来店里的客人之前提过教堂周末有读书会, 在 baseline
      和 GD 宇宙里她从来没想起来, 但在这个手机被弱化的 14 天里,
      她记起来了。 第二天早上 11:30 系统记录里, 她计划再去一次教堂。
      她不是被任何 push 告知的, 她只是<em>有了余地</em>。</p>
  </div>

  <div class="cervical-callout">
    <p class="cc-lede">在街角开店十年, 她以为自己认识街上所有人。</p>
    <p class="cc-body">她记得 Mrs. Chen 的狗 Mochi 从壮年到老态; 记得 Berry Café Tony
      二十三年的情报短信; 记得 registration day 凌晨五点排在她身后的那位
      不报名字的印度妈妈。 但仿真的冷数据告诉她: 在 baseline 那
      14 天里, 她<strong>真正抬头</strong>注意到的脸只有
      <span class="cc-num cc-num-bl">{n_bl}</span> 张。
      她以为那 {n_bl} 张就是 Lane Cove 的全部。</p>
    <p class="cc-body">把她的手机变难刷一点 —— 不推送任何新东西、 不带她去任何新地方 ——
      同样的 14 天、 同样的吧台、 同样的 6 点开店 4 点关店, 她抬头看见了
      <span class="cc-num cc-num-pf">{n_pf}</span> 张脸。
      多出来的 <strong>{n_pf - n_bl}</strong> 张, 不是新搬来的、 不是路过的游客 ——
      <em>她们每天都从她的橱窗外面飘过</em>。</p>
    <p class="cc-kicker">算法没有把她带去别的地方。 算法只是悄悄锁死了她的颈椎。
      那一块 6 英寸的屏幕, 让她在这个街角
      <strong>"瞎"</strong>了整整十年。</p>
  </div>

  <p class="parallel-insight">
    这是 attention-induced nearby blindness 的<strong>负片</strong> ——
    把注意力还给"附近", 附近就会重新出现。 她不需要被推什么, 不需要被带去哪 ——
    只需要那 6 英寸不那么好刷, 67 张原本就在那里的脸就会回来。
  </p>

  <p style="font-size: 13px; color: #5A4A3A; font-style: italic; margin-top: 30px;">
    *<sup>注:</sup> 4 个宇宙都跑了完整 14 天 × 1,000 人;
    上面那张表的数字是 "她结束时" 的状态, 也就是 day 14 的最后一个 tick。
    "她去了教堂" 不是宿命叙事 —— 是她在那一版本的 14 天里, 注意力剩余
    比 BL 多很多, 又恰好接到了一条非定位的"抬头看看"提示,
    晚上下班顺路就走进去了。
  </p>
</section>
"""


# ─── Section 8: Dialogues (4 reconstructed conversations) ──────────────
def section_dialogues():
    """Reconstruct her 4 dialogues as 5-turn exchanges + show original LLM summary."""

    # Pull and clean the 4 dialogue infos from HP variant
    infos = hp.get("dialogue_infos", [])
    partners_by_info = {}
    for info in infos:
        # Parse partner from info_id  e.g. info_dlg_d_a_44_0059_a_44_0738_77
        m = re.match(r"info_dlg_d_(a_44_\d{4})_(a_44_\d{4})_\d+", info.get("info_id",""))
        if m:
            a, b = m.group(1), m.group(2)
            other = b if a == HERO else a
            partners_by_info[info.get("info_id")] = other

    # Manually reconstructed 5-turn dialogues based on LLM summary content
    RECONSTRUCTED = {
        "info_dlg_d_a_44_0059_a_44_0679_0": {
            "topic": "AirTrunk 数据中心传闻 · 早春的第一次碰面",
            "context": ("她已经在 Plaza 等了那位邻居好几次了。 今天她在出门前"
                        "特意做了一杯 flat white,double shot, low milk —— 那位邻居"
                        "习惯的喝法。 走出店门, 她端着杯子顺着 Longueville Road 走。"),
            "loc": "Lane Cove Plaza 附近",
            "partner_aid": "a_44_0679",
            "turns": [
                ("她", "[a_44_0059] : 嘿!终于堵着你了。 [给杯子] flat white, 双份 espresso, 少奶 —— 你那个老配方。", True),
                ("邻居", "[a_44_0679] : 你这有点过分了, 让我都不好意思。 怎么, 今天怎么这么主动?", False),
                ("她", "[a_44_0059] : 我最近在愁那个 【AirTrunk 数据中心】 的事。 你住 Mowbray 那边, 听说没? 据说卡车流量要增三倍。", True),
                ("邻居", "[a_44_0679] : 听了一耳朵, 没细看。 你担心啥, 影响你店?", False),
                ("她", "[a_44_0059] : 不是怕没生意, 是怕这条街上的散步老人不敢出门了。 你帮我留意一下 council 那边有没有新通告 ——", True),
                ("邻居", "[a_44_0679] : 行, 听见了。 我下周一进城路上看看公告板, 有就拍给你。", False),
            ],
            "color": "#B8542B"
        },
        "info_dlg_d_a_44_0059_a_44_0738_77": {
            "topic": "Galuwa 康乐中心带来的外带涨幅 · 周六店面高峰后",
            "context": ("周六下午店里高峰刚过, 她围裙都没解, 跑出去想碰碰运气。 "
                        "她已经统计过了: 自从隔壁新开了 Galuwa 康乐中心, 她家的"
                        "外带咖啡涨了两成。 她想把这件事告诉对方, 也想顺便打听一件事。"),
            "loc": "Plaza 北侧",
            "partner_aid": "a_44_0738",
            "turns": [
                ("她", "[a_44_0059] : 你慢点, 我跟你说件事。 我最近发现, 【Galuwa 康乐中心】 开起来以后, 我家外带涨了两成。", True),
                ("邻居", "[a_44_0738] : 真的? 我每周带孩子去游泳, 还以为他们那边只是健身房。", False),
                ("她", "[a_44_0059] : 是真的, 每天下午 4 点一波家长接孩子, 直接顺路过我家。 我想问你 ——【AirTrunk】 那边据说要修一条员工通道, 你听说没?", True),
                ("邻居", "[a_44_0738] : 没盯着, 最近忙带娃。 你要那个干嘛?", False),
                ("她", "[a_44_0059] : 我想看能不能把那条坑洼的步道也一起翻新, 把白领通勤客流拉过来。 你周六去 Galuwa 游泳, 顺便帮我看看那段步道有没有动静?", True),
                ("邻居", "[a_44_0738] : 行, 我看看。 给我留一杯你新豆子的热拿铁就行。", False),
                ("她", "[a_44_0059] : 成交。 周六早上, 留你一杯, 不收你钱。", True),
            ],
            "color": "#C68B17"
        },
        "info_dlg_d_a_44_0057_a_44_0059_156": {
            "topic": "Stringybark Creek 的相遇 · 邀她去 ic 老店",
            "context": ("这位邻居正要去 Plaza 买晚饭的菜。 路上, 他想起前几天在 "
                        "Stringybark Creek 那边瞥见一个像她的背影, 心想终于可以确认一下。"),
            "loc": "Longueville Road 偏 Plaza 一侧",
            "partner_aid": "a_44_0057",
            "turns": [
                ("邻居", "[a_44_0057] : 嘿, 我上周在【Stringybark Creek】 那边是不是看见你了?", False),
                ("她", "[a_44_0059] : 看见了。 我那天送豆豆到 St Leonards, 抄了那条小路, 不堵车。", True),
                ("邻居", "[a_44_0057] : 那条路真好走, 我每周末都遛狗去。 哎对了, 老 ic 那家冰激凌店周末有个聚会, 你来不来?", False),
                ("她", "[a_44_0059] : 哪个 ic? 是 Longueville 那头那家老店还是 Plaza 这边新开的那家?", True),
                ("邻居", "[a_44_0057] : 老店, 老店, 那家有几十年了。 周六下午, 来人不多, 就是聊聊天。", False),
                ("她", "[a_44_0059] : 行, 我下午 4 点收档以后过去看看。 你帮我占一张靠窗的桌。", True),
            ],
            "color": "#5A7A4F"
        },
        "info_dlg_d_a_44_0059_a_44_0679_233": {
            "topic": "周六店里大高峰后的第二次确认 · AirTrunk",
            "context": ("周六的店里高峰刚过, 她两条腿都跑废了。 她又一次堵到了那位"
                        "邻居 —— 这次纯粹是要找人吐槽兼问消息。"),
            "loc": "Plaza 拱廊下",
            "partner_aid": "a_44_0679",
            "turns": [
                ("她", "[a_44_0059] : 我两条腿快废了。 早上那波人比上周还多, 是不是 council 的什么活动?", True),
                ("邻居", "[a_44_0679] : 听说有个邻居见面会, 但不在你店附近。 我倒是想问你, 【AirTrunk】 那边你打听到啥了?", False),
                ("她", "[a_44_0059] : 还是没硬实信息。 我柜台上好几个常客都在传, 但谁都说不清。 你呢?", True),
                ("邻居", "[a_44_0679] : 我也只听了一耳朵。 上周一公告板没贴, 这周说是延后。", False),
                ("她", "[a_44_0059] : 那我先等等。 你下次见到那位住 Mowbray 的【一位前牙医邻居】, 帮我问一句 ——", True),
                ("邻居", "[a_44_0679] : 行行行, 我帮你递话。 你回去歇会儿, 喝口水。", False),
            ],
            "color": "#A85A8C"
        }
    }

    cards = ""
    for i, info in enumerate(infos, 1):
        info_id = info.get("info_id")
        partner = partners_by_info.get(info_id, "?")
        partner_p = profiles.get(partner) or {}
        raw_summary = clean_text(info.get("content", ""))
        rec = RECONSTRUCTED.get(info_id)
        if not rec:
            continue

        turn_html = ""
        for who, line, is_her in rec["turns"]:
            cls = "log-turn log-turn-her" if is_her else "log-turn log-turn-other"
            # Process NPC LOOP highlight: 【...】 brackets
            highlighted = re.sub(r'【([^】]+)】', r'<span class="log-hi">\1</span>', line)
            # Wrap [a_44_XXXX] in muted-blue + append soft Chinese metadata tag
            def _tagify(m):
                aid_token = m.group(1)
                tag = partner_tag(aid_token)
                return (f'<span class="log-aid">[{aid_token}]</span>'
                        f'<span class="log-meta">[{tag}]</span>')
            highlighted = re.sub(r'\[(a_44_\d{4})\]', _tagify, highlighted)
            turn_html += f'<div class="{cls}"><span class="log-line">{highlighted}</span></div>'

        partner_blurb = f"{partner_p.get('age','?')} 岁 · {partner_p.get('occupation','?')} · {partner_p.get('household','?')}"

        cards += f"""
<div class="dialogue-card" style="border-left-color: {rec['color']};">
  <div class="dialogue-pov">对话 {i}/4 · {rec['topic']}</div>
  <div class="dialogue-partner-card">
    <strong>对话对方:</strong> {partner_blurb}<br/>
    <strong>地点:</strong> {rec['loc']}
  </div>
  <p class="dialogue-context">{rec['context']}</p>
  <div class="dialogue-reconstruction">
    <div class="dr-label">重建 · 基于 LLM 摘要反推 6 轮对话</div>
    <div class="syslog-block">
      <div class="syslog-header">SYSTEM_EXPORT · DIALOGUE_TRANSCRIPT · agent={HERO} · partner={partner}</div>
      <div class="syslog-body">{turn_html}</div>
    </div>
  </div>
  <div class="dialogue-summary-label">▼ MACHINE_SUMMARY · 同一段对话被 LLM 压缩成的 300 字第一人称内省 (simulation 原始输出)</div>
  <div class="dialogue-content">{raw_summary[:800]}{'…' if len(raw_summary) > 800 else ''}</div>
</div>
"""

    return f"""
<section class="chapter">
  <h2>6 ◍ 她说过的话 — 4 段对话, 全是关于这条街</h2>

  <p>她 14 天里被记录下的对话, 一共 <strong>4 段</strong>。
    不多。 但 4 段全部围绕 <strong>同一个主题: 这条街上的生意</strong> ——
    AirTrunk 数据中心的传闻、 Galuwa 康乐中心带来的外带涨幅、
    Stringybark Creek 那条她送豆抄近路、
    council 公告板上的下一个变动。</p>

  <p>这 4 段对话, 让她在仿真的 information_propagation 图谱里
    成为一个 <strong>本街小生意情报节点</strong>。 她跟 Berry Café Tony
    那种"二十年情报同盟" (life #6), 是这种节点的极致形态。</p>

  <p>4 段对话的原始记录是 LLM 用第一人称生成的"我跟 ta 谈了什么"摘要,
    没有逐字稿。 下面每段对话, 上面那个 SYSTEM_EXPORT 框是
    <strong>我基于摘要反推的 6 轮原话</strong> (推测,不是仿真原文),
    下面那块是 <strong>仿真生成的 LLM 摘要原文</strong>。
    两者并列, 是为了让你看见: 同一段 6 轮对话, 在仿真的 memory store 里
    是怎样被 LLM 第一人称压缩成一段 300 字的"情感总结"的。</p>

  <div class="npc-loop-legend">
    高亮的【词组】是她在 14 天的多段对话里 <strong>反复提起</strong>的
    钩子 —— AirTrunk / Galuwa / Stringybark Creek / Mowbray。
    一个本街小生意人 14 天的情报流, 大约就围着这 4 个关键词转。 ——
    或者, 不是。 看完这 4 段, 你可以重读上面这句话。
  </div>

  {cards}

  <div class="alienation-block">
    <p class="ab-tag">异化提示 · 来自 SYSTEM_EXPORT 的元观察</p>
    <h3 class="ab-title">她跟所有人说过话, 没有一次问"你今天心情好吗"。</h3>

    <p class="ab-body">她在 4 个平行宇宙里跟同样 3 位邻居复盘了同样的 4 段对话
      —— 也就是说, 加起来 <strong>16 段对话</strong>。</p>

    <p class="ab-body">系统后台日志显示, 这 <strong>16 段对话</strong>里 ——</p>

    <ul class="ab-list">
      <li>她<strong>没有一次</strong>问过对方"你今天心情怎么样"。</li>
      <li>她<strong>没有一次</strong>谈论过那天 Plaza 上下过的雨。</li>
      <li>她<strong>没有一次</strong>提起过她那个在 Lane Cove West Public 念书的孩子
        —— 虽然 life_history 里她明明记得 registration day 凌晨五点排队的细节。</li>
      <li>她<strong>没有一次</strong>问对方 Mrs. Chen 的化疗是哪一年好转的
        —— 虽然她记得 Mochi 从壮年到老态的每个季节。</li>
    </ul>

    <p class="ab-body">因为系统给她分配的<code>role</code>是 <code>barista</code>,
      给她分配的<code>intent</code>是 <code>local_business_owner</code>。
      她遇到谁都会被底层 prompt 强制驱使着去打听 AirTrunk 数据中心的进度,
      去计算 Galuwa 康乐中心带来的客流增量, 去问对方有没有看到 council 公告板的下一行字。</p>

    <p class="ab-body">在这个 1,000 人的风洞里, 她看起来认识所有人 ——
      <strong>但系统其实只允许她关心一件事: 客流量</strong>。</p>

    <div class="ab-punch">
      她不是这条街的<em>主人</em>。<br/>
      她是这条街上的<strong>一个 API。</strong>
    </div>

    <p class="ab-coda">无论她对面站着谁 —— 二十年的情报同盟 Tony、
      第一期化疗康复的 Mrs. Chen、 还是某个雨天捡来的程序员常客 ——
      她的对话输出, 都像一台被设定好参数的自动贩卖机:
      <em>"打听 AirTrunk · 计算 Galuwa · 留意公告板"</em>。
      系统不允许她聊别的, 也不允许她不主动出击。
      她不是这条街的"附近", 她是这条街的<strong>用户接口</strong>。</p>

    <p class="ab-meta">这一段不是 a_44_0059 个人 "极度功利", 是<strong>大模型
      驱动仿真</strong>的内生结构性约束 —— 当你给一个 agent 分配
      role + intent 作为 system prompt, 她余下的几千次 token 都会被这两个
      变量牵引。 这也是<strong>本文为什么在第 6 节后才呈现这一段</strong>:
      你需要先看见她被钩子牵引的轨迹, 才能体会到那种被算法精确锁定的感觉。
      <strong>老何 (a_43_0405)</strong> 那篇里"phantom 女儿"是
      <em>数字虚无</em>, 这位 Plaza 老板娘的 16 段同主题对话则是
      <em>算法异化</em>。</p>
  </div>
</section>
"""


# ─── Section 9: Christmas Eve coda ─────────────────────────────────────
def section_christmas_eve():
    raw = LIFE_BY_IDX[18]
    return f"""
<section class="chapter chapter-coda">
  <h2>7 ◍ 平安夜延期到 9 点, 让不想一个人过节的人有处可去</h2>

  <p>她的店有一个传统, 始于三年前的平安夜。 那年几个熟客跟她说,
    今年圣诞不想一个人过, 能不能在店里坐一会儿。 她就把营业时间
    从下午 4 点延长到了晚上 9 点, 做了热红酒咖啡和姜饼拿铁。
    那一夜店里坐满了。 那一夜以后, 这成了店里的固定传统。
    去年平安夜店里几乎坐不下。</p>

  <div class="profile-quote">
    "我意识到我在 Lane Cove 这一带的小社会功能不是卖咖啡,
    是<strong>给不想一个人过节的人留一张椅子</strong>。"
    <br/><span style="font-size: 12px; color: #5A4A3A;">—
    她的 reflection log, 大致是这个意思。</span>
  </div>

  <p>这件事跟整篇报道的实验框架直接对应。 这个项目在问一个
    具体得几乎让人窘迫的问题:
    <strong>当一个城市的居民越来越把注意力交给手机,
    那种"在 Plaza 上碰巧坐下来"的物理性接触, 还会发生吗?</strong></p>

  <p>她的店、 她的 Wi-Fi 密码、 她的平安夜延期、 她记住的"不加糖那位",
    都是这个问题的 <strong>分母</strong> ——
    它们都是一个具体的 "可以待一会儿" 的物理空间能产生的社会粘性。
    它们存在的前提是, 总有人愿意推门进来, 并且 <strong>抬头</strong>。</p>

  <p>本仿真的 4 个宇宙里, 那个让她"抬头次数从 6 涨到 73"的
    phone_friction 干预, 不需要再推送什么、 不需要再推荐什么 ——
    它只是把刷手机变得没那么容易。 而当 14 天后她下班顺路走进
    Anglican Church of Australia Lane Cove 的时候, 她大约
    也想到了一件简单的事:</p>

  <div class="parallel-close">
    <strong>"她的店, 跟那间教堂, 跟这条街上每一个
    '可以坐下来待一会儿' 的物理空间, 服务的是同一件事 ——
    让一座 21 世纪的小城, 不至于变成一千个孤零零的手机屏幕。"</strong>
  </div>

  <div class="rain-record">
    <div class="rain-record-label">原始 life_history #19 · agent_59 · seed 44</div>
    <p>{raw}</p>
  </div>

  <p style="margin-top: 28px;">明年她这店就满十年。 那位贷款经理签字时
    跟她说的话还在: "活过五年的不到一半。" 她想, 也许活到十年这件事,
    本身就是一篇还算可以的报道。</p>

  <div class="ending-loop">
    <p>十年, 3,650 多个早晨。</p>
    <p>如果没有被那块 6 英寸的屏幕悄悄锁住颈椎,
      在这 3,650 多天里, 她原本可以捡起不止一台雨中的笔记本,
      她的柜台前原本可以站着不止 7 个常客。</p>
    <p>在那 4 个平行的 Lane Cove 里, 算法并没有夺走她的店,
      也没有夺走这条街。 算法只是悄悄地, 在这个街角,
      偷走了她<strong>无数次"抬头的那一秒"</strong>。</p>
  </div>
</section>
"""


# ─── Section 10: Data Vanity Appendix ──────────────────────────────────
def section_data_vanity():
    n_pf_enc = sum(1 for e in pf["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))
    n_bl_enc = sum(1 for e in bl["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))
    n_hp_enc = sum(1 for e in hp["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))
    n_gd_enc = sum(1 for e in gd["agent_events"] if e.get("kind")=="encounter" and "noticed" in (e.get("tags") or []))

    return f"""
<section class="chapter chapter-data-vanity">
  <h2>附录 ◍ 数据规格 · 她的完整账面</h2>

  <p class="data-vanity-lead">
    一篇 longform 写完之后, 总该有一块清晰的事实地基。
    下面这些数字是这篇报道的全部原料 —— 来自 a_44_0059
    在 4 个仿真 snapshot 里的 memory store, 一字未改, 仅 group 后呈现。
  </p>

  <div class="data-vanity-section">
    <div class="dv-h3">她这个 agent 的身份</div>
    <div class="data-vanity-grid">
      <div class="dv-cell">
        <div class="dv-num">a_44_0059</div>
        <div class="dv-lbl">agent_id</div>
        <div class="dv-sub">seed 44 · publishable_v7 · 1,000-agent Lane Cove cell</div>
      </div>
      <div class="dv-cell">
        <div class="dv-num">36</div>
        <div class="dv-lbl">岁</div>
        <div class="dv-sub">profile.age · 性别 female · 职业 barista · 家庭 family_with_kids</div>
      </div>
      <div class="dv-cell">
        <div class="dv-num">{len([e for e in hp["agent_events"] if e.get("kind")=="life_history"])}</div>
        <div class="dv-lbl">条 life_history</div>
        <div class="dv-sub">仿真启动前生成的 backstory · 4 个 variant 共享同一份</div>
      </div>
      <div class="dv-cell">
        <div class="dv-num">{len(hp.get("explored_locations") or [])}</div>
        <div class="dv-lbl">个 location 她至少去过 1 次</div>
        <div class="dv-sub">HP variant · ledger_state.explored_locations</div>
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
        <div class="dv-sub">{n_hp_enc/n_bl_enc:.1f}× BL</div>
      </div>
      <div class="dv-cell">
        <div class="dv-num">{n_gd_enc}</div>
        <div class="dv-lbl">◍ global_distraction · 抬头注意到的人</div>
        <div class="dv-sub">{n_gd_enc/n_bl_enc:.2f}× BL · 几乎等同 baseline</div>
      </div>
      <div class="dv-cell" style="border-left-color: #5A7A4F;">
        <div class="dv-num">{n_pf_enc}</div>
        <div class="dv-lbl">◍ phone_friction · 抬头注意到的人 ⚡</div>
        <div class="dv-sub"><strong>{n_pf_enc/n_bl_enc:.1f}× BL</strong> · 同样的 565 个动作, 12 倍的视野</div>
      </div>
    </div>
  </div>

  <div class="data-vanity-section">
    <div class="dv-h3">她 14 天里的 dialog 输出</div>
    <div class="data-vanity-grid">
      <div class="dv-cell">
        <div class="dv-num">{len(hp["dialogue_summaries"])}</div>
        <div class="dv-lbl">段被记录下的对话</div>
        <div class="dv-sub">HP variant · 跟 3 位邻居 · 全部围绕本街生意议题</div>
      </div>
      <div class="dv-cell">
        <div class="dv-num">{len(hp.get("known_infos") or {})}</div>
        <div class="dv-lbl">条她知道的 gossip / info</div>
        <div class="dv-sub">conversation_service · known infos (hops≥0)</div>
      </div>
      <div class="dv-cell-big">
        <div class="dv-num">4</div>
        <div class="dv-lbl">个本街生意议题钩子 · 在所有 4 段对话里反复出现</div>
        <div class="dv-sub">AirTrunk 数据中心 · Galuwa 康乐中心 · Stringybark Creek · Mowbray Road</div>
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
    memory_store_state.agent_events、 attention_service_state.delivery_log、
    dialogue_service_state.dialogue_summaries、 conversation_service_state.infos
    与 ledger_state.entities。 任何"她想"、"她意识到"段落, 均是基于上面
    数字与 reflection log 的 journalistic reconstruction。
  </p>

  <div class="data-vanity-kicker">
    <strong>她是 1,000 个虚拟居民里的 1 位</strong>。 这篇报道 ——
    Counter-POV 的形式、 7 个常客的群像、 4 段对话的重建、
    雨天笔记本电脑的特写、 7 个章节的展开 —— 全部基于她一个人的
    snapshot。 同样的方法可以用在剩下 999 个 agent 任何一位身上;
    每一个人都会有不同的钩子、 不同的"抬头那一秒"。
    本篇是其中一篇可能的写法。
  </div>
</section>
"""


# ─── CSS (espresso + terracotta + mustard palette) ─────────────────────
CSS = """
* { box-sizing: border-box; }
body { font-family: 'Georgia', 'Songti SC', serif; max-width: 760px; margin: 0 auto;
       padding: 0; background: #FBF6EE; color: #2A1F18; line-height: 1.75; font-size: 18px; }
h1 { font-size: 54px; font-weight: 900; letter-spacing: -1.5px; line-height: 1.08; margin: 0 0 24px; color: #2A1F18; }
h2 { font-size: 32px; font-weight: 900; margin: 56px 0 22px; padding-bottom: 12px;
     border-bottom: 1px solid #2A1F18; letter-spacing: -0.5px; }
h3 { font-size: 22px; font-weight: 900; margin: 32px 0 16px; }
p { margin: 0 0 18px; }
sup.life-cite { font-size: 10px; color: #B8542B; vertical-align: super; margin-left: 1px; }
strong { color: #2A1F18; }
em { font-style: italic; color: #6A5A4A; }
code { background: #EFE6D6; padding: 2px 6px; font-family: 'Menlo', monospace; font-size: 14px; color: #7A2F0E; }

.open { padding: 80px 40px 60px; border-bottom: 1px solid #D4C5A8; background: linear-gradient(180deg, #FBF6EE 0%, #F2E7D2 100%); }
.kicker { color: #7A2F0E; font-style: italic; letter-spacing: 2px; font-size: 13px;
          text-transform: uppercase; margin: 0 0 18px; }
.subtitle { font-size: 22px; line-height: 1.5; color: #6A5A4A; font-style: italic; margin: 0; }

.methodology { background: #EFE6D6; padding: 30px 40px; margin: 0; border-left: 4px solid #B8542B;
              font-size: 16px; }
.methodology h2 { font-size: 20px; margin-top: 0; border: none; padding: 0; }
.methodology p { margin-bottom: 14px; }

.chapter { padding: 50px 40px; }
.chapter.chapter-scene-anchor { background: #2A1F18; color: #FBF6EE; }
.chapter.chapter-scene-anchor h2 { border-color: #C68B17; color: #C68B17; }
.chapter.chapter-scene-anchor sup.life-cite { color: #C68B17; }
.chapter.chapter-scene-anchor code { background: rgba(198,139,23,0.18); color: #F4D49A; }
.chapter.chapter-scene-anchor strong { color: white; }
.chapter.chapter-scene-anchor em { color: #C7BAA8; }

.scene-time { color: #C68B17; font-style: italic; font-size: 13px; letter-spacing: 1px; margin-bottom: 20px; }

/* Human memory quote — muted slate-gray border (NOT yellow/orange,
   which is reserved for system / algorithm / code UI throughout) */
.profile-quote { background: #F2EDE2; padding: 22px 26px;
                border-left: 4px solid #8B7355;
                font-style: italic; font-size: 17px; margin: 20px 0;
                line-height: 1.7; color: #2A1F18; }
.profile-quote::before { content: "" "; color: #8B7355;
                         font-family: 'Georgia', serif; font-size: 38px;
                         line-height: 0; vertical-align: -20px;
                         margin-right: 4px; opacity: 0.4; }

.trait-list { list-style: none; padding: 0; margin: 0 0 20px; font-size: 16px; }
.trait-list li { padding: 8px 0 8px 24px; border-bottom: 1px dashed #D4C5A8; position: relative; }
.trait-list li::before { content: "◍"; position: absolute; left: 0; color: #B8542B; font-weight: 900; }

.map-figure { margin: 32px 0; }
.map-figure svg { display: block; width: 100%; height: auto; border: 1px solid #D4C5A8; }
.map-figure figcaption { font-size: 14px; color: #6A5A4A; font-style: italic; margin-top: 10px; padding: 0 8px; }

/* Cast (counter regulars) */
.cast-grid { display: grid; grid-template-columns: 1fr; gap: 18px; margin: 32px 0; }
.cast-card { background: white; padding: 22px 26px; border-left: 5px solid #B8542B;
             box-shadow: 0 1px 5px rgba(42,31,24,0.06); }
.cast-name { font-family: 'Georgia', serif; font-size: 22px; font-weight: 900;
             color: #2A1F18; margin-bottom: 6px; }
.cast-order { font-family: 'Menlo', monospace; font-size: 13px; color: #7A2F0E;
              margin-bottom: 4px; background: #FBF6EE; padding: 4px 8px;
              display: inline-block; }
.cast-since { font-size: 13px; color: #6A5A4A; font-style: italic; margin-bottom: 14px; }
.cast-blurb { font-size: 16px; line-height: 1.7; margin: 0 0 10px; color: #2A1F18; }
.cast-cite { font-family: 'Menlo', monospace; font-size: 11px; color: #8B7355;
             letter-spacing: 0.5px; margin-top: 4px; }

/* Rain chapter aesthetic */
.rain-text { background: rgba(58, 70, 90, 0.04); padding: 22px 28px; margin: 22px 0;
             border-left: 4px solid #3A5670; }
.rain-text p { font-size: 17px; line-height: 1.8; }
.rain-record { background: rgba(198,139,23,0.10); padding: 18px 22px; margin: 22px 0;
               border-left: 4px solid #C68B17; }
.rain-record-label { font-family: 'Menlo', monospace; font-size: 11px;
                     color: #7A2F0E; letter-spacing: 1px; text-transform: uppercase;
                     margin-bottom: 10px; }
.rain-record p { font-size: 15px; line-height: 1.7; color: #2A1F18; margin: 0; }
.chapter-scene-anchor .rain-record { background: rgba(198,139,23,0.14); }
.chapter-scene-anchor .rain-record p { color: #F2E7D2; }
.chapter-scene-anchor .rain-record-label { color: #F4D49A; }

/* Push density figure */
.push-density-figure { margin: 36px auto 24px; padding: 0; width: 100%; }
.push-density-caption { font-family: 'Georgia', serif; font-size: 18px; color: #2A1F18;
                        font-style: italic; text-align: center; margin: 0 0 18px; }
.push-density-grid { display: grid;
                     grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
                     gap: 18px; width: 100%; }
.push-stack { background: white; border-top: 5px solid var(--accent);
              box-shadow: 0 2px 8px rgba(42,31,24,0.08); padding: 18px 18px 14px;
              min-height: 380px; min-width: 0;
              display: flex; flex-direction: column; }
.ps-phone-top { border-bottom: 1px dashed #D4C5A8; padding-bottom: 10px;
                margin-bottom: 14px; display: flex; justify-content: space-between;
                align-items: baseline; }
.ps-header { font-family: 'Helvetica', sans-serif; font-size: 14px;
             font-weight: 700; color: var(--accent); letter-spacing: 0.5px; }
.ps-count { font-family: 'Helvetica', sans-serif; font-size: 11px;
            color: #8B7355; letter-spacing: 1px; text-transform: uppercase; }
.ps-empty { flex: 1; display: flex; flex-direction: column;
            justify-content: center; align-items: center;
            font-family: 'Georgia', serif; color: #A89880; font-style: italic;
            font-size: 16px; line-height: 1.9; text-align: center;
            padding: 30px 8px; }
.ps-notifs { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.notif { font-family: 'Helvetica', sans-serif; font-size: 11px;
         padding: 7px 9px; border-radius: 4px; color: #2A1F18;
         display: flex; gap: 8px; line-height: 1.4;
         overflow: hidden; min-width: 0; }
.notif-day { font-size: 10px; color: #8B7355; flex: 0 0 30px;
             font-variant-numeric: tabular-nums; }
.notif-txt { flex: 1 1 0; min-width: 0;
             overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.notif-hyperlocal_push { background: #FBE5D6; border-left: 3px solid #B8542B; }
.notif-global_distraction { background: #E0EAF5; border-left: 3px solid #3B6EA8; }
.notif-phone_friction { background: #E2EBDB; border-left: 3px solid #5A7A4F;
                        font-size: 14px; padding: 12px 14px; line-height: 1.6;
                        white-space: normal; gap: 12px; }
.notif-baseline { background: #EFE6D6; border-left: 3px solid #8B7355; }
.notif-rep { display: inline-block; font-size: 9px; color: #6A5A4A;
             margin-left: 4px; padding: 1px 5px; background: rgba(184,84,43,0.10);
             border-radius: 8px; font-variant-numeric: tabular-nums;
             vertical-align: middle; }
.notif-more { font-size: 11px; color: #6A5A4A; font-style: italic; padding-top: 6px; }
.push-density-fineprint { font-family: 'Helvetica', sans-serif; font-size: 12px;
                          color: #8B7355; text-align: center; font-style: italic;
                          margin: 14px auto 0; max-width: 540px; }

/* Universes section */
.universe-compare { width: 100%; border-collapse: collapse; margin: 20px 0 24px;
                    font-family: 'Helvetica', sans-serif; font-size: 13px; }
.universe-compare thead th { padding: 12px 8px; border-bottom: 2px solid #2A1F18;
                             text-align: left; font-size: 11px; letter-spacing: 1px;
                             text-transform: uppercase; color: #2A1F18; }
.universe-compare tbody th { padding: 10px 8px; color: #6A5A4A; font-weight: 500;
                             border-bottom: 1px dashed #D4C5A8; text-align: left; width: 26%; }
.universe-compare tbody td { padding: 10px 8px; border-bottom: 1px dashed #D4C5A8;
                             font-variant-numeric: tabular-nums; color: #2A1F18; font-size: 13px; }
.universe-compare tbody td code { font-size: 11px; padding: 2px 4px; background: #EFE6D6; color: #7A2F0E; }
.universe-compare tbody td em { font-size: 11px; color: #8B7355; }

/* Hero row in universe-compare: 6 / 20 / 2 / 73 jumbo numbers */
.universe-compare tr.row-key th { background: rgba(184, 84, 43, 0.05);
                                  padding: 18px 10px; vertical-align: middle;
                                  font-weight: 700; color: #2A1F18; }
.universe-compare tr.row-key th strong { color: #7A2F0E; }
.universe-compare tr.row-key td { background: rgba(184, 84, 43, 0.04);
                                  padding: 16px 10px; vertical-align: middle;
                                  text-align: left; }
.row-key-sub { font-size: 10px; color: #8B7355; font-weight: 400; letter-spacing: 0.5px; }
.big-num { font-family: 'Helvetica', sans-serif; font-weight: 900;
           font-size: 38px; line-height: 1; letter-spacing: -1.5px;
           font-variant-numeric: tabular-nums; display: inline-block;
           margin-right: 4px; }
.big-num-bl { color: #8B7355; }
.big-num-hp { color: #B8542B; }
.big-num-gd { color: #8B7355; opacity: 0.55; }
.big-num-pf { color: #5A7A4F; }

/* Scene-bridge — soft handoff between chapters */
.scene-bridge { font-style: italic; color: #C7BAA8; font-size: 16px;
                line-height: 1.75; padding: 12px 16px;
                border-left: 3px solid #C68B17;
                background: rgba(198, 139, 23, 0.06);
                margin: 0 0 28px; }

/* Digital Stampede callout in HP essay */
.digital-stampede { background: rgba(122, 47, 14, 0.07);
                    border-left: 4px solid #7A2F0E;
                    padding: 18px 22px; margin: 18px 0;
                    font-size: 16px; line-height: 1.75; }
.digital-stampede strong { color: #7A2F0E; }

/* Cyber-ghost punchline at end of HP essay */
.cyber-ghost { margin: 18px 0 0; padding: 20px 24px;
               background: linear-gradient(135deg, #2A1F18 0%, #3A2E24 100%);
               color: #F2E7D2; border-left: 5px solid #C68B17;
               font-size: 16px; line-height: 1.8; font-family: 'Georgia', serif; }
.cyber-ghost strong { color: #FFE873; }

/* Ending-loop in ch7 closing — title callback */
.ending-loop { margin: 44px 0 0; padding: 36px 38px;
               background: linear-gradient(180deg, #2A1F18 0%, #1A130E 100%);
               color: #F2E7D2; border-left: 6px solid #C68B17;
               box-shadow: 0 4px 16px rgba(42, 31, 24, 0.25); }
.ending-loop p { font-family: 'Georgia', serif; line-height: 1.7;
                  color: #F2E7D2; margin: 0 0 16px; }
.ending-loop p:nth-child(1) { font-size: 28px; font-weight: 700;
                               color: #FFE873; letter-spacing: -0.5px;
                               margin-bottom: 22px; }
.ending-loop p:nth-child(2) { font-size: 17px; }
.ending-loop p:nth-child(3) { font-size: 19px; font-style: italic;
                               border-top: 1px dashed #5A4A3A; padding-top: 22px;
                               margin-top: 22px; margin-bottom: 0; }
.ending-loop strong { color: #FFE873; font-style: normal; }

.universe-essay { background: white; padding: 24px 28px; margin: 18px 0;
                  box-shadow: 0 1px 4px rgba(42,31,24,0.05); border-left: 4px solid #D4C5A8; }
.universe-essay h4 { margin: 0 0 14px; font-size: 21px; font-family: 'Georgia', serif;
                     font-weight: 700; color: #2A1F18; }
.universe-essay p { margin: 0 0 12px; font-size: 16px; line-height: 1.75; color: #2A1F18; }
.universe-essay p:last-child { margin-bottom: 0; }
.universe-essay em { color: #6A5A4A; }
.universe-essay strong { color: #2A1F18; }

.parallel-insight { margin-top: 30px; font-size: 21px; color: #B8542B; font-style: italic; }
.parallel-insight-h3 { margin-top: 50px; font-family: 'Helvetica', sans-serif; font-size: 14px;
                       letter-spacing: 2px; text-transform: uppercase; color: #B8542B;
                       border-bottom: 2px solid #B8542B; padding-bottom: 8px; }

.parallel-kicker { display: block; margin-top: 22px; padding: 20px 24px;
                    background: #E2EBDB; color: #2A1F18; font-family: 'Georgia', serif;
                    font-size: 16px; line-height: 1.7; border-left: 5px solid #5A7A4F; }
.parallel-kicker strong { color: #3F5E36; }
.parallel-kicker em { color: #3F5E36; font-style: italic; }

.parallel-close { margin-top: 32px; padding: 24px 30px; background: #2A1F18; color: #F2E7D2;
                  font-size: 17px; line-height: 1.7; border-left: 6px solid #C68B17;
                  font-family: 'Georgia', serif; }
.parallel-close strong { color: white; }

/* Dialogues */
.dialogue-card { background: white; padding: 24px 28px; margin: 24px 0;
                border-left: 4px solid #2A1F18; box-shadow: 0 1px 4px rgba(42,31,24,0.06); }
.dialogue-pov { font-size: 11px; font-weight: 900; color: #7A2F0E; letter-spacing: 2px;
               text-transform: uppercase; margin-bottom: 12px; }
.dialogue-partner-card { background: #EFE6D6; padding: 10px 14px; margin: 0 0 14px;
                        font-size: 13px; line-height: 1.6; border-left: 3px solid #B8542B; }
.dialogue-context { font-style: italic; color: #6A5A4A; margin: 0 0 16px; font-size: 15px; line-height: 1.7; }
.dialogue-reconstruction { margin: 18px 0; }
.dr-label { font-family: 'Menlo', monospace; font-size: 11px; color: #7A2F0E;
            letter-spacing: 1px; text-transform: uppercase; margin-bottom: 8px; }
.dialogue-summary-label { margin-top: 20px; padding: 9px 14px; font-family: 'Menlo', monospace;
                 font-size: 10.5px; letter-spacing: 1.2px;
                 color: #6A5A4A; background: #DDD4C2; font-weight: 700;
                 border-left: 4px solid #8B7355; }
.dialogue-content { font-family: 'Songti SC', 'Georgia', serif; font-size: 14px; line-height: 1.85;
                   margin: 0; color: #5A4A3A; padding: 18px 22px;
                   background: #E8E3DC; border-left: 4px solid #8B7355;
                   font-style: italic; }
.dialogue-content::before { content: "▼ "; color: #8B7355; font-style: normal; font-weight: 700; }

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
.log-hi { background: #C68B17; color: #14181F; padding: 2px 6px;
          font-weight: 700; border-radius: 3px; letter-spacing: 0.2px; }
.log-aid { color: #6FAEEB; font-weight: 600; font-family: 'Menlo', monospace;
           opacity: 0.85; }
.log-meta { color: #8B7355; font-family: 'Songti SC', 'Georgia', serif;
            font-size: 11px; opacity: 0.75; margin: 0 6px 0 4px;
            letter-spacing: 0.5px; }
.log-turn-her .log-meta { color: #D4B968; opacity: 0.7; }

.npc-loop-legend { font-size: 13px; color: #6A5A4A; background: #EFE6D6;
                   padding: 12px 16px; border-left: 3px solid #C68B17;
                   line-height: 1.7; font-style: italic; margin: 18px 0; }

/* anti-subtitle in opening */
.anti-subtitle { margin: 22px 0 0; padding: 14px 18px;
                 background: rgba(122, 47, 14, 0.08);
                 border-left: 4px solid #7A2F0E;
                 font-size: 16px; line-height: 1.65; color: #2A1F18;
                 font-style: italic; }

/* Cervical-callout — the PF "颈椎被锁死" punch block */
.cervical-callout { margin: 32px 0; padding: 36px 38px;
                    background: linear-gradient(180deg, #FBF6EE 0%, #F2E7D2 100%);
                    border-left: 8px solid #5A7A4F;
                    box-shadow: 0 3px 10px rgba(42, 31, 24, 0.08); }
.cc-lede { font-family: 'Georgia', serif; font-size: 24px; line-height: 1.45;
           color: #2A1F18; font-weight: 700; margin: 0 0 22px;
           letter-spacing: -0.3px; }
.cc-body { font-size: 17px; line-height: 1.85; color: #2A1F18; margin: 0 0 18px; }
.cc-body em { color: #7A2F0E; font-style: italic; font-weight: 700; }
.cc-num { font-family: 'Helvetica', sans-serif; font-weight: 900;
          font-size: 34px; padding: 0 6px; letter-spacing: -1px;
          font-variant-numeric: tabular-nums; vertical-align: -3px; }
.cc-num-bl { color: #8B7355; }
.cc-num-pf { color: #5A7A4F; }
.cc-kicker { font-family: 'Georgia', serif; font-size: 22px; line-height: 1.55;
             color: #2A1F18; font-weight: 700; margin: 24px 0 0;
             padding-top: 22px; border-top: 2px solid #5A7A4F; }
.cc-kicker strong { color: #7A2F0E; background: #FFE873; padding: 2px 6px; }

/* Alienation block — at the end of ch6 */
.alienation-block { margin: 50px 0 0; padding: 50px 44px;
                    background: #14181F; color: #C8CDD6;
                    border-left: 8px solid #C68B17; }
.ab-tag { font-family: 'Helvetica', sans-serif; font-size: 11px;
          color: #C68B17; letter-spacing: 2.5px; text-transform: uppercase;
          margin: 0 0 18px; font-weight: 700; }
.ab-title { font-family: 'Georgia', serif; font-size: 32px; line-height: 1.3;
            color: #FFE873; margin: 0 0 28px; letter-spacing: -0.5px;
            font-weight: 900; border: none; padding: 0; }
.ab-body { font-size: 17px; line-height: 1.85; color: #E0E0E0; margin: 0 0 16px; }
.ab-body strong { color: white; }
.ab-body code { background: rgba(198, 139, 23, 0.18); color: #FFE873;
                padding: 2px 8px; font-family: 'Menlo', monospace;
                font-size: 14px; border-radius: 3px; }
.ab-list { list-style: none; padding: 0; margin: 0 0 22px; }
.ab-list li { padding: 10px 0 10px 24px; border-bottom: 1px dashed #2A303C;
              font-size: 16px; line-height: 1.7; color: #E0E0E0;
              position: relative; }
.ab-list li::before { content: "—"; position: absolute; left: 0;
                       color: #C68B17; font-weight: 900; }
.ab-list li strong { color: white; background: rgba(255, 232, 115, 0.12);
                      padding: 0 4px; }
.ab-punch { margin: 32px 0; padding: 32px 30px; background: #2A1F18;
            border: 2px solid #C68B17; text-align: center;
            font-family: 'Georgia', serif; font-size: 22px; line-height: 1.65;
            color: #FFE873; }
.ab-punch strong { color: white; font-size: 32px; display: block;
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
.chapter-coda { padding: 60px 40px; background: linear-gradient(180deg, #F2E7D2 0%, #FBF6EE 100%); }
.chapter-coda h2 { color: #2A1F18; border-color: #B8542B; }

/* Data vanity */
.chapter-data-vanity { background: #EFE6D6; padding: 56px 40px; margin-top: 0;
                        border-top: 4px solid #2A1F18; }
.chapter-data-vanity h2 { font-family: 'Georgia', serif; font-size: 36px;
                          color: #2A1F18; border-bottom: 2px solid #2A1F18;
                          letter-spacing: -0.5px; }
.data-vanity-lead { font-size: 18px; line-height: 1.7; color: #6A5A4A;
                    font-style: italic; margin: 0 0 36px; max-width: 640px; }
.data-vanity-section { margin: 36px 0 28px; }
.dv-h3 { font-family: 'Helvetica', sans-serif; font-size: 14px; letter-spacing: 2px;
         text-transform: uppercase; color: #B8542B; margin: 0 0 18px;
         font-weight: 700; }
.data-vanity-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.dv-cell { background: white; padding: 18px 22px; box-shadow: 0 1px 3px rgba(42,31,24,0.06);
           border-left: 4px solid #2A1F18; }
.dv-cell-big { grid-column: 1 / -1; border-left-color: #B8542B; }
.dv-num { font-family: 'Helvetica', sans-serif; font-weight: 900;
          font-size: 36px; line-height: 1.05; letter-spacing: -1.5px;
          color: #2A1F18; font-variant-numeric: tabular-nums; }
.dv-cell-big .dv-num { font-size: 50px; color: #B8542B; }
.dv-lbl { font-family: 'Helvetica', sans-serif; font-size: 14px;
          color: #2A1F18; margin-top: 4px; font-weight: 600; }
.dv-sub { font-family: 'Helvetica', sans-serif; font-size: 12px;
          color: #6A5A4A; margin-top: 4px; line-height: 1.4; }
.data-vanity-fineprint { margin-top: 32px; font-size: 14px; color: #6A5A4A;
                         font-style: italic; border-top: 1px dashed #A89880;
                         padding-top: 16px; }
.data-vanity-kicker { margin-top: 36px; padding: 28px 30px; background: #2A1F18;
                      color: #F2E7D2; font-size: 17px; line-height: 1.7;
                      border-left: 6px solid #C68B17; font-family: 'Georgia', serif; }
.data-vanity-kicker strong { color: #C68B17; }

@media (max-width: 600px) {
  body { font-size: 17px; }
  h1 { font-size: 36px; }
  h2 { font-size: 26px; }
  .open { padding: 50px 24px 40px; }
  .chapter { padding: 40px 24px; }
  .methodology { padding: 24px 24px; }
  .push-density-grid { grid-template-columns: 1fr; }
  .data-vanity-grid { grid-template-columns: 1fr; }
  .dv-num { font-size: 30px; }
  .dv-cell-big .dv-num { font-size: 40px; }
  .universe-compare { font-size: 12px; }
  .universe-compare tbody th { width: auto; }
}
"""


# ─── Assemble HTML ─────────────────────────────────────────────────────
HTML = "\n".join([
    "<!DOCTYPE html>",
    '<html lang="zh-CN"><head>',
    '<meta charset="utf-8"/>',
    '<meta name="viewport" content="width=device-width, initial-scale=1"/>',
    '<title>抬头那一秒, 雨里的笔记本变成了 4 年的常客 · 36 岁咖啡店老板娘 14 天 · Synthetic Socio Wind Tunnel</title>',
    f'<style>{CSS}</style>',
    "</head><body>",
    section_open(),
    section_methodology(),
    section_who(),
    section_counter_cast(),
    section_laptop_rain(),
    section_metro_summer(),
    section_four_fourteens(),
    section_dialogues(),
    section_christmas_eve(),
    section_data_vanity(),
    "</body></html>"
])

OUT.parent.mkdir(parents=True, exist_ok=True)
with open(OUT, "w") as f:
    f.write(HTML)

size_mb = OUT.stat().st_size / 1e6
print(f"\n✓ Wrote {OUT}")
print(f"  size: {size_mb:.2f} MB")
print(f"  open: file://{OUT.absolute()}")
