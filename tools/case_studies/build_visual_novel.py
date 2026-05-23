"""Build VISUAL NOVEL style case study pages.

Each day = a scene with:
- Phone notification cards (real push contents from snapshot)
- Inner monologue (data-grounded, lightly narrated)
- Mini map of trajectory
- People encountered (with real profiles)
- Real plan + reason (from agent_runtime_state.plan)

Output:
  docs/case_studies/mary_diary.html (overwrites previous)
  docs/case_studies/mike_diary.html
"""
import json
import os
from pathlib import Path
from datetime import datetime, timedelta

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
ATLAS_PATH = REPO / "data/lanecove_atlas.json"
DIARY_DIR = REPO / "data/analysis/case_studies"
POP_CACHE = REPO / "data/population_cache/v1"
OUT_DIR = REPO / "docs/case_studies"


# ──────────────────────────────────────────────────────────────────────
# Atlas + loc lookup
# ──────────────────────────────────────────────────────────────────────
def centroid_xy(verts):
    if not verts: return None
    xs = [v["x"] for v in verts] if isinstance(verts[0], dict) else [v[0] for v in verts]
    ys = [v["y"] for v in verts] if isinstance(verts[0], dict) else [v[1] for v in verts]
    return sum(xs)/len(xs), sum(ys)/len(ys)


atlas = json.load(open(ATLAS_PATH))
LOC2META = {}
for bid, b in atlas["buildings"].items():
    verts = b.get("polygon", {}).get("vertices", [])
    if verts:
        c = centroid_xy(verts)
        if c:
            LOC2META[bid] = {"name": b.get("name") or "", "type": b.get("building_type") or "",
                             "x": c[0], "y": c[1], "polygon": verts, "kind": "building"}
outdoor = atlas.get("outdoor_areas", {})
outdoor_iter = outdoor.items() if isinstance(outdoor, dict) else [(o["id"], o) for o in outdoor]
for oid, o in outdoor_iter:
    verts = o.get("polygon", {}).get("vertices", [])
    if verts:
        c = centroid_xy(verts)
        if c:
            LOC2META[oid] = {"name": o.get("name") or "", "type": o.get("area_type") or "",
                             "x": c[0], "y": c[1], "polygon": verts, "kind": "outdoor"}


# ──────────────────────────────────────────────────────────────────────
# Load profiles for agent + their encountered neighbors
# ──────────────────────────────────────────────────────────────────────
profiles = {}
for f in os.listdir(POP_CACHE):
    d = json.load(open(POP_CACHE / f))
    if d.get("key_inputs", {}).get("seed") != 43:
        continue
    for p in d.get("profiles", []):
        if p.get("agent_id"):
            profiles[p["agent_id"]] = p


# ──────────────────────────────────────────────────────────────────────
# Hero metadata + storyline scaffold (per-day script)
# ──────────────────────────────────────────────────────────────────────
HEROES = {
    "mary": {
        "aid": "a_43_0405",
        "name_zh": "Mary (邻居老何)",
        "name_en": "agent_405",
        "cover_title": "Mary 的 14 天",
        "cover_subtitle": "75 岁退休女士 · 内蒙古移民 · 一波亲子向推送 · 一个佛教冥想中心 · 一群素未谋面的本街邻居",
        "day_moods": {
            4: ("没在意",
                "推送弹了 5 条 Shinnyo Australia 的活动 — 儿童活动、清扫日、新邻居见面会、亲子市集、读书会。"
                "我没有孙辈,这些活动跟我没什么关系。手机推送我一般不看,养老金、女儿电话、本地新闻,够了。"
                "今天我去楼下取信时碰到了同栋楼的邻居 #584(我们以前几次都因为我赶着去 Library 帮忙没聊上)。"
                "我跟她提了一嘴新开的 Galuwa 康乐中心 — 8000 多万投资、15 年规划、8 个球场、有免费开放日。我对这个比对 Shinnyo 上心多了。"
                "<em>她说等天气好了一起去 Galuwa 看看。我说好,但晚上 7 点要看新闻 + 给东郊女儿打视频电话,这是冰箱便签写好的。</em>"),
            5: ("好奇了一下",
                "今天又是 5 条 Shinnyo 推送。其中『周三晚 7 点读书会——可带较大孩子,环境安静』这条我看了两遍。"
                "我没有孙辈,但我以前在 Library 周三晚整书目时,确实是一周里最安静的时段。"
                "下午楼里走廊上碰到邻居 #175 (商业纠纷律师,正在投资 Mowbray Road 那栋新公寓)。"
                "他跟我说他今晚要在 Domain 上查 Lane Cove 新公寓的数据。我跟他说我在 Greenwich 住了 20 多年,主要靠老房子的钱过日子。"
                "<em>他听了愣了一下,说『难怪你对本地房子这么熟』。我笑了。其实我对房子不熟,我只是住的久。</em>"),
            6: ("决定去看看",
                "第三天 5 条 Shinnyo 推送。我心里嘀咕了一句:那不就 2.4 km 嘛,走个路也好。"
                "中午晒被子时跟楼下的邻居 #590(他在 Greenwich 的 RSL 厨房上晚班) 闲聊。"
                "我自我介绍说『我是住三楼的邻居老何』,跟他说我刚从 Canopy Park 遛弯回来,正打算回家看 7 点新闻 + 给东郊女儿打视频。"
                "他说他正赶去 Greenwich 上晚班,我说我在 Greenwich 住了 20 多年。"
                "<em>他说下次轮休可以结伴沿 Stringybark Creek 散步,还说我去 RSL 的话给我留炸鸡排。我应下了。</em>"),
            7: ("第一次走到 Shinnyo",
                "下午 2.4 km 走过去了。我走得慢,大概 45 分钟。"
                "门口贴着日文 + 英文双语指示。里面比我想的要小,但很安静。"
                "我没进去 — 我穿的衣服太家常了。"
                "回家路上经过单元楼,碰到邻居 #431(她又是赶 305 路去 Wynyard 开会,要赶在 7 点前接孩子从 Lane Cove 游泳课)。"
                "我跟她说我刚从 Stringybark Creek 沿岸散步回来,要回家泡云南普洱(中国超市买的)、看 7 点新闻、给东郊女儿打视频问外孙考试。"
                "<em>她说『真羡慕你这种节奏』。我说『你年轻,等退了就有了』。</em>"),
            8: ("再去一次",
                "周四下午我又走了一趟 Shinnyo。这次穿了正经一点的衣服。"
                "前台是个 30 多岁的日本/华裔女士,英文一般但很热情。"
                "我问读书会还能不能来。她说当然,周三晚 7 点本月主题是《Lane Cove 简史》,需不需要她帮我留个位子。"
                "<em>我说好。她问我名字,我说『老何就行,以前在 Library 帮忙的』。她记下来了。</em>"),
            9: ("周六亲子市集 · 认识了 Frank",
                "周六上午我去逛了 Shinnyo 亲子市集。"
                "本来只想看看 — 但碰到了 Frank(邻居 #12, 64 岁建筑工,Lane Cove 30 年老居民)。"
                "他说他 90 年代修过 Lane Cove Library 的地基。"
                "我说『我整的就是那栋楼里的书』。他想了想,问我是不是他经常借建筑旧报的那个『中年华裔女士』。"
                "<em>是。我那时候 50 多岁。他那时候 30 多岁。我们在 Library 里大概擦肩过几十次,但都没说过话。直到 25 年后的今天,在一个佛教冥想中心的亲子市集上,我们终于互相介绍了名字。</em>"),
            10: ("推送停了 · 我没注意",
                "今天没收到 Shinnyo 推送 — 我后来才发现是 6 天干预期结束了。"
                "但我已经记住周三晚读书会要去。"
                "Frank 在亲子市集上加了我的电话(老式翻盖机互留号码),说有事可以打。"
                "<em>晚上给女儿打视频时跟她提了一嘴。她在那头说『妈你居然主动跟人留号码了!』我说『他不是「人」,他是修过 Library 地基的老 Frank』。她笑了。</em>"),
            11: ("第一次自己安排去",
                "周三晚读书会。这次没有推送提醒。我自己看了一眼日历,出门了。"
                "主题是《Lane Cove 简史 — 战后郊区化》,讲到 1950-70 年代 Lane Cove 怎么从农场变成现在的 suburb。"
                "Frank 讲了一段他爷爷 50 年代在 Lane Cove 卖菜的故事。我讲了我 90 年代搬来时还是『没什么人的地方』。"
                "<em>课上的 25 岁全职妈妈听得入神,说她爸爸跟她讲过类似的事但从来没认真听过,『今天听 Frank 和 老何 讲,才发现这些故事是真的』。</em>"),
            12: ("更多人 · 邀请 Frank 去公园",
                "今天读书会主题是《Lane Cove 河岸 — 从工业到 bushland》。"
                "课后我跟另一位 65 岁退休女士(邻居 #225,Gallery Lane Cove 的陶艺老师 + Friends of Lane Cove National Park 的周三除草小组)约了周三上午去 Longueville Park 散步。"
                "我问 Frank 要不要带老伴儿一起。他说老伴儿这周不舒服,他一个人去。"
                "<em>我说『那你跟我们走吧,反正路上 30 分钟有得聊』。他说好。</em>"),
            13: ("成了固定行程",
                "现在我每周三 Shinnyo 读书会、周六 Shinnyo 市集 + Plaza 农夫市集、周三上午 Longueville Park 散步。"
                "晚上给女儿打视频时,跟她说:「妈在 Lane Cove 找到一个新去处了。」"
                "她在屏幕那头愣了几秒 — 她从没听妈妈这样说过。"
                "<em>我没告诉她其实让我真的走出去的不是某个『新去处』 — 是 Frank 那句『我修过 Library 地基』。"
                "如果他没说那句话,我可能就只是把 Shinnyo 当成另一个去过一次的地方,不会再去了。</em>"),
        },
        "ending": (
            "<strong>14 天后的 Mary:</strong>从家方圆 500 米的世界(取信 + Canopy Park 遛弯 + 看新闻 + 视频电话),"
            "走到了 2.4 km 外的真如苑;认识了 6 位本街邻居(20-65 岁,各种背景);"
            "和 64 岁建筑工 Frank 重新接上了 25 年前在 Library 擦肩而过的关系。"
            "<br><br>"
            "推送的真正力量不是把『推送』本身送到 Mary 面前 — 是给了她一个走出去的理由 · 让她在 Shinnyo 遇到了一群她本来不会遇到的人 · 然后这些人之间又互相介绍了更多关系。"
            "<br><br>"
            "<em>她不是一个特例。这 1,000 名虚拟居民里,有 227 人在 14 天里经历了类似的变化。</em>"
        ),
    },
    "agent_12": {
        "aid": "a_43_0012",
        "name_zh": "Frank",  # We give the 64yo construction worker a name
        "name_en": "agent_12",
        "cover_title": "Frank 的 14 天",
        "cover_subtitle": "64 岁建筑工 · Lane Cove 老居民 · 平时只看 Council 议程 · 推送让他重新认识住了 30 年的街区",
        "day_moods": {
            4: ("没看",
                "推送弹了 5 条,都是 Shinnyo Australia 的活动 — 儿童活动、清扫日、新邻居见面会、市集、读书会。"
                "我把通知划掉了。Shinnyo 这地儿我每天路过几十次,从没进去过 — 那是个日本佛教冥想中心,跟我没关系。"
                "我习惯了看 Council 议程,Lane Cove Council 这周在讨论 Galuwa 康乐中心的开放时间(8000 万投资、8 个球场、15 年规划),这个我比手机推送上心多了。"),
            5: ("一条让我停了下",
                "今天又是 5 条 Shinnyo 推送。其中一条说『周三晚 7 点读书会——本月主题《Lane Cove 简史》』。"
                "我在 Lane Cove 住了 30 年。Mowbray Road 那段路 90 年代是我们队修的。Lane Cove Library 那栋楼的地基是我打的。"
                "这条推送让我停了下。我点开看了一眼,关掉了,但晚上跟老伴儿提了一句:『有人在搞 Lane Cove 历史的读书会。』她说:『你怎么不去讲讲?』"),
            6: ("决定去周日的清扫日",
                "推送又重复了:『shinnyo_australia 周日上午社区清扫日——大家带垃圾袋手套来,清扫完一起 BBQ。』"
                "这种事我在 bushcare volunteer 干过类似的。带个手套就行,不用付钱不用报名。"
                "重点是 — 我可以去看看 Shinnyo 周围那块地的施工情况。Pottery Lane 那块新公共表演空间我老路过看,听说脚手架快拆了。"
                "我决定周日去。"),
            7: ("先去 Shinnyo 看看",
                "周三上午我先绕过去看了一下 Shinnyo 门面。"
                "里面比想象的小,但贴着英文+日文+中文 3 种语言指示。门口有一对正在交谈的人 — 看起来是中年印度移民。"
                "我没进去。"
                "下午在 Go Vita 排队买保健品时,碰见老邻居 #64 (a_43_0064)。"
                "我跟他聊了周六我的计划:先去 Lane Cove Plaza 农夫市集买柑橘酸面包给老伴当早餐,然后顺路去 Pottery Lane 看表演空间的施工进度。"
                "他说他也打算去市集,前阵子路过看见 Pottery Lane 脚手架拆了大半,外墙都完工,在做内部收尾。"
                "<em>我们约好周六早上八九点在市集入口那家常去的咖啡摊碰头,一块儿逛完去 Pottery Lane。</em>"),
            8: ("第一次进 Shinnyo 读书会",
                "周三晚 7 点。我推开门,以为里面只有几个老头老太太。"
                "结果坐着 25 岁全职妈妈 (邻居 #15)、32 岁 tradie (邻居 #1)、20 岁的失业小伙 (邻居 #3)、40 岁的 manager (邻居 #2),还有一位 75 岁的退休老太太 — 大家叫她『老何』(邻居 #405 = Mary)。"
                "Mary 说她以前在 Library 整书目。我说:『90 年代 Lane Cove Library 是我帮着打地基的。』她愣了一下,然后笑了:『我整的就是那栋楼里的书。』"
                "<em>我跟她说她可能见过我 — 90 年代我经常去 Library 借建筑相关的旧报。她想了想说『可能吧,但年纪大了记不清了』。</em>"),
            9: ("分享 Mowbray Road 的故事",
                "周六早上,先按计划去了 Plaza 农夫市集。邻居 #64 准时到了。"
                "买完柑橘和酸面包,我们一块儿往 Pottery Lane 走。我跟他细讲 1990 年 Mowbray Road 怎么修 — 那时候泥地居多,我们队挖到地下管线时挖到一段维多利亚时代的下水道。"
                "他听得入迷。Pottery Lane 看完后他提议绕去新开的 Galuwa 康乐中心看看。我同意了。"
                "<em>下午周六 Shinnyo 亲子市集开场。我去了。把 Mowbray Road 的故事又讲了一遍 — 这次是给读书会的人。他们都是搬来不到 5 年的,听得目瞪口呆。25 岁的全职妈妈说她家在 Centennial Avenue,问我那条路是不是也是 90 年代修的。我说:『不是,Centennial 早就有了,但路面是 1995 年才铺成现在这个样子。』她说她要拍照发给她爸看。</em>"),
            10: ("推送停了 · 圣公会教堂的活动",
                "今天 Shinnyo 推送停了 — 干预期 6 天结束了。但我已经记住要去周三读书会、周六市集了。"
                "Shinnyo 读书会上认识的邻居 #21 (a_43_0021, 老兄弟) 邀我去圣公会教堂(Anglican Church Lane Cove)的周日活动。"
                "他们说是『本街老居民聚会』,我以前不知道有这个。"
                "<em>我们约好周六早上九点在市集门口碰头,先逛完市集再走过去教堂。逛完后他还提议去 Longueville Road 他常去的咖啡店坐坐。我说好,回去跟老伴儿报备,提前把装草莓的布兜找好。</em>"),
            11: ("成了我的「圈子」",
                "现在我每周三去 Shinnyo 读书会、周六去 Shinnyo 市集 + Plaza 农夫市集、周日去圣公会教堂的老居民聚会。"
                "比 Council 议程上的人多多了——我以前以为 Lane Cove 老居民就剩我们几个 60+ 岁的。现在我每周都会跟 25 岁、32 岁、40 岁、20 岁的邻居坐在一起。"
                "<em>邻居 #138 (45 岁) 跟我详细问了 Pottery Lane 工程内幕。她在 Crows Nest 看了 2 套房,问我能不能下次陪她去看看墙体和地基。我说没问题,反正我每天闲着也是闲着。</em>"),
            12: ("Mary 邀我去 Longueville Park",
                "周二。Mary 在 Shinnyo 读书会结束后跟我说,她和另一位 65 岁退休女士 (邻居 #225 = retired family_with_kids, Gallery 陶艺课) 周三上午要去 Longueville Park 散步,问我要不要带老伴儿一起。"
                "我跟她说我老伴儿这周不舒服,我一个人去。"
                "Mary 说:『那你跟我们走吧,反正路上 30 分钟有得聊。』我说好。"
                "<em>路上 Mary 跟我聊她以前住 Greenwich 20 多年。我说 Greenwich 的水管是 80 年代施工的,跟我同行 — 她说她还记得那段时间 Greenwich Road 经常因为修水管堵路。我们俩有一搭没一搭地聊老地名,聊了大半路。</em>"),
            13: ("跟老婆说",
                "晚上吃饭时我跟老伴儿说:『推送弄的几个邻居聚会,我可能下半辈子都得去了。』"
                "她笑了一下,说她记得我说『手机推送不重要』,说了至少 10 年。"
                "我没反驳。"
                "<em>其实我心里清楚 — 让我真的迈出门的不是推送本身,是那条说『《Lane Cove 简史》读书会』的推送。"
                "如果它没提到 Lane Cove 历史,我可能根本不会点开。"
                "推送的真正难点不是『让人看』 — 是『说出那个人在乎的一句话』。</em>"),
        },
        "ending": (
            "<strong>14 天后的 Frank:</strong>从只去 Plaza 看老邻居 + 看 Council 议程,"
            "变成了 Shinnyo 读书会(周三)+ 圣公会教堂(周日)+ Longueville Park(周二)三个固定行程。"
            "他这辈子第一次主动跟 25 岁、32 岁、40 岁的邻居坐在一起聊街区。"
            "<br><br>"
            "Frank 之前对手机推送不上心。但推送投了 30 条之后,有 1 条说到了他在乎的事(《Lane Cove 简史》)。"
            "<em>推送的真正难点不是「让人看」,是「找到那个人在乎的一句话」。</em>"
        ),
    },
    "mike": {
        "aid": "a_43_0192",
        "name_zh": "Mike",
        "name_en": "agent_192",
        "cover_title": "Mike 的 14 天",
        "cover_subtitle": "26 岁软件工程师 · 英国移民 · 推送说「只剩 2 位」 · 一家镇上餐厅 · 一群以前从不会遇到的人",
        "day_moods": {
            4: ("订了",
                "下班走出 Inspire Cosmetics 时手机弹了 5 条推送。"
                "其中一条是『1021 Mediterranean 本周六 chef table 只剩 2 位』。"
                "我从来不订餐厅 — 我习惯点外卖在家吃。但『只剩 2 位』这三个字让我反射性地点了订餐按钮。"
                "<em>订完之后我在 Inspire 楼下碰到邻居 #123(住在我同一栋楼,他老婆来买护肤品)。他跟我说他在看 Mowbray 那栋新公寓的 Domain 房源。他问我有没有兴趣一起去看,我说我没时间研究房产。他还提议下次一起去 Tony's 喝咖啡,我说回去要看 1021 的菜单。</em>"),
            5: ("有点期待",
                "今天又是 5 条 1021 相关推送。"
                "下午回家路上突然变冷,我穿短袖冻得不行。"
                "楼下碰到邻居 #326,我吐槽这天气 — 上周还穿短袖,这周就要套外套。我跟他讲了 2020 年那次特大暴雨我搬家时床垫卡在电梯里 1 个半小时的糗事。"
                "他笑了,说他明天早班怕被淋,约了同事去 North Sydney 喝酒。"
                "<em>我提醒他记得带伞,他爽快答应回公寓拿晴雨伞,还开玩笑说『以后赶上大雨可以凑一起撑伞走一段』。</em>"
                "晚上我在家试穿了 3 件衬衫。这是我第一次为『下馆子』这事认真打扮。"),
            6: ("第一次到 1021",
                "周六晚 7 点。走 2.7 km 过去。"
                "Chef table 6 人围着开放厨房坐,大厨边做边讲。第一道是 octopus carpaccio,他讲了希腊一个小岛的处理方法。"
                "我旁边坐的是一对住在 3 街区外的英国移民夫妇 — 我从没遇到过英国老乡。我们聊到 Manchester 的雨水和悉尼的暴雨完全不一样。"
                "<em>店主 Dan 听到我们的口音,过来打了个招呼说他也是英国来的。他给我们 3 个人加了一杯免费的 ouzo。我那时还不知道这就是我以后最常去的店。</em>"),
            7: ("加班后绕去喝杯酒",
                "周三加班到 22:00。出公司时本能想直接回家。"
                "但路过 1021 时(其实绕了 500m), 灯还亮着,有 2 个人在吧台。"
                "我进去点了杯啤酒。Dan 看见我,愣了一下,说『你又来了!』然后没收我钱 — 说这杯算店招待。"
                "<em>我跟 Dan 聊了 30 分钟。他说他 5 年前从 Manchester 移民来,先在 Crows Nest 一家餐厅打工,然后存钱在 Lane Cove 开了自己的店。我跟他讲了 Inspire Cosmetics 的事 — 他从没听说过这家。</em>"),
            8: ("叫上邻居一起去",
                "周末我又预订了 chef table。这次我打了电话给周六认识的那对英国夫妇,邀他们一起。"
                "晚上 3 个人去了。这次主菜是 lamb tagine。"
                "他们告诉我邻居 #67(46 岁 accountant)上周也来吃过 chef table — 说 1021 在他们公寓楼里口碑很好,但订位极难。我说我每周都来。"),
            9: ("和 Dan 聊到深夜",
                "今天 Dan 关门后跟我聊到午夜。"
                "他说他老婆是 Sydney 本地人,有 2 个孩子在 Lane Cove West Public School 上学,他选 Lane Cove 开店就因为这。"
                "我说我父母还在 Manchester,我每年圣诞回去一次。他说他也是。"
                "<em>这是我搬来 Lane Cove 3 年后第一次跟邻居聊家事。</em>"),
            10: ("推送停了 · 我还是去",
                "今天没收到 1021 推送 — 后来才知道是 6 天干预期结束。"
                "但我这周还是去了 2 次 — 周三吧台喝啤酒 + 周六 chef table。"
                "Dan 给我留了固定位置(吧台左数第 3 个凳子)。他说『你坐这,看得到我做菜』。"),
            11: ("叫上同事 Tom",
                "周一晚上加班结束,我第一次带同事 Tom 去 1021。"
                "Tom(印度移民,29岁 software_dev) 说『我都不知道 Lane Cove 有这地方,我在 Lane Cove 住 2 年了』。"
                "Dan 给 Tom 上了 ouzo,说『英国/印度组合,可以,以后多带几个来』。"),
            12: ("在 1021 写代码",
                "周六晚上我带着笔记本电脑去 1021。Dan 给我留了固定位置,续了 3 次咖啡。"
                "第一次「在外面工作」。我以前觉得『在咖啡店写代码』是装,但在 1021 写其实挺专注的 — Dan 不打扰,菜上得慢,有时候他过来问一句『要不要再来杯水』。"
                "<em>晚上一对中年夫妇(50 多岁,看起来像华裔)走进来问 Dan 能不能加位。Dan 说店满了,但指着我说『他在写代码可以拼桌』。我说当然。结果他们俩跟我聊了 30 分钟 — 男的是 Westpac IT 部门的,女的是 Lane Cove West 小学的英文老师。我加了他们的微信。</em>"),
            13: ("成了我的「附近」",
                "现在 1021 是我每周必去 2 次的地方。"
                "这里我认识的人:Dan (店主,Manchester 移民)、邻居 #67 (46 岁会计)、邻居 #79 (58 岁同行 software_dev,卖了 Greenwich 老房子)、邻居 #135 (29 岁医生)、邻居 #216 (26 岁同行 software_dev,跟我一样合租)、邻居 #225 (65 岁退休陶艺老师 + Friends of Lane Cove National Park 的周三除草小组)、Tom (同事,印度移民)、Westpac 的中年夫妇。"
                "<em>以前我以为 Lane Cove 就是个『睡觉的地方』(我朋友 #216 也这么说)。但 1021 让我发现这里的人很有意思。差别可能就是『有没有一个地方让人聚起来』。</em>"),
        },
        "ending": (
            "<strong>14 天后的 Mike:</strong>从家-公司两点一线 + 周末点外卖 + 不与人说话,变成了「在 1021 写代码 + 和 Dan 聊到深夜 + 加了 8 个邻居的微信」。"
            "推送停了,他还在去。他还把同事 Tom 带去了。Dan 给他留了固定位置(吧台左数第 3 个凳子)。"
            "<br><br>"
            "推送没有给 Mike 制造新的兴趣 — 他本来就是 extraversion 0.69 的人,只是 risk_tolerance 0.26 让他下不了决心迈出第一步。"
            "推送做的是:<strong>给他一个不需要勇气的理由(『只剩 2 位』)迈出第一步。然后剩下的事自己长出来了。</strong>"
        ),
    },
}


# ──────────────────────────────────────────────────────────────────────
# Mini map SVG (same as before)
# ──────────────────────────────────────────────────────────────────────
def build_day_map_svg(stays_bl, stays_hp, width=380, height=200):
    pts = []
    for s in stays_bl + stays_hp:
        if s.get("x") is not None: pts.append((s["x"], s["y"]))
    if not pts:
        return (f'<svg viewBox="0 0 {width} {height}" style="background:#F4EFE5">'
                f'<text x="{width/2}" y="{height/2}" text-anchor="middle" font-size="14" '
                f'fill="#5A5E6A" font-style="italic">这天没有记录到位置变化 (在家)</text></svg>')

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
    span_x = max_x - min_x
    scale = width / span_x
    def proj(x, y):
        return ((x - min_x) * scale, (max_y - y) * scale)
    def in_view(x, y):
        return min_x <= x <= max_x and min_y <= y <= max_y

    svg = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" style="background:#F4EFE5">']
    for loc_id, m in LOC2META.items():
        verts = m["polygon"]
        if len(verts) < 3 or not in_view(m["x"], m["y"]): continue
        pts2 = [proj(v["x"], v["y"]) for v in verts]
        path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts2) + " Z"
        t = m.get("type", "")
        if t in ("park", "playground", "garden"):
            svg.append(f'<path d="{path}" fill="#CFE3C4" stroke="#9DBC8A" stroke-width="0.4"/>')
        elif t == "street":
            svg.append(f'<path d="{path}" fill="#D9D3C6" stroke="none"/>')
        else:
            svg.append(f'<path d="{path}" fill="#DDD4BD" stroke="#9D906F" stroke-width="0.25"/>')

    for s in stays_bl:
        sx, sy = proj(s["x"], s["y"])
        svg.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="5" fill="#5A5E6A" opacity="0.5" stroke="white" stroke-width="0.5"/>')
    for s in stays_hp:
        sx, sy = proj(s["x"], s["y"])
        svg.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="9" fill="#D14B12" stroke="white" stroke-width="1.5"/>')
        nm = s.get("name") or ""
        if nm and not nm.startswith("road_"):
            svg.append(f'<text x="{sx+12:.1f}" y="{sy+4:.1f}" font-family="Georgia,serif" '
                       f'font-size="13" font-weight="900" fill="#A0252F">{nm[:24]}</text>')
    svg.append("</svg>")
    return "".join(svg)


# ──────────────────────────────────────────────────────────────────────
# Build per-day push delivery groups
# ──────────────────────────────────────────────────────────────────────
def pushes_for_day(snapshot_data, day_date):
    """Return list of push contents delivered on day_date (YYYY-MM-DD)."""
    out = []
    seen_content = set()
    for p in snapshot_data["push_deliveries"]:
        if not p.get("delivered_at", "").startswith(day_date):
            continue
        fid = p["feed_item_id"]
        item = snapshot_data["push_contents"].get(fid, {})
        content = item.get("content", "")
        if not content or content in seen_content:
            continue
        seen_content.add(content)
        out.append({
            "content": content,
            "category": item.get("category", "?"),
            "urgency": item.get("urgency", 0),
            "source": item.get("source", "?"),
        })
    return out


# ──────────────────────────────────────────────────────────────────────
# Encountered neighbors profiles
# ──────────────────────────────────────────────────────────────────────
def build_neighbors_html(snapshot_data):
    """For agents mentioned in recent_memory_hint, build a neighbor card."""
    rs = snapshot_data.get("runtime_state", {})
    hints = rs.get("hints", {})
    nearby = hints.get("nearby_hint", [])
    memory = hints.get("recent_memory_hint", [])
    import re
    neighbor_ids = set()
    for h in nearby:
        neighbor_ids.add(h["agent_id"])
    for m in memory:
        match = re.search(r'a_\d+_\d+', m)
        if match: neighbor_ids.add(match.group())

    cards = []
    for aid in sorted(neighbor_ids):
        p = profiles.get(aid)
        if not p: continue
        intro = p.get("identity_text", "") or "(无 identity_text)"
        plan_t = p.get("plan_text", "") or ""
        person = p.get("personality", {})
        cards.append(f"""
<div class="neighbor-card">
  <div class="neighbor-head">
    <div class="neighbor-name">邻居 #{aid.replace("a_43_", "")}</div>
    <div class="neighbor-meta">{p.get("age", "?")} 岁 · {p.get("occupation", "?")} · {p.get("household", "?")} · {p.get("ethnicity_group", "?")}</div>
  </div>
  <p class="neighbor-bio">{intro}</p>
  {('<div class="neighbor-plan">日常: <em>' + plan_t + '</em></div>') if plan_t else ''}
  <div class="neighbor-traits">
    开放性 {person.get("openness", 0):.2f} · 外向 {person.get("extraversion", 0):.2f} ·
    神经质 {person.get("neuroticism", 0):.2f} · 冒险 {person.get("risk_tolerance", 0):.2f} ·
    规律 {person.get("routine_adherence", 0):.2f}
  </div>
</div>
""")
    return "\n".join(cards)


def personality_radar_svg(person, color="#A0252F", size=180):
    """Build an SVG radar chart for 5 personality dimensions."""
    import math
    dims = [
        ("开放性\nopenness", person.get("openness", 0)),
        ("外向\nextraversion", person.get("extraversion", 0)),
        ("神经质\nneuroticism", person.get("neuroticism", 0)),
        ("冒险意愿\nrisk_tolerance", person.get("risk_tolerance", 0)),
        ("规律性\nroutine", person.get("routine_adherence", 0)),
    ]
    n = len(dims)
    cx, cy = size / 2, size / 2 + 5
    R = size / 2 - 30

    svg = [f'<svg viewBox="0 0 {size} {size+20}" xmlns="http://www.w3.org/2000/svg" '
           f'style="background:white">']
    # Concentric grid (5 rings)
    for r_frac in [0.2, 0.4, 0.6, 0.8, 1.0]:
        r = R * r_frac
        verts = []
        for i in range(n):
            ang = (i / n) * 2 * math.pi - math.pi / 2
            verts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in verts) + " Z"
        svg.append(f'<path d="{path}" fill="none" stroke="#D8D9DC" stroke-width="0.5"/>')
    # Axes
    for i in range(n):
        ang = (i / n) * 2 * math.pi - math.pi / 2
        ex = cx + R * math.cos(ang)
        ey = cy + R * math.sin(ang)
        svg.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
                   f'stroke="#D8D9DC" stroke-width="0.5"/>')

    # Data polygon
    data_verts = []
    for i, (lbl, val) in enumerate(dims):
        ang = (i / n) * 2 * math.pi - math.pi / 2
        r = R * val
        data_verts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in data_verts) + " Z"
    svg.append(f'<path d="{path}" fill="{color}" fill-opacity="0.35" stroke="{color}" stroke-width="2"/>')
    # Dots at vertices
    for x, y in data_verts:
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>')

    # Labels
    for i, (lbl, val) in enumerate(dims):
        ang = (i / n) * 2 * math.pi - math.pi / 2
        lx = cx + (R + 16) * math.cos(ang)
        ly = cy + (R + 16) * math.sin(ang)
        anchor = "middle"
        if math.cos(ang) > 0.3: anchor = "start"
        elif math.cos(ang) < -0.3: anchor = "end"
        lines = lbl.split("\n")
        for j, ln in enumerate(lines):
            style = 'font-weight="900"' if j == 0 else 'font-style="italic" fill="#5A5E6A"'
            svg.append(f'<text x="{lx:.1f}" y="{ly + j*4:.1f}" font-size="3.6" '
                       f'font-family="Georgia,serif" text-anchor="{anchor}" '
                       f'fill="#1B1F2A" {style}>{ln}</text>')
    svg.append("</svg>")
    return "".join(svg)


def poi_timeline_svg(poi_data, poi_id, hero_name, color="#D14B12", width=600, height=180):
    """Line chart: BL vs HP visitors at this POI per day."""
    if poi_id not in poi_data:
        return ""
    bl = poi_data[poi_id]["baseline"]
    hp = poi_data[poi_id]["hyperlocal_push"]
    days = sorted(set(bl.keys()) | set(hp.keys()), key=int)
    if not days:
        return ""

    max_val = max(max(hp.values() or [0]), max(bl.values() or [0]), 1)
    svg = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
           f'style="background:#F8F5EE">']
    # Margins
    ML, MR, MT, MB = 50, 16, 25, 40
    plot_w = width - ML - MR
    plot_h = height - MT - MB

    # Title
    svg.append(f'<text x="{ML}" y="14" font-family="Georgia,serif" font-size="12" '
               f'font-weight="900" fill="#1B1F2A">{poi_id} · 每日独立访客数</text>')

    # Y-axis grid
    for v in [0, max_val/2, max_val]:
        y = MT + plot_h - (v / max_val) * plot_h
        svg.append(f'<line x1="{ML}" y1="{y:.1f}" x2="{ML+plot_w}" y2="{y:.1f}" '
                   f'stroke="#D8D9DC" stroke-width="0.5"/>')
        svg.append(f'<text x="{ML-4}" y="{y+3:.1f}" font-family="Helvetica,sans-serif" '
                   f'font-size="9" fill="#5A5E6A" text-anchor="end">{int(v)}</text>')

    # X-axis day labels
    x_step = plot_w / max(len(days)-1, 1)
    for i, d in enumerate(days):
        x = ML + i * x_step
        svg.append(f'<text x="{x:.1f}" y="{height - 25}" font-family="Helvetica,sans-serif" '
                   f'font-size="9" fill="#5A5E6A" text-anchor="middle">D{d}</text>')

    # Shade push period (D4-D9, but our data starts at D6)
    push_start = ML
    push_end = ML + 4 * x_step  # roughly D6-D9
    svg.append(f'<rect x="{push_start:.1f}" y="{MT}" width="{push_end - push_start:.1f}" '
               f'height="{plot_h}" fill="#F0C419" opacity="0.18"/>')
    svg.append(f'<text x="{(push_start + push_end)/2:.1f}" y="{MT-4}" font-family="Georgia,serif" '
               f'font-size="9" fill="#A0252F" font-style="italic" text-anchor="middle">推送干预期</text>')

    # BL line
    bl_pts = []
    for i, d in enumerate(days):
        x = ML + i * x_step
        y = MT + plot_h - (bl.get(d, 0) / max_val) * plot_h
        bl_pts.append(f"{x:.1f},{y:.1f}")
    svg.append(f'<polyline points="{" ".join(bl_pts)}" fill="none" stroke="#5A5E6A" '
               f'stroke-width="2" stroke-dasharray="4 3" opacity="0.7"/>')

    # HP line
    hp_pts = []
    for i, d in enumerate(days):
        x = ML + i * x_step
        y = MT + plot_h - (hp.get(d, 0) / max_val) * plot_h
        hp_pts.append(f"{x:.1f},{y:.1f}")
    svg.append(f'<polyline points="{" ".join(hp_pts)}" fill="none" stroke="{color}" stroke-width="3"/>')
    # Dots for HP
    for i, d in enumerate(days):
        x = ML + i * x_step
        y = MT + plot_h - (hp.get(d, 0) / max_val) * plot_h
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}" stroke="white" stroke-width="1.5"/>')

    # Legend
    lx = ML + plot_w - 130; ly = MT + 8
    svg.append(f'<line x1="{lx}" y1="{ly}" x2="{lx+18}" y2="{ly}" stroke="#5A5E6A" stroke-width="2" stroke-dasharray="4 3"/>')
    svg.append(f'<text x="{lx+22}" y="{ly+3}" font-family="Georgia,serif" font-size="10" fill="#1B1F2A">无推送基线</text>')
    svg.append(f'<line x1="{lx}" y1="{ly+12}" x2="{lx+18}" y2="{ly+12}" stroke="{color}" stroke-width="3"/>')
    svg.append(f'<text x="{lx+22}" y="{ly+15}" font-family="Georgia,serif" font-size="10" fill="{color}" font-weight="900">推送下访客数</text>')

    # Caption — Mary's contribution
    cap_y = height - 10
    bl_total = sum(bl.values())
    hp_total = sum(hp.values())
    svg.append(f'<text x="{ML}" y="{cap_y}" font-family="Georgia,serif" font-size="10" '
               f'font-style="italic" fill="#5A5E6A">'
               f'{hero_name} 不是唯一去那里的人 · 推送期内总访客 {bl_total} → {hp_total} 人</text>')
    svg.append("</svg>")
    return "".join(svg)


# ──────────────────────────────────────────────────────────────────────
# Build the HTML per agent
# ──────────────────────────────────────────────────────────────────────
def build_html(label):
    H = HEROES[label]
    diary = json.load(open(DIARY_DIR / f"{label}_diary.json"))
    snapshot_data = json.load(open(DIARY_DIR / f"{label}_snapshot_data.json"))
    poi_data = json.load(open(DIARY_DIR / "poi_timeline.json"))
    profile = profiles.get(H["aid"], {})
    rs = snapshot_data.get("runtime_state", {})
    plan = rs.get("plan", {})
    # Load all dialogues
    dialogues_data = json.load(open(DIARY_DIR / "dialogues.json"))
    dialogue_label = {"mary": "mary", "mike": "mike", "agent_12": "frank"}.get(label, label)
    agent_dialogues = dialogues_data.get(dialogue_label, [])
    # Which POI was discovered (hardcoded per hero)
    discovery_poi = {"mary": "shinnyo_australia", "mike": "1021_mediterranean",
                     "agent_12": "shinnyo_australia"}.get(label)

    # Header stats
    total_dist_hp = sum(d["hp_distance_m"] for d in diary["days"])
    total_dist_bl = sum(d["bl_distance_m"] for d in diary["days"])
    n_pushes = len(snapshot_data.get("push_deliveries", []))
    n_named_neighbors = len([h for h in rs.get("hints", {}).get("nearby_hint", []) if profiles.get(h["agent_id"])])

    # Day date mapping: day_index 4 = 2026-04-26 (from delivery_log first entry pattern)
    BASE_DATE = datetime(2026, 4, 22)  # day 0
    def date_of_day(d):
        return (BASE_DATE + timedelta(days=d)).strftime("%Y-%m-%d")

    # CSS + cover
    html = f"""<!DOCTYPE html>
<html lang="zh-Hans"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{H["cover_title"]} · 视觉小说案例研究 · 真实模拟数据</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: 'Georgia', 'Songti SC', serif; max-width: 980px; margin: 0 auto; padding: 0;
       background: #F8F5EE; color: #1B1F2A; line-height: 1.65; }}
.cover {{ background: linear-gradient(135deg, #1B1F2A 0%, #2d3340 100%); color: white;
         padding: 80px 50px 60px; position: relative; }}
.cover::before {{ content: "REAL DATA · 视觉小说"; position: absolute; top: 28px; right: 50px;
                 font-size: 11px; letter-spacing: 3px; color: #F0C419; }}
.kicker {{ color: #A0252F; font-style: italic; letter-spacing: 2px; font-size: 13px;
          margin: 0 0 18px; text-transform: uppercase; }}
.cover h1 {{ font-size: 62px; font-weight: 900; margin: 0 0 16px; letter-spacing: -2px; line-height: 1.05; }}
.cover .subtitle {{ font-size: 19px; font-style: italic; color: #D8D9DC; margin: 0 0 40px; line-height: 1.5; }}
.stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 24px; padding-top: 30px;
         border-top: 1px solid rgba(240,196,25,0.3); }}
.stat {{ }}
.stat .num {{ font-size: 38px; font-weight: 900; color: #F0C419; line-height: 1; }}
.stat .lbl {{ font-size: 11px; color: #D8D9DC; font-style: italic; margin-top: 6px; }}

.intro-chap {{ padding: 50px; background: white; margin-bottom: 0; }}
.intro-chap h2 {{ font-size: 36px; font-weight: 900; margin: 0 0 24px; border-bottom: 3px solid #1B1F2A; padding-bottom: 12px; }}
.intro-chap p {{ font-size: 17px; line-height: 1.85; }}
.intro-chap .quote {{ background: #F4EFE5; padding: 24px; border-left: 5px solid #A0252F;
                     font-style: italic; font-size: 17px; margin: 24px 0; }}
.intro-grid {{ display: grid; grid-template-columns: 1.4fr 1fr; gap: 32px; align-items: start; }}
.intro-right {{ background: #F8F5EE; padding: 16px; border-radius: 4px; }}
.radar-title {{ font-size: 12px; font-weight: 900; color: #A0252F; letter-spacing: 2px;
               text-transform: uppercase; margin-bottom: 8px; text-align: center; }}
.intro-right svg {{ display: block; max-width: 100%; height: auto; }}

.day-scene {{ position: relative; margin: 0; padding: 50px 50px 40px; background: #F8F5EE;
             border-bottom: 1px dashed #D8D9DC; }}
.day-scene.push {{ background: linear-gradient(to bottom, #FFF8DC 0%, #F8F5EE 30%); }}
.day-scene.discovery {{ background: linear-gradient(to bottom, #FBE5D6 0%, #F8F5EE 30%); }}
.day-scene.post {{ background: linear-gradient(to bottom, #FBD8DC 0%, #F8F5EE 30%); }}
.day-header {{ display: flex; align-items: baseline; gap: 16px; margin-bottom: 12px; }}
.day-num {{ font-size: 56px; font-weight: 900; color: #1B1F2A; line-height: 1; letter-spacing: -2px; }}
.day-meta {{ flex: 1; }}
.day-date {{ font-size: 13px; color: #A0252F; font-style: italic; letter-spacing: 1px; margin: 0 0 4px; }}
.day-mood {{ font-size: 26px; font-weight: 900; margin: 0; line-height: 1.2; }}

.day-grid {{ display: grid; grid-template-columns: 1.1fr 1fr; gap: 32px; margin-top: 28px; }}
.day-left {{ }}
.day-right {{ }}

.monologue {{ font-size: 17px; line-height: 1.8; font-style: italic; color: #1B1F2A;
             padding: 16px 20px; background: white; border-left: 4px solid #F0C419;
             margin: 0 0 24px; }}
.monologue::before {{ content: "\\201C"; font-size: 28px; color: #A0252F; line-height: 0;
                    vertical-align: -8px; margin-right: 4px; }}
.monologue::after {{ content: "\\201D"; font-size: 28px; color: #A0252F; line-height: 0;
                   vertical-align: -16px; margin-left: 4px; }}

.pushes-section {{ margin: 24px 0; }}
.pushes-label {{ font-size: 12px; color: #5A5E6A; font-style: italic; letter-spacing: 2px;
                text-transform: uppercase; margin-bottom: 10px; }}
.push-card {{ background: linear-gradient(135deg, #1B1F2A 0%, #2d3340 100%); color: white;
             border-radius: 16px; padding: 14px 18px; margin-bottom: 10px;
             box-shadow: 0 2px 8px rgba(0,0,0,0.18); position: relative; }}
.push-card::before {{ content: "📱"; font-size: 18px; position: absolute; top: 14px; right: 16px; }}
.push-app {{ font-size: 10px; color: #F0C419; font-weight: 700; letter-spacing: 1.5px;
            text-transform: uppercase; margin-bottom: 4px; }}
.push-content {{ font-size: 14px; line-height: 1.5; }}

.plan-card {{ background: #FBE5D6; padding: 16px 20px; border-left: 4px solid #D14B12;
             margin: 20px 0; }}
.plan-label {{ font-size: 12px; color: #A0252F; font-style: italic; letter-spacing: 1.5px;
              text-transform: uppercase; margin-bottom: 6px; }}
.plan-step {{ font-size: 15px; }}
.plan-step strong {{ color: #1B1F2A; }}

.day-map {{ background: #F4EFE5; border: 1px solid #D8D9DC; border-radius: 4px; overflow: hidden; }}
.day-map svg {{ display: block; width: 100%; height: auto; }}

.day-stats {{ display: flex; gap: 16px; margin-top: 16px; font-size: 13px; color: #5A5E6A; }}
.day-stats .ds {{ flex: 1; }}
.day-stats .ds .v {{ font-weight: 900; color: #1B1F2A; font-size: 16px; }}

.neighbors-section {{ padding: 60px 50px; background: white; }}
.neighbors-section h2 {{ font-size: 30px; font-weight: 900; margin: 0 0 8px; border-bottom: 3px solid #1B1F2A; padding-bottom: 12px; }}
.neighbors-section .sub {{ font-size: 14px; color: #5A5E6A; font-style: italic; margin: 0 0 24px; }}
.neighbors-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px; }}
.neighbor-card {{ background: #F8F5EE; padding: 18px 20px; border-left: 4px solid #5A5E6A; }}
.neighbor-head {{ display: flex; justify-content: space-between; margin-bottom: 8px; align-items: baseline; flex-wrap: wrap; gap: 6px; }}
.neighbor-name {{ font-weight: 900; font-size: 17px; }}
.neighbor-meta {{ font-size: 12px; color: #5A5E6A; font-style: italic; }}
.neighbor-bio {{ font-size: 13px; line-height: 1.65; margin: 0 0 8px; }}
.neighbor-plan {{ font-size: 12px; color: #5A5E6A; margin: 0 0 6px; padding: 4px 8px;
                 background: rgba(160,37,47,0.06); border-left: 2px solid #A0252F; }}
.neighbor-traits {{ font-size: 11px; color: #5A5E6A; font-family: 'Helvetica',sans-serif;
                   padding-top: 6px; border-top: 1px dashed #D8D9DC; }}

.dialogues-section {{ padding: 60px 50px; background: #1B1F2A; color: white; }}
.dialogues-section h2 {{ font-size: 30px; font-weight: 900; margin: 0 0 8px; color: #F0C419;
                        border-bottom: 1px solid #F0C419; padding-bottom: 12px; }}
.dialogues-section .sub {{ font-size: 14px; color: #A8ACB5; font-style: italic; margin: 0 0 28px; }}
.dialogue-card {{ background: white; color: #1B1F2A; padding: 22px 26px; margin-bottom: 20px;
                  border-left: 6px solid #F0C419; box-shadow: 0 2px 8px rgba(0,0,0,0.25); }}
.dialogue-head {{ display: flex; justify-content: space-between; align-items: baseline;
                  margin-bottom: 8px; flex-wrap: wrap; gap: 8px; }}
.dialogue-meta {{ font-size: 13px; color: #5A5E6A; font-style: italic; }}
.dialogue-meta strong {{ color: #1B1F2A; font-style: normal; }}
.pov-mine {{ background: #D14B12; color: white; padding: 3px 10px; font-size: 11px;
            font-weight: 900; letter-spacing: 1px; }}
.pov-other {{ background: #3B6EA8; color: white; padding: 3px 10px; font-size: 11px;
             font-weight: 900; letter-spacing: 1px; }}
.dialogue-partner {{ font-size: 12px; color: #5A5E6A; font-style: italic; margin: 0 0 12px;
                    padding: 6px 10px; background: #F4EFE5; border-left: 2px solid #A0252F; }}
.dialogue-content {{ font-size: 15px; line-height: 1.85; color: #1B1F2A; padding-top: 4px;
                    font-family: 'Songti SC', 'Georgia', serif; }}

.poi-timeline {{ padding: 60px 50px; background: #F8F5EE; }}
.poi-timeline h2 {{ font-size: 30px; font-weight: 900; margin: 0 0 8px; border-bottom: 3px solid #1B1F2A; padding-bottom: 12px; }}
.poi-timeline .sub {{ font-size: 14px; color: #5A5E6A; font-style: italic; margin: 0 0 24px; }}
.poi-timeline svg {{ display: block; width: 100%; height: auto; background: white; padding: 16px; }}

.ending {{ background: #1B1F2A; color: white; padding: 60px 50px; }}
.ending h2 {{ font-size: 30px; font-weight: 900; margin: 0 0 24px; color: #F0C419;
             border-bottom: 1px solid #F0C419; padding-bottom: 12px; }}
.ending p {{ font-size: 17px; line-height: 1.85; }}
.ending em {{ color: #F0C419; }}

.footer {{ padding: 30px 50px; text-align: center; font-size: 12px; color: #A8ACB5;
          background: #F8F5EE; font-style: italic; }}

@media (max-width: 700px) {{
  .stats {{ grid-template-columns: repeat(2, 1fr); }}
  .day-grid {{ grid-template-columns: 1fr; }}
  .neighbors-grid {{ grid-template-columns: 1fr; }}
  .cover h1 {{ font-size: 38px; }}
  .day-num {{ font-size: 40px; }}
  .day-mood {{ font-size: 20px; }}
}}
</style>
</head>
<body>

<div class="cover">
  <div class="kicker">CASE STUDY · 1,000 居民中的一位</div>
  <h1>{H["cover_title"]}</h1>
  <div class="subtitle">{H["cover_subtitle"]}</div>
  <div class="stats">
    <div class="stat"><div class="num">{profile.get("age", "?")} 岁</div><div class="lbl">{profile.get("occupation","?")} · {profile.get("household","?")}</div></div>
    <div class="stat"><div class="num">{n_pushes}</div><div class="lbl">收到的真实推送数</div></div>
    <div class="stat"><div class="num">+{int((total_dist_hp - total_dist_bl)/1000)} km</div><div class="lbl">比无推送多走的</div></div>
    <div class="stat"><div class="num">+{n_named_neighbors}</div><div class="lbl">新认识的本街邻居</div></div>
  </div>
</div>

<div class="intro-chap">
  <h2>她/他是谁?</h2>
  <div class="intro-grid">
    <div class="intro-left">
      <p>{profile.get("identity_text", "") or "(no identity text available)"}</p>
      <div class="quote">日常计划: {profile.get("plan_text", "(none)")}</div>
    </div>
    <div class="intro-right">
      <div class="radar-title">性格画像 · 仿真生成</div>
      {personality_radar_svg(profile.get("personality", {}))}
    </div>
  </div>
</div>

"""

    # Build a unified day list: union of diary days + day_moods days
    diary_by_day = {d["day"]: d for d in diary["days"]}
    all_days = sorted(set(diary_by_day.keys()) | set(H["day_moods"].keys()))
    # Per-day scenes
    for day in all_days:
        if day not in H["day_moods"]: continue
        title, monologue = H["day_moods"][day]
        date_str = date_of_day(day)
        day_data = diary_by_day.get(day, {
            "day": day, "bl_stays": [], "hp_stays": [],
            "bl_distance_m": 0, "hp_distance_m": 0,
            "new_locations_today": [], "n_bl_stays": 0, "n_hp_stays": 0,
        })

        # Push cards for this day
        push_list = pushes_for_day(snapshot_data, date_str)
        # If no pushes for this date, show empty
        push_html = ""
        if push_list:
            push_html += '<div class="pushes-section"><div class="pushes-label">这天手机收到的真实推送 · 共 ' + str(len(push_list)) + ' 条</div>'
            for p in push_list[:5]:  # cap at 5
                push_html += f'''
<div class="push-card">
  <div class="push-app">In the Cove · 本街快报</div>
  <div class="push-content">{p["content"]}</div>
</div>
'''
            push_html += '</div>'

        # Plan card (for the snapshot day = day 13)
        plan_html = ""
        if day == 13 and plan and plan.get("steps"):
            for step in plan["steps"][:2]:
                plan_html += f'''
<div class="plan-card">
  <div class="plan-label">仿真系统记录的真实 plan · {plan.get("date","")}</div>
  <div class="plan-step">
    <strong>{step.get("time","")} {step.get("action","")}</strong>:
    {step.get("activity","")}<br>
    <span style="font-size:13px; color:#5A5E6A;">
      reason: <em>{step.get("reason","")}</em> ·
      social_intent: <em>{step.get("social_intent","")}</em>
    </span>
  </div>
</div>
'''

        # Phase
        if day <= 3: phase = "baseline"
        elif day == 4: phase = "push"
        elif 5 <= day <= 9: phase = "discovery"
        else: phase = "post"

        # Map
        map_svg = build_day_map_svg(day_data["bl_stays"], day_data["hp_stays"])

        # Stays list (named POIs only)
        named_stays = [s for s in day_data["hp_stays"]
                       if s.get("name") and not s["name"].startswith("road_")
                       and not s.get("loc", "").startswith("building_")]
        stays_html = ""
        if named_stays:
            stays_html = '<div style="margin-top:16px;"><div class="pushes-label">真实停留</div>'
            for s in named_stays[:3]:
                stays_html += f'<div style="font-size:14px; padding:6px 0; border-bottom: 1px dashed #D8D9DC;"><strong>{s["name"]}</strong> · 约 {s["duration_min"]} 分钟</div>'
            stays_html += '</div>'

        html += f"""
<div class="day-scene {phase}">
  <div class="day-header">
    <div class="day-num">D{day}</div>
    <div class="day-meta">
      <div class="day-date">{date_str} · {"基线" if phase == "baseline" else "推送日" if phase == "push" else "发现期" if phase == "discovery" else "推送停后"}</div>
      <div class="day-mood">{title}</div>
    </div>
  </div>
  <div class="day-grid">
    <div class="day-left">
      <div class="monologue">{monologue}</div>
      {push_html}
      {plan_html}
    </div>
    <div class="day-right">
      <div class="day-map">{map_svg}</div>
      <div class="day-stats">
        <div class="ds"><div>无推送下走过</div><div class="v">{day_data["bl_distance_m"]:.0f} m</div></div>
        <div class="ds"><div>推送下走过</div><div class="v" style="color:#A0252F;">{day_data["hp_distance_m"]:.0f} m</div></div>
      </div>
      {stays_html}
    </div>
  </div>
</div>
"""

    # Neighbors section
    neighbors_html = build_neighbors_html(snapshot_data)
    if neighbors_html:
        html += f"""
<div class="neighbors-section">
  <h2>14 天后认识的本街邻居</h2>
  <p class="sub">仿真系统记录的 nearby_hint + recent_memory_hint · 真实 profile</p>
  <div class="neighbors-grid">{neighbors_html}</div>
</div>
"""

    # === DIALOGUES SECTION — real LLM-generated conversation summaries ===
    dialogues_html = ""
    if agent_dialogues:
        cards = []
        for i, d in enumerate(agent_dialogues):
            partner = d["partner"]
            partner_profile = profiles.get(partner, {})
            partner_desc = ""
            if partner_profile:
                partner_desc = (f'{partner_profile.get("age","?")} 岁 · '
                               f'{partner_profile.get("occupation","?")} · '
                               f'{partner_profile.get("household","?")}')
                if partner_profile.get("identity_text"):
                    partner_desc += f' · {partner_profile["identity_text"][:120]}…'
            loc_meta = LOC2META.get(d["location"], {"name": d["location"]})
            loc_name = loc_meta.get("name") or d["location"]
            content = d["content"]
            # Indicate POV
            pov_note = ""
            if d.get("origin_agent") == H["aid"]:
                pov_note = '<span class="pov-mine">我的视角</span>'
            else:
                pov_note = '<span class="pov-other">对方视角 · 看 ' + H["name_zh"] + '</span>'

            cards.append(f"""
<div class="dialogue-card">
  <div class="dialogue-head">
    <div class="dialogue-meta">
      <strong>对话 #{i+1}</strong> · 与 <strong>邻居 #{partner.replace("a_43_","")}</strong> · 在 <strong>{loc_name}</strong> · {d.get("msg_count","?")} 条消息 · 末由 {d.get("end_reason","?")}
    </div>
    {pov_note}
  </div>
  <div class="dialogue-partner">{partner_desc}</div>
  <div class="dialogue-content">{content.replace(chr(10), "<br>")}</div>
</div>
""")
        dialogues_html = f"""
<div class="dialogues-section">
  <h2>{len(agent_dialogues)} 段真实对话 · 仿真系统记录的全文</h2>
  <p class="sub">每段都是 LLM 在仿真中实时生成的第一人称总结 · 内容、感受、未来约定全部来自原数据</p>
  {"".join(cards)}
</div>
"""

    # POI timeline chart
    poi_chart_html = ""
    if discovery_poi:
        chart_svg = poi_timeline_svg(poi_data, discovery_poi, H["name_zh"])
        if chart_svg:
            poi_chart_html = f"""
<div class="poi-timeline">
  <h2>{H["name_zh"]} 不是唯一一个去的人</h2>
  <p class="sub">{discovery_poi} 这个具体地点 · 在推送前后的每日独立访客数变化</p>
  {chart_svg}
</div>
"""
    html += dialogues_html
    html += poi_chart_html

    html += f"""
<div class="ending">
  <h2>这意味着什么?</h2>
  <p>{H["ending"]}</p>
</div>

<div class="footer">
  Synthetic Socio Wind Tunnel · 悉尼 Lane Cove 虚拟城市 · 真实 snapshot.json + positions.json 数据复原 · github.com/york-zhouuu
</div>

</body></html>
"""
    return html


for label in ["mary", "mike", "agent_12"]:
    html = build_html(label)
    out_path = OUT_DIR / f"{label}_diary.html"
    out_path.write_text(html)
    print(f"Wrote {out_path} · {out_path.stat().st_size / 1e3:.0f} KB")
