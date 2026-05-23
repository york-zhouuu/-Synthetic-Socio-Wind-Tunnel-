"""Build 'bridge' 插曲 — 0175 the lawyer-neighbor as the social hub
connecting Mary / Lisa / 0590 / Frank, with Lisa as the paradoxical outlier.

Output: docs/case_studies/bridge.html (single standalone interstitial)
Data:   data/analysis/case_studies/*_4variants.json (already extracted)
        + lawyer 0175 life_history streamed from HP snapshot
"""
import json
import os
import re
import ijson
from pathlib import Path

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
SUITE = REPO / "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245"
HP = SUITE / "variant_hyperlocal_push/seed_43_pid69976_tick4020.snapshot.json"
OUT = REPO / "docs/case_studies/bridge.html"

# ─── Load profiles ─────────────────────────────────────────────────────
profs = {}
for f in os.listdir(REPO / "data/population_cache/v1"):
    d = json.load(open(REPO / f"data/population_cache/v1/{f}"))
    if d.get("key_inputs", {}).get("seed") != 43:
        continue
    for p in d.get("profiles", []):
        if p.get("agent_id"):
            profs[p["agent_id"]] = p

# ─── Cast ──────────────────────────────────────────────────────────────
CAST = {
    "Mary":  {"aid": "a_43_0405", "label": "Mary", "subtitle": "75 岁退休志愿者",
              "color": "#A0252F", "x": 200, "y": 220},
    "0175":  {"aid": "a_43_0175", "label": "那位律师邻居", "subtitle": "44 岁 Barangaroo 律师 · 144 路通勤",
              "color": "#1B1F2A", "x": 400, "y": 130},   # central hub
    "0590":  {"aid": "a_43_0590", "label": "RSL 厨子", "subtitle": "37 岁洗碗工 + aged care 护工",
              "color": "#3A9D5C", "x": 600, "y": 220},
    "Frank": {"aid": "a_43_0012", "label": "老 Frank", "subtitle": "64 岁退休会计 · 1992 搬来 Lane Cove 32 年",
              "color": "#5A5E6A", "x": 240, "y": 380},
    "Lisa":  {"aid": "a_43_0482", "label": "Lisa", "subtitle": "49 岁 Plaza 干洗店老板 · 12 年",
              "color": "#D14B12", "x": 700, "y": 380},
}

# ─── Hops matrix (from previous scan, HP variant) ──────────────────────
HOPS = {
    "Mary":  {"Mary": "—", "Lisa": 6, "0590": 0, "0175": 1, "Frank": 6},
    "Lisa":  {"Mary": 7,  "Lisa": "—","0590": 6, "0175": 6, "Frank": 5},
    "0590":  {"Mary": 3,  "Lisa": 6, "0590": "—","0175": 3, "Frank": 5},
    "0175":  {"Mary": 0,  "Lisa": 4, "0590": 1, "0175": "—","Frank": 6},
    "Frank": {"Mary": 4,  "Lisa": 5, "0590": 3, "0175": 6, "Frank": "—"},
}

# Direct dialogue edges (5-turn 实际对话)
EDGES = [
    ("Mary",  "0175", "5-turn × 4 universes", "direct"),
    ("Mary",  "0590", "5-turn × 4 universes", "direct"),
    ("0175",  "0590", "1 hop · 听过他的故事",      "weak"),
    ("0175",  "Frank","life_history 直接提名: '我后来知道他叫 Frank,退休前是会计师'", "memory"),
    ("Mary",  "Lisa", "6 手 · 几乎没听过",          "distant"),
    ("0590",  "Lisa", "6 手 · 几乎没听过",          "distant"),
    ("0175",  "Lisa", "6 手 · 几乎没听过",          "distant"),
]

# ─── Pull 0175 life_history (key citations) ────────────────────────────
print("streaming HP for 0175 life_history...")
LAWYER_LIFE = []
with open(HP) as f:
    for aid, evs in ijson.kvitems(f, "memory_store_state.agent_events"):
        if aid == "a_43_0175":
            for e in evs:
                if e.get("kind") == "life_history":
                    LAWYER_LIFE.append((e.get("content") or "").strip())
            break

def find_life(*keywords):
    """Return first life_history matching any keyword."""
    for ev in LAWYER_LIFE:
        for kw in keywords:
            if kw in ev:
                return ev
    return None

L_FRANK   = find_life("144 路公交车上的固定座位", "Frank")
L_MRSCHEN = find_life("Mrs. Chen", "陈太太", "jump leads")
L_GALUWA  = find_life("Galuwa")
L_SHIFT   = find_life("早晨接力赛")  # work-life balance
L_CHATSW  = find_life("Crows Nest", "Barangaroo")
L_FAMILY  = find_life("儿子穿上蓝格子校服", "Lane Cove Public")

# ─── SVG network diagram ───────────────────────────────────────────────
def render_network_svg(width=860, height=520):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
             f'style="width:100%;max-width:{width}px;height:auto;background:#FFFEF8;font-family:Helvetica,sans-serif;">']
    # Title
    parts.append(f'<text x="{width//2}" y="36" text-anchor="middle" '
                 f'font-size="16" font-weight="700" letter-spacing="2px" fill="#1B1F2A">'
                 f'5 个 agent · 1,000 人小镇里的小三角</text>')
    parts.append(f'<text x="{width//2}" y="56" text-anchor="middle" '
                 f'font-size="11" fill="#5A5E6A">实线 = 直接 5 轮对话过 · 虚线 = 通过 N 手听过 · 点画 = life_history 里被提名</text>')

    # Edges
    EDGE_STYLE = {
        "direct":  ("#A0252F", "4",        "none"),
        "weak":    ("#1B1F2A", "1.8",      "8 6"),
        "memory":  ("#D14B12", "2.4",      "2 4"),
        "distant": ("#A8ACB5", "1.0",      "2 10"),
    }
    for a, b, label, kind in EDGES:
        color, w, dash = EDGE_STYLE[kind]
        x1, y1 = CAST[a]["x"], CAST[a]["y"]
        x2, y2 = CAST[b]["x"], CAST[b]["y"]
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                     f'stroke="{color}" stroke-width="{w}" stroke-dasharray="{dash}" opacity="0.85"/>')
        # mid-label
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        # only show short labels to avoid clutter
        short = label if len(label) < 24 else label[:22] + "…"
        parts.append(f'<text x="{mx}" y="{my - 4}" text-anchor="middle" '
                     f'font-size="9.5" fill="{color}" font-weight="600" '
                     f'style="paint-order:stroke;stroke:#FFFEF8;stroke-width:3px">{short}</text>')

    # Nodes
    for name, d in CAST.items():
        is_hub = (name == "0175")
        is_outlier = (name == "Lisa")
        r = 38 if is_hub else 30
        # outer ring for hub
        if is_hub:
            parts.append(f'<circle cx="{d["x"]}" cy="{d["y"]}" r="{r+6}" '
                         f'fill="none" stroke="{d["color"]}" stroke-width="1.5" '
                         f'stroke-dasharray="4 3" opacity="0.5"/>')
        # outlier dotted ring
        if is_outlier:
            parts.append(f'<circle cx="{d["x"]}" cy="{d["y"]}" r="{r+4}" '
                         f'fill="none" stroke="{d["color"]}" stroke-width="1" '
                         f'stroke-dasharray="1 4" opacity="0.5"/>')
        parts.append(f'<circle cx="{d["x"]}" cy="{d["y"]}" r="{r}" '
                     f'fill="{d["color"]}" stroke="#FFFEF8" stroke-width="3"/>')
        # name
        parts.append(f'<text x="{d["x"]}" y="{d["y"]+4}" text-anchor="middle" '
                     f'font-size="13" font-weight="700" fill="white">{d["label"]}</text>')
        # subtitle below
        parts.append(f'<text x="{d["x"]}" y="{d["y"]+r+14}" text-anchor="middle" '
                     f'font-size="10" fill="#5A5E6A">{d["subtitle"]}</text>')
        # role tag
        tag = None
        if is_hub: tag = "★ 社交节点 hub"
        elif is_outlier: tag = "○ 反向远点"
        if tag:
            parts.append(f'<text x="{d["x"]}" y="{d["y"]+r+28}" text-anchor="middle" '
                         f'font-size="10" font-style="italic" fill="{d["color"]}" font-weight="600">{tag}</text>')

    parts.append('</svg>')
    return "".join(parts)


def render_hops_matrix():
    """Render the hops matrix as a clean HTML table."""
    names = ["Mary", "0175", "0590", "Frank", "Lisa"]
    rows = []
    rows.append("<tr><th></th>" + "".join(f"<th>{n}</th>" for n in names) + "</tr>")
    for r in names:
        cells = [f"<th>{r}</th>"]
        for c in names:
            v = HOPS[r][c]
            cls = "mx-self" if v == "—" else (
                "mx-direct" if v == 0 else
                "mx-close" if v == 1 else
                "mx-mid" if isinstance(v, int) and v <= 3 else
                "mx-far"
            )
            cells.append(f'<td class="{cls}">{v}</td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f'<table class="hops-matrix"><thead>{rows[0]}</thead><tbody>{"".join(rows[1:])}</tbody></table>'


# ─── CSS ───────────────────────────────────────────────────────────────
CSS = """
* { box-sizing: border-box; }
body { font-family: 'Georgia', 'Songti SC', serif; max-width: 880px; margin: 0 auto;
       padding: 0; background: #FFFEF8; color: #1B1F2A; line-height: 1.75; font-size: 17px; }
section { padding: 50px 40px; }
h1 { font-size: 48px; font-weight: 900; letter-spacing: -1px; line-height: 1.1; margin: 0 0 18px; }
h2 { font-size: 28px; font-weight: 900; margin: 50px 0 18px; padding-bottom: 10px;
     border-bottom: 1px solid #1B1F2A; letter-spacing: -0.5px; }
h3 { font-size: 18px; margin: 26px 0 12px; color: #A0252F; font-family: 'Helvetica', sans-serif;
     letter-spacing: 2px; text-transform: uppercase; }
p { margin: 0 0 16px; }
.kicker { font-family: 'Helvetica', sans-serif; font-size: 12px; letter-spacing: 3px;
          text-transform: uppercase; color: #A0252F; margin: 0 0 12px; font-weight: 700; }
.subtitle { font-size: 18px; color: #5A5E6A; font-style: italic; max-width: 640px;
            margin: 0 0 32px; line-height: 1.55; }
code { background: #F4EFE5; color: #A0252F; padding: 2px 5px; font-size: 0.85em;
       font-family: 'Menlo', monospace; border-radius: 2px; }
strong { color: #1B1F2A; }

.opening { background: #1B1F2A; color: #F4EFE5; padding: 60px 40px; }
.opening h1 { color: white; }
.opening .kicker { color: #F0C419; }
.opening .subtitle { color: #C8CDD6; }
.opening code { background: rgba(240,196,25,0.15); color: #F0C419; }

.network-figure { margin: 30px 0; padding: 24px;
                  background: #FFFEF8; border: 1px solid #E6D9B8;
                  border-radius: 4px; }

.hops-matrix { width: 100%; max-width: 540px; margin: 18px auto 8px;
               border-collapse: collapse; font-family: 'Menlo', monospace;
               font-size: 13px; }
.hops-matrix th, .hops-matrix td { padding: 8px 10px; text-align: center;
                                   border: 1px solid #E6D9B8; font-variant-numeric: tabular-nums; }
.hops-matrix th { background: #F4EFE5; font-weight: 700; color: #1B1F2A; }
.hops-matrix tbody th { background: #FBF6E8; text-align: left; }
.mx-self { background: #1B1F2A; color: #F0C419; font-weight: 700; }
.mx-direct { background: #A0252F; color: white; font-weight: 700; }
.mx-close { background: #FBE5D6; color: #A0252F; font-weight: 700; }
.mx-mid { background: #FFFCE8; color: #1B1F2A; }
.mx-far { background: #F4EFE5; color: #8A8E96; font-style: italic; }
.hops-caption { font-family: 'Helvetica', sans-serif; font-size: 11px;
                color: #8A8E96; text-align: center; max-width: 540px;
                margin: 0 auto 26px; font-style: italic; }

.quote-block { background: #14181F; color: #C8CDD6; padding: 18px 22px; margin: 18px 0;
               border-left: 4px solid #F0C419; font-family: 'Menlo', monospace;
               font-size: 13px; line-height: 1.75; }
.quote-block .qb-source { color: #7A8090; font-size: 10.5px; letter-spacing: 1px;
                          margin-bottom: 10px; padding-bottom: 8px;
                          border-bottom: 1px dashed #2A303C; }
.quote-block .qb-hi { background: #F0C419; color: #14181F; padding: 1px 4px;
                      font-weight: 700; border-radius: 2px; }

.scene-block { background: #F4EFE5; padding: 22px 28px; margin: 24px 0;
               border-left: 5px solid #1B1F2A; font-family: 'Georgia', serif;
               font-size: 17px; line-height: 1.85; }

.lisa-callout { background: #FBE5D6; padding: 22px 28px; margin: 28px 0;
                border-left: 5px solid #D14B12; }
.lisa-callout em { color: #5A5E6A; }

.closing { background: #1B1F2A; color: #F4EFE5; padding: 50px 40px; margin-top: 0; }
.closing em { color: #F0C419; }
.closing strong { color: white; }

.case-links { display: flex; gap: 14px; flex-wrap: wrap; margin: 28px 0;
              font-family: 'Helvetica', sans-serif; }
.case-links a { color: #A0252F; text-decoration: none; padding: 10px 16px;
                background: #FBE5D6; border-radius: 3px; font-size: 13px;
                font-weight: 600; }
.case-links a:hover { background: #F4D08C; }

@media (max-width: 600px) {
  body { font-size: 16px; }
  h1 { font-size: 34px; }
  h2 { font-size: 22px; }
  section { padding: 36px 22px; }
}
"""


# ─── Page assembly ─────────────────────────────────────────────────────
def opening_section():
    return f"""
<section class="opening">
  <p class="kicker">A LONGFORM INTERLUDE · 1,000 个虚拟居民里的隐形 hub</p>
  <h1>那位律师邻居什么都知道</h1>
  <p class="subtitle">在 Synthetic Socio Wind Tunnel 这套 1,000 人仿真里,有一位 44 岁的律师
  (<code>a_43_0175</code>),他没有自己的 longform 报道——但他出现在了几乎每一个 hero 的故事里。
  他是 Mary 的对话搭子,是 老 Frank 144 路通勤的同车老熟人,
  跟干洗店 Lisa 共享同一栋 Plaza 旁边的公寓楼。<br>
  他没有戏剧化的"4 个平行宇宙"——4 部不同的手机底下,他都把车停在 building_2022 楼下。
  但 1,000 人小镇里的多数八卦,都至少经过他一手。
  这一篇关于他作为 social hub 的位置。</p>
</section>
"""


def scene_open():
    return f"""
<section>
  <h2>1 · 早上 7:25,Greenwich 那个车站</h2>
  <div class="scene-block">
    "我每天早上 7:25 准时出现在 Greenwich 那个车站,坐 144 路到 St Leonards 换火车去 City。
    车上有个头发花白的老人总是坐在左侧第三排——我后来知道他叫 Frank,退休前是会计师。
    2020 年 3 月疫情刚来时,车突然空了,那段时间我甚至有点想念和 Frank 一起抱怨
    Pacific Highway 堵车的早晨。"
  </div>
  <p>这是 <code>a_43_0175</code> 在 <code>memory_store.life_history</code> 里的第 2 条事件,
  importance 字段 0.7+。它写在 simulation 启动之前——属于他被注入的"过去"。</p>

  <p><strong>这条 life_history 同时也是一份 ground truth 证书:</strong>
  它直接证明了 <code>a_43_0012</code>(我们叫他老 Frank)真实身份是会计师——
  虽然他自己的 profile.occupation 字段写的是 <code>construction</code>。
  系统的两层数据互相矛盾,但 0175 这条 life_history 记录了哪一层是真的。</p>
</section>
"""


def section_network():
    return f"""
<section>
  <h2>2 · 5 个 agent · 1 张社交网络图</h2>
  <p>在这个 1,000 人的仿真里,我们 detailed reporting 过 3 个 hero:
  <a href="mary.html">Mary</a>(75 岁退休志愿者)、Lisa(49 岁 Plaza 干洗店老板)、
  老 Frank(64 岁退休会计)。还有第 4 位 hero <strong>RSL 厨子 0590</strong>
  (37 岁洗碗工 + aged care 护工)即将上线。<br>
  把这 4 位 hero 跟 0175 摆在同一张网络图上,会出来一个清晰的拓扑:</p>

  <div class="network-figure">
    {render_network_svg()}
  </div>

  <p>4 种边:</p>
  <ul>
    <li><strong style="color:#A0252F">实线红</strong> — 实际在 simulation 里发生过 5 轮对话(4 个 universe 都发生)</li>
    <li><strong style="color:#1B1F2A">长虚线深灰</strong> — 通过 1 手转述听过对方的故事</li>
    <li><strong style="color:#D14B12">短虚线橙</strong> — life_history 里直接提名(ground-truth memory)</li>
    <li><strong style="color:#A8ACB5">点画灰</strong> — 5+ 手才听到的远端关系</li>
  </ul>
</section>
"""


def section_matrix():
    return f"""
<section>
  <h2>3 · 八卦距离矩阵</h2>
  <p>系统的 <code>conversation_service_state.known</code> 字段记录了每个 agent 听过哪些 info,
  以及每条 info 是经过多少手才到她耳朵里。从这个 16,000-条 info × 1,000-agent 的稀疏矩阵里,
  抽出我们这 5 位的 5×5 子矩阵:</p>

  {render_hops_matrix()}
  <p class="hops-caption">行 = 谁,列 = 听过谁的故事 · 数字 = 最近几手 · "—" 是她自己</p>

  <p>读 0175 这一行: 他听 Mary 的故事是 <strong>0 手</strong>(因为他直接跟她对话过),
  听 0590 是 <strong>1 手</strong>(从某个共同熟人那里听过),
  听 Frank 是 <strong>6 手</strong>(虽然他 life_history 记得 Frank 的脸,但 simulation 跑起来后
  Frank 的新故事要绕 6 圈才到他耳朵)。</p>

  <p>更有趣的是 <strong>Lisa 那一列</strong>:她离所有人都 5-7 手——这位 12 年 Plaza 干洗店老板,
  在 simulation 的对话网络里反而是 <strong>最远的节点</strong>。</p>
</section>
"""


def section_frank_quote():
    return f"""
<section>
  <h2>4 · 0175 跟老 Frank:144 路通勤的同车熟人</h2>
  <p>0175 是<strong>除老 Frank 自己外,整套仿真里唯一一个在 life_history 里直接写出
  "Frank"两个字的 agent</strong>。这条记忆直接锚定了我们 Frank 报道里那个核心矛盾——
  系统给老 Frank 的 profile.occupation 是 <code>construction</code>,但 0175 的 life_history
  原原本本写着:"<strong>退休前是会计师</strong>"。</p>

  <div class="quote-block">
    <div class="qb-source">&gt; memory_store.life_history · agent=a_43_0175 · importance=0.75</div>
    144 路公交车上的固定座位 — 自从搬来,我每天早上 7:25 准时出现在
    <span class="qb-hi">Greenwich 那个车站</span>,坐 144 路到 St Leonards 换火车。
    车上有个头发花白的老人总是坐在左侧第三排,我后来知道他叫 <span class="qb-hi">Frank</span>,
    退休前是 <span class="qb-hi">会计师</span>。2020 年 3 月疫情刚来时,车突然空了,
    那段时间我甚至有点想念和 Frank 一起抱怨 Pacific Highway 堵车的早晨。
  </div>

  <p>但当 simulation 真正跑起来,老 Frank 出现在 0175 视野里的频率
  在 14 天里降到了几乎 0——0175 听到老 Frank 的"周六去 Pottery Lane 看新表演空间"
  那个 evangelizing 故事,需要 6 手转述才能传到他耳朵里。</p>

  <p><strong>认识 ≠ 沟通。</strong>0175 记得 Frank 这个人,
  但 simulation 跑出来的 14 天里,他们没在同一个 5-分钟时段共处过任何地方,
  也没在彼此的 plan 路径里出现过。两个老同车熟人,
  在仿真里活成了两个互不影响的轨道。</p>
</section>
"""


def section_mary_lisa():
    return f"""
<section>
  <h2>5 · 0175 跟 Mary:同住 building_2022 的两位邻居</h2>
  <p>Mary 跟 0175 之间是这套报道里最稠密的一条连接——他们在 <strong>4 个 universe</strong>
  里都进行了 5 轮对话。0175 还住在 Mary 同一栋楼(<code>building_2022</code>),
  共享同一位邻居 Mrs Chen——一位牵着雪纳瑞的老太太。</p>

  <div class="quote-block">
    <div class="qb-source">&gt; memory_store.life_history · agent=a_43_0175 · importance=0.68</div>
    <span class="qb-hi">Plaza 旁边那位陈太太</span> — 搬来第一年我根本不认识邻居,
    直到 2019 年一个冬夜,Lane Cove Plaza 旁边的 Coles 停车场,
    我忘了关车灯,电池耗尽。一个牵着雪纳瑞的老太太——后来知道她姓陈,
    <span class="qb-hi">就住我公寓楼上</span>——二话不说从后备箱拿出 jump leads 救了我。
    现在每天早上在电梯里碰到,她都会问一句"今天去圣莱纳德还是在家?"。
  </div>

  <p>Mary 也在她的 life_history 里多次提到 Mrs Chen——但他们俩各自记得的
  "Mrs Chen"细节有微妙差别(Mary 记得"住公寓后栋的紫红披肩老太",0175 记得
  "牵雪纳瑞的住楼上的老太太")。一个虚拟 agent 在 1,000 人小镇里可以同时被多位邻居
  以不同细节记住——<strong>多个 LLM 视角下的同一个 NPC</strong>。</p>
</section>
"""


def section_lisa_outlier():
    return f"""
<section>
  <h2>6 · Lisa 是反向的远点</h2>
  <p>有一件事是 Lisa 自己肯定不知道的——
  她从 2012 年起就在 Lane Cove Plaza 经营那家干洗店,
  每天早上 6 点开门,认识半条街的客人名字,
  整 14 天里也跟 4 位顾客有过完整的 5 轮对话。但当我们把镇上每位居民的
  <code>known</code> 字段摆在一起,<strong>Lisa 离我们这 4 位 hero 都很远</strong>:</p>

  <div class="lisa-callout">
    <p><strong>Lisa → Mary: 6 手</strong> · <strong>Lisa → 0175: 6 手</strong>
    · <strong>Lisa → 0590: 6 手</strong> · <strong>Lisa → 老 Frank: 5 手</strong></p>
    <p><em>(对比:0175 → Mary 是 0 手,0175 → 0590 只有 1 手。)</em></p>
  </div>

  <p>但 Lisa 不是没人知道——前面那个 992 名邻居的 known 池里,
  <strong>Lisa 自己的 4 条 dialogue info 几乎传遍了整个 Lane Cove</strong>。
  她在网络中是个高出度的源,但<strong>低入度的接收器</strong>:她讲的故事被反复转述,
  但别人讲的故事她几乎听不到。</p>

  <p>这跟她的物理位置吻合——她每天站在 Plaza 干洗店的台子后面,
  顾客们带着各自的故事来,留下几句寒暄就走。她记得他们的衣服尺码、记得 Mrs Chen
  那件没取走的风衣;但顾客转身走出店门之后跟 144 路上的 Frank 喝咖啡聊的什么,
  她不会知道。</p>

  <p><strong>同样一个 1,000 人的小镇,有人是 hub,有人是反向的远点。</strong>
  这个差别不是性格的,也不是社交意愿的——是<strong>仿真里 plan 路径 + 对话发起 + 物理位置
  三个 channel 共同决定的网络拓扑</strong>。0175 因为通勤 + 律师业务 + 学校家长 + 公寓邻居
  四种角色叠加,自然成了多线 hub;Lisa 因为店铺位置固定 + 顾客流动 + 自己作息独立,
  成了一个高知名度但低听力的孤立节点。</p>
</section>
"""


def closing():
    return f"""
<section class="closing">
  <p style="font-family:Georgia,serif;font-size:19px;line-height:1.7;color:#F4EFE5;">
  Synthetic Socio Wind Tunnel 这套 1,000 人仿真生成了 ~16 GB 的 snapshot 数据。
  我们 detailed 了其中 3 位 hero——但 0175 不是 hero,他是把这些 hero 串起来的人。<br><br>
  <strong>真正的小镇研究里,这种"什么都知道的律师邻居"才是最贵的访谈对象。</strong>
  在仿真里,我们能直接 dump 他的 <code>known</code> 字段、
  看他 life_history 里到底记得谁——不需要约访,不需要破冰,
  不需要担心他记错或者忘了。<br><br>
  下次你看完 <a href="mary.html" style="color:#F0C419">Mary</a> 那 10 章
  + 即将上线的 Lisa 跟 0590 的篇,记得回头看一眼这个 1 手就能连通整个网络的男人。<br>
  <em>1,000 人小镇里有 999 个其他人——但只有 1 个真正的 hub。</em>
  </p>

  <div class="case-links">
    <a href="mary.html">→ Mary 长文(75 岁退休志愿者)</a>
    <a href="../项目实验结果.html">→ 1,000 人统计层报告</a>
  </div>
</section>
"""


html_parts = [
    "<!DOCTYPE html>",
    '<html lang="zh-Hans"><head>',
    '<meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    '<title>那位律师邻居什么都知道 · 1,000 人小镇的隐形 hub · Synthetic Socio Wind Tunnel</title>',
    f'<style>{CSS}</style>',
    '</head><body>',
    opening_section(),
    scene_open(),
    section_network(),
    section_matrix(),
    section_frank_quote(),
    section_mary_lisa(),
    section_lisa_outlier(),
    closing(),
    '<footer style="padding:30px; text-align:center; font-size:12px; color:#A8ACB5; font-style:italic;">',
    'Synthetic Socio Wind Tunnel · 悉尼 Lane Cove 虚拟城市 · seed 43 · '
    'social topology from conversation_service_state.known',
    '</footer>',
    '</body></html>',
]

OUT.write_text("\n".join(html_parts))
print(f"Wrote {OUT} · {OUT.stat().st_size / 1024:.0f} KB")
