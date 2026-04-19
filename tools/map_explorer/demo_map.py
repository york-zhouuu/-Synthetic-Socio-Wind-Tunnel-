"""
新苑里社区 — Fictional demo scenario for the Map Explorer UI.

Hand-built via `RegionBuilder` plus preset knowledge maps and social
traces demonstrating information asymmetry between agents. Entirely
decoupled from Lane Cove production data.

Was previously co-located with production Lane Cove code in
`tools/map_explorer/mock_map.py`; separated during the
`tidy-project-layout` change so the demo can be retired independently
of the real-world scenario.

Public API:
    create_atlas() -> Atlas
    create_demo_knowledge_maps(atlas) -> dict[str, AgentKnowledgeMap]
    create_ledger_with_demo_knowledge(atlas) -> Ledger
"""
from __future__ import annotations

from synthetic_socio_wind_tunnel.atlas.service import Atlas
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.atlas.models import (
    BorderType, Material,
)
from synthetic_socio_wind_tunnel.ledger.service import Ledger
from synthetic_socio_wind_tunnel.ledger.models import (
    AgentKnowledgeMap,
    AgentLocationKnowledge,
    LocationFamiliarity,
)


F = LocationFamiliarity


def create_atlas() -> Atlas:
    """Build the demo neighborhood Atlas."""

    builder = RegionBuilder("xin_yuan_li", "新苑里社区")

    # ─────────────────────────────────────────────
    # OLD SIDE (west, x: 0–185)
    # ─────────────────────────────────────────────

    # Chen's apartment block (旧楼)
    (builder
        .add_building("chen_home", "新苑里7号楼", building_type="residential")
        .polygon([(5, 30), (55, 30), (55, 90), (5, 90)])
        .floors(6)
        .building_description("建于1990年代的六层砖混住宅楼，外墙已有裂缝，一楼有几家小店面。走廊昏暗，晾晒的衣物从窗外延伸出来。")
        .sounds("楼道里邻居聊天声", "楼上小孩奔跑声", "远处菜市场叫卖声")
        .smells("饭菜香", "霉味", "楼道清洁剂")
        .add_affordance("rest", time_range=(0, 24), description="居民楼，需凭门禁卡进入")
        .add_affordance("socialize", time_range=(6, 22), description="楼道、单元门口是邻居聚集闲聊之处")
        .entry_signals(
            visible_from_street=("破旧的单元门", "锈迹斑斑的信箱", "晾衣架上的衣物"),
            signage=("新苑里7号", "门禁系统已损坏请拨打物业"),
            facade_description="六层砖混结构，外墙脱落，底层有报刊亭和修鞋摊。",
        )
        .end_building()
    )

    # Old wet market (旧菜市场)
    (builder
        .add_building("old_market", "新苑菜市场", building_type="market")
        .polygon([(60, 25), (135, 25), (135, 85), (60, 85)])
        .floors(1)
        .building_description("开放式菜市场，摊位密集，上午最为热闹。猪肉摊、蔬菜摊、豆腐摊，每个摊主都认识周围的常客。地面湿滑，有积水。")
        .sounds("摊主吆喝声", "讨价还价声", "刀剁砧板声", "广播类歌曲")
        .smells("鱼腥味", "新鲜蔬菜气息", "猪肉血腥味", "香料")
        .active_hours(5, 13)
        .add_affordance("buy_food", time_range=(5, 13), requires=("payment",),
                        language_of_service=("Mandarin", "Hokkien"),
                        description="猪肉蔬菜豆腐鸡蛋，本地价格。大部分摊主只说普通话和闽南语。")
        .add_affordance("socialize", time_range=(5, 13),
                        description="熟客之间互相认识，买菜顺带聊天是常态")
        .entry_signals(
            visible_from_street=("喧闹的摊位", "悬挂的猪肉", "排队的本地居民"),
            signage=("新苑菜市场", "营业时间 05:00-13:00", "各摊位手写价格牌（普通话）"),
            price_visible="猪肉约¥28/斤，蔬菜¥3-8/斤",
            facade_description="无门的开放式入口，铁皮雨棚，地面长期潮湿。",
        )
        .end_building()
    )

    # Community Center (社区活动中心)
    (builder
        .add_building("community_center", "新苑社区活动中心", building_type="community_center")
        .polygon([(5, 100), (90, 100), (90, 155), (5, 155)])
        .floors(2)
        .building_description("政府运营的社区活动中心，一楼有棋牌室和老年活动室，二楼有小型图书室和会议室。墙上贴满社区通知和健康宣传海报。")
        .sounds("麻将声", "老人聊天声", "广播体操音乐", "儿童课外班声音")
        .smells("老旧建筑气息", "消毒水", "茶水")
        .active_hours(8, 20)
        .add_affordance("socialize", time_range=(8, 20),
                        language_of_service=("Mandarin",),
                        description="老年活动室，棋牌、看报纸，主要是退休居民")
        .add_affordance("rest", time_range=(8, 20), description="免费开放给社区居民")
        .add_affordance("work", time_range=(9, 17),
                        description="二楼小型图书室，安静，有桌椅")
        .entry_signals(
            visible_from_street=("开着的大门", "门口下棋的老人", "宣传栏"),
            signage=("新苑社区活动中心", "欢迎居民入内", "老年活动室 →", "免费Wi-Fi（仅限居民）"),
            facade_description="两层白色瓷砖建筑，大门常开，门口有长椅，老人经常在此聚集。",
        )
        .end_building()
    )

    # Small repair shop (修理铺)
    (builder
        .add_building("repair_shop", "老王修理铺", building_type="shop")
        .polygon([(95, 100), (140, 100), (140, 135), (95, 135)])
        .floors(1)
        .building_description("家电修理和配钥匙，老板王师傅在此做了二十年。门口摆着各种旧家电零件。")
        .sounds("电钻声", "收音机", "老板与客人交谈")
        .smells("机油", "电焊烟")
        .active_hours(8, 19)
        .add_affordance("shop", time_range=(8, 19), requires=("payment",),
                        language_of_service=("Mandarin",),
                        description="家电维修、配钥匙、小五金，现金为主")
        .entry_signals(
            visible_from_street=("门口堆放的旧家电", "手写价格单"),
            signage=("修理·配钥匙", "手写：电风扇维修¥30起"),
            price_visible="维修¥30起",
            facade_description="低矮平房，木门，玻璃上贴满手写服务价目。",
        )
        .end_building()
    )

    # Old teahouse (老茶馆)
    (builder
        .add_building("old_teahouse", "同兴茶馆", building_type="cafe")
        .polygon([(5, 165), (75, 165), (75, 215), (5, 215)])
        .floors(1)
        .building_description("经营三十年的老茶馆，木质桌椅，小茶壶。常客都是附近退休居民，喝茶、看报、打牌。老板娘认识每一个常客。")
        .sounds("茶壶蒸汽声", "报纸翻动声", "麻将牌碰击声", "粤曲收音机")
        .smells("茶香", "烟草味", "老木头气息")
        .active_hours(6, 20)
        .add_affordance("rest", time_range=(6, 20), requires=("payment",),
                        language_of_service=("Mandarin", "Cantonese"),
                        description="喝茶坐一上午，茶位费¥8-15，不赶人")
        .add_affordance("socialize", time_range=(6, 20),
                        description="熟人圈子，外来者会被打量，但不会被排斥")
        .entry_signals(
            visible_from_street=("老旧木招牌", "门口坐着喝茶的老人", "窗内昏黄灯光"),
            signage=("同兴茶馆", "茶位¥8"),
            price_visible="茶位¥8起",
            facade_description="单层瓦顶建筑，木格窗，门帘半掩，有茶香飘出。",
        )
        .end_building()
    )

    # ─────────────────────────────────────────────
    # NEW SIDE (east, x: 235–420)
    # ─────────────────────────────────────────────

    # Sunrise Café (新式咖啡馆)
    (builder
        .add_building("sunrise_cafe", "Sunrise Café", building_type="cafe")
        .polygon([(240, 30), (310, 30), (310, 90), (240, 90)])
        .floors(2)
        .building_description("精品咖啡馆，2019年开业。玻璃幕墙，工业风装修，专注手冲咖啡。笔记本电脑用户居多，有独立工作区。提供英文和中文菜单。")
        .sounds("咖啡机研磨声", "轻音乐", "英语和普通话混杂的交谈", "键盘打字声")
        .smells("新鲜咖啡香", "烘焙气息")
        .active_hours(7, 22)
        .add_affordance("buy_coffee", time_range=(7, 22), requires=("payment",),
                        capacity=45,
                        language_of_service=("English", "Mandarin"),
                        description="精品手冲咖啡，拿铁¥38，美式¥28，提供英文菜单")
        .add_affordance("work", time_range=(7, 22), requires=("payment",),
                        capacity=45,
                        description="Wi-Fi 100Mbps，插座充足，适合远程办公")
        .add_affordance("socialize", time_range=(7, 22),
                        description="开放式社交环境，但主要是陌生人共处")
        .entry_signals(
            visible_from_street=("玻璃幕墙", "内部笔记本用户", "咖啡师在吧台工作", "排队人群"),
            signage=("SUNRISE CAFÉ", "Wi-Fi Available", "英文/中文菜单贴在橱窗外"),
            price_visible="咖啡¥28–48，蛋糕¥35起",
            facade_description="全透明玻璃立面，工业风铁艺招牌，内部灯光明亮，白天可清晰看到内部。",
        )
        .end_building()
    )

    # Coworking space (联合办公)
    (builder
        .add_building("cowork", "WeSpace 联合办公", building_type="coworking")
        .polygon([(240, 100), (340, 100), (340, 175), (240, 175)])
        .floors(3)
        .building_description("三层联合办公空间，提供固定工位和灵活工位。一楼是开放工作区，二楼是会议室，三楼是私密工位区。需要会员卡或日票。")
        .sounds("键盘声", "低声电话会议", "通风系统白噪音")
        .smells("空调循环空气", "咖啡机")
        .active_hours(7, 22)
        .add_affordance("work", time_range=(7, 22),
                        requires=("membership",),
                        language_of_service=("English", "Mandarin"),
                        capacity=120,
                        description="日票¥88，月卡¥1200。高速Wi-Fi，打印机，会议室可预订。")
        .entry_signals(
            visible_from_street=("企业logo墙", "刷卡门禁", "通过玻璃可见工作的人"),
            signage=("WeSpace", "Day Pass ¥88", "Members Only After 22:00"),
            price_visible="日票¥88，月卡¥1200",
            facade_description="现代写字楼风格，玻璃门禁，门厅有前台，非会员无法直接进入。",
        )
        .end_building()
    )

    # Boutique apartments (精品公寓)
    (builder
        .add_building("boutique_apts", "新苑里精品公寓", building_type="residential")
        .polygon([(350, 25), (415, 25), (415, 115), (350, 115)])
        .floors(12)
        .building_description("2021年建成的高层精品公寓，主要租给外籍人士和科技从业者。门禁严格，有专属门卫。内有健身房和屋顶花园。")
        .sounds("电梯运行声", "安静的走廊")
        .smells("空气清新剂", "洗涤剂")
        .add_affordance("rest", time_range=(0, 24), requires=("membership",),
                        description="长租公寓，需签约，月租¥8000起")
        .entry_signals(
            visible_from_street=("玻璃幕墙大堂", "制服门卫", "门禁系统"),
            signage=("新苑里精品公寓", "访客请登记"),
            facade_description="十二层玻璃幕墙公寓，大堂装修现代，24小时门卫。",
        )
        .end_building()
    )

    # Brunch restaurant (早午餐)
    (builder
        .add_building("brunch_place", "The Table 早午餐", building_type="cafe")
        .polygon([(350, 130), (415, 130), (415, 195), (350, 195)])
        .floors(1)
        .building_description("北欧风格早午餐餐厅，全英文菜单，周末需排队。主要客群为外籍人士和年轻白领。")
        .sounds("轻松背景音乐", "英语为主的交谈", "餐具碰撞声")
        .smells("烤面包香", "咖啡", "培根")
        .active_hours(8, 16)
        .add_affordance("buy_food", time_range=(8, 16), requires=("payment",),
                        language_of_service=("English",),
                        description="全英文菜单，牛油果吐司¥68，班尼迪克蛋¥78。周末排队约40分钟。")
        .entry_signals(
            visible_from_street=("等待区坐着的人", "粉笔黑板菜单", "北欧风装修"),
            signage=("THE TABLE", "Brunch 08:00-16:00", "Walk-ins Welcome"),
            price_visible="主食¥58–88",
            facade_description="白色外墙，落地窗，木质招牌，门口有等待长椅。",
        )
        .end_building()
    )

    # Artisan grocery (精品超市)
    (builder
        .add_building("artisan_grocery", "Green Basket 精品食材", building_type="shop")
        .polygon([(240, 190), (310, 190), (310, 250), (240, 250)])
        .floors(1)
        .building_description("进口食材和有机蔬菜，也卖精品零食和葡萄酒。价格是旁边菜市场的3-5倍，但有英文标签和网上订单服务。")
        .sounds("轻柔背景音乐", "冰柜运转声", "英文/普通话服务声")
        .smells("新鲜有机蔬菜", "咖啡豆")
        .active_hours(9, 21)
        .add_affordance("buy_food", time_range=(9, 21), requires=("payment",),
                        language_of_service=("English", "Mandarin"),
                        description="进口有机食材，牛油果¥25/个，有机鸡蛋¥35/盒。支持外卖和会员积分。")
        .entry_signals(
            visible_from_street=("整洁的货架陈列", "英文价格标签", "蔬菜展示区"),
            signage=("Green Basket", "Organic & Import", "Free Delivery Above ¥200"),
            price_visible="有机蔬菜¥15-45",
            facade_description="玻璃橱窗展示新鲜蔬菜，绿色主题装修，干净整洁。",
        )
        .end_building()
    )

    # ─────────────────────────────────────────────
    # RAILWAY CORRIDOR (中间地带, x: 185–235)
    # ─────────────────────────────────────────────

    (builder
        .add_building("railway_underpass", "铁路涵洞通道", building_type="street")
        .polygon([(185, 115), (235, 115), (235, 150), (185, 150)])
        .floors(1)
        .building_description("连接新旧两侧的铁路涵洞，灯光昏暗，有涂鸦，经常有人骑车穿越。步行约1分钟。")
        .sounds("火车驶过的震动声", "回声", "鸽子声")
        .smells("潮湿混凝土", "柴油")
        .add_affordance("transit", time_range=(0, 24),
                        description="步行或骑行穿越，全天开放，但夜间较暗")
        .entry_signals(
            visible_from_street=("低矮的混凝土拱顶", "涂鸦", "对面可见"),
            signage=("限高3.5m",),
            facade_description="混凝土涵洞，两侧有照明，但灯泡经常损坏。",
        )
        .end_building()
    )

    # ─────────────────────────────────────────────
    # OUTDOOR AREAS
    # ─────────────────────────────────────────────

    # Old side main street
    (builder
        .add_street("old_main_st", "民生路（旧区段）", road_name="民生路")
        .polygon([(5, 0), (185, 0), (185, 28), (5, 28)])
        .segment_index(0)
        .outdoor_description("旧区主干道，路面有破损，两侧是低矮店面和行道树。早上有早点摊，白天有电动车穿行。")
        .sounds("电动车喇叭声", "早点摊叫卖声", "施工远声")
        .smells("油条炸香", "尾气", "行道树")
        .add_affordance("transit", time_range=(0, 24), description="主要行人和非机动车道")
        .add_affordance("buy_food", time_range=(6, 10),
                        language_of_service=("Mandarin",),
                        description="早晨路边摊：油条¥2，豆浆¥3，包子¥2")
        .entry_signals(
            facade_description="双向两车道，两侧行道树，路面不平整，有共享单车停放点。"
        )
        .end_outdoor()
    )

    # Old side park
    (builder
        .add_outdoor("old_park", "民生路街心花园", area_type="park")
        .polygon([(5, 220), (140, 220), (140, 305), (5, 305)])
        .surface("concrete")
        .vegetation(0.4)
        .outdoor_description("旧式街心花园，铺装广场和少量绿化。清晨有大妈跳广场舞，下午老人在石凳上乘凉。有健身器材区。")
        .sounds("广场舞音乐", "鸟叫", "老人聊天", "儿童玩耍")
        .smells("绿植", "泥土")
        .add_affordance("rest", time_range=(5, 22), description="公共开放空间，免费")
        .add_affordance("exercise", time_range=(5, 22), description="健身器材区，广场舞区，太极拳")
        .add_affordance("socialize", time_range=(5, 22), description="社区社交中心，熟人聚集地")
        .entry_signals(
            visible_from_street=("在跳舞的大妈", "健身器材", "石凳上的老人"),
            facade_description="开放式公园，无围墙，有铁艺栏杆标识。",
        )
        .end_outdoor()
    )

    # New side main street
    (builder
        .add_street("new_main_st", "创新路（新区段）", road_name="创新路")
        .polygon([(235, 0), (420, 0), (420, 28), (235, 28)])
        .segment_index(0)
        .outdoor_description("新区主干道，路面平整，两侧有精品店和咖啡馆。共享单车整齐停放，路边有咖啡外带客人。")
        .sounds("轻音乐从商店飘出", "英语交谈", "外卖骑手呼叫声")
        .smells("咖啡", "烘焙")
        .add_affordance("transit", time_range=(0, 24), description="主要步行街道")
        .entry_signals(
            facade_description="双向两车道，路面平整，两侧有精品门店，共享单车停放整齐。"
        )
        .end_outdoor()
    )

    # Pocket park new side
    (builder
        .add_outdoor("pocket_park", "创新路口袋公园", area_type="park")
        .polygon([(235, 200), (345, 200), (345, 305), (235, 305)])
        .surface("grass")
        .vegetation(0.7)
        .outdoor_description("2020年改造的口袋公园，草坪、木质座椅、艺术装置。平时有遛狗的居民和在此工作的远程办公者。偶有快闪市集。")
        .sounds("草坪上的交谈", "狗叫", "远处街道声")
        .smells("青草", "花香")
        .add_affordance("rest", time_range=(0, 24), description="公共开放，全天免费")
        .add_affordance("work", time_range=(8, 20),
                        description="木质桌椅，适合户外办公，但无电源")
        .add_affordance("socialize", time_range=(8, 22),
                        description="遛狗社群、自发聚会，英语普通话都有")
        .entry_signals(
            visible_from_street=("草坪", "艺术装置", "带笔记本的人"),
            facade_description="开放式草坪公园，有木质标识牌，无围栏。",
        )
        .end_outdoor()
    )

    # Railway corridor (physical divider)
    (builder
        .add_outdoor("railway_corridor", "铁路绿化带", area_type="outdoor")
        .polygon([(185, 0), (235, 0), (235, 115), (185, 115)])
        .surface("gravel")
        .vegetation(0.3)
        .outdoor_description("废弃铁路沿线的绿化隔离带，铁丝网围栏，偶有流浪猫出没。实际上将整个社区分为东西两侧。")
        .sounds("偶尔的货运列车声", "风吹草声")
        .smells("野草", "铁锈")
        .add_affordance("transit", time_range=(0, 24),
                        description="仅有涵洞一处可穿越，其余全部封闭")
        .end_outdoor()
    )

    # ─────────────────────────────────────────────
    # CONNECTIONS
    # ─────────────────────────────────────────────

    (builder
        # Old side buildings to old main street
        .connect("chen_home", "old_main_st", "entrance")
        .connect("old_market", "old_main_st", "entrance")
        .connect("community_center", "old_main_st", "path")
        .connect("repair_shop", "old_main_st", "entrance")
        .connect("old_teahouse", "old_main_st", "entrance")

        # Old side internal
        .connect("community_center", "old_park", "path")
        .connect("chen_home", "community_center", "path")
        .connect("old_market", "repair_shop", "path")
        .connect("repair_shop", "community_center", "path")
        .connect("old_teahouse", "old_park", "path")
        .connect("old_park", "old_main_st", "path")

        # Railway corridor
        .connect("old_main_st", "railway_corridor", "path")
        .connect("railway_corridor", "railway_underpass", "path")
        .connect("railway_underpass", "new_main_st", "path")
        .connect("new_main_st", "railway_corridor", "path")

        # New side buildings to new main street
        .connect("sunrise_cafe", "new_main_st", "entrance")
        .connect("cowork", "new_main_st", "entrance")
        .connect("boutique_apts", "new_main_st", "entrance")
        .connect("brunch_place", "new_main_st", "entrance")
        .connect("artisan_grocery", "new_main_st", "entrance")

        # New side internal
        .connect("cowork", "sunrise_cafe", "path")
        .connect("brunch_place", "boutique_apts", "path")
        .connect("artisan_grocery", "cowork", "path")
        .connect("pocket_park", "new_main_st", "path")
        .connect("pocket_park", "brunch_place", "path")
        .connect("pocket_park", "artisan_grocery", "path")
    )

    # ─────────────────────────────────────────────
    # BORDERS (researcher metadata — not exposed to agents)
    # ─────────────────────────────────────────────

    (builder
        .add_border("railway_divide", "铁路分界线", BorderType.PHYSICAL)
        .border_sides(
            ["chen_home", "old_market", "community_center", "repair_shop",
             "old_teahouse", "old_main_st", "old_park"],
            ["sunrise_cafe", "cowork", "boutique_apts", "brunch_place",
             "artisan_grocery", "new_main_st", "pocket_park"],
        )
        .border_permeability(0.15)
        .border_crossings(["railway_underpass"])
        .border_description(
            "废弃铁路线将社区分为新旧两侧。仅有一处涵洞可步行穿越，"
            "物理上的低渗透性导致两侧居民日常几乎无交集。"
        )
        .end_border()

        .add_border("language_barrier", "语言-文化边界", BorderType.SOCIAL)
        .border_sides(
            ["old_market", "old_teahouse", "community_center"],
            ["sunrise_cafe", "brunch_place", "artisan_grocery"],
        )
        .border_permeability(0.1)
        .border_description(
            "旧区空间以普通话/闽南语为主，新区空间以英语/普通话双语运营。"
            "语言差异形成无形的社会边界，即便物理上可达，陈大爷等老居民"
            "也会因语言障碍而感到格格不入。"
        )
        .end_border()

        .add_border("info_divide", "信息隔离边界", BorderType.INFORMATIONAL)
        .border_sides(
            ["chen_home", "old_market", "old_teahouse"],
            ["sunrise_cafe", "cowork", "boutique_apts"],
        )
        .border_permeability(0.05)
        .border_description(
            "陈大爷等老居民的信息圈局限于社区公告栏、邻居口耳相传、"
            "电视新闻。他们对新区的业态几乎一无所知，甚至不知道对面有咖啡馆。"
            "Alex等新区居民同样不知道旧区有同兴茶馆这样的社区空间。"
        )
        .end_border()
    )

    region = builder.build()
    return Atlas(region)


def create_demo_knowledge_maps(atlas: Atlas) -> dict[str, AgentKnowledgeMap]:
    """
    Create preset knowledge maps for 4 demo agents.

    This demonstrates information asymmetry — agents literally don't know
    places exist until they encounter them.

    陈大爷: 旧区专家，新区对他来说几乎是空白
    Alex:   新区居民，旧区是模糊的背景
    Mei:    自由穿行，两侧都有了解
    Aisha:  外籍人士，仅知道新区和主要交通节点
    """

    maps: dict[str, AgentKnowledgeMap] = {}

    # ─── 陈大爷 (Chen Daye) — 70岁，旧区深耕四十年 ───
    chen_km = AgentKnowledgeMap(agent_id="chen_daye")
    chen_km.locations = {
        "chen_home":        AgentLocationKnowledge(loc_id="chen_home", familiarity=F.REGULAR,
                                known_name="家", visit_count=14600, learned_from="self_visit",
                                subjective_impression="住了四十年，每层楼的邻居都认识"),
        "old_market":       AgentLocationKnowledge(loc_id="old_market", familiarity=F.REGULAR,
                                known_name="菜市场", visit_count=3650, learned_from="self_visit",
                                subjective_impression="每天早上来，猪肉摊的老张会给我留好料"),
        "community_center": AgentLocationKnowledge(loc_id="community_center", familiarity=F.REGULAR,
                                known_name="社区活动中心", visit_count=500, learned_from="self_visit",
                                subjective_impression="下午打牌、看报的地方，认识不少老邻居"),
        "old_teahouse":     AgentLocationKnowledge(loc_id="old_teahouse", familiarity=F.REGULAR,
                                known_name="同兴茶馆", visit_count=800, learned_from="self_visit",
                                subjective_impression="喝了二十年，老板娘叫我'陈老'"),
        "old_park":         AgentLocationKnowledge(loc_id="old_park", familiarity=F.REGULAR,
                                known_name="街心花园", visit_count=2000, learned_from="self_visit",
                                subjective_impression="太极拳、和老王下棋"),
        "repair_shop":      AgentLocationKnowledge(loc_id="repair_shop", familiarity=F.VISITED,
                                known_name="老王修理铺", visit_count=20, learned_from="self_visit"),
        "old_main_st":      AgentLocationKnowledge(loc_id="old_main_st", familiarity=F.REGULAR,
                                known_name="民生路", visit_count=5000, learned_from="self_visit"),
        "railway_corridor": AgentLocationKnowledge(loc_id="railway_corridor", familiarity=F.SEEN_EXTERIOR,
                                known_name="铁路那边", learned_from="self_visit",
                                subjective_impression="铁丝网围着，没什么好看的"),
        "railway_underpass": AgentLocationKnowledge(loc_id="railway_underpass", familiarity=F.VISITED,
                                known_name="涵洞", visit_count=5, learned_from="self_visit",
                                subjective_impression="穿过去太暗了，不太安全"),
        # 新区：仅模糊听说
        "new_main_st":      AgentLocationKnowledge(loc_id="new_main_st", familiarity=F.HEARD_OF,
                                known_name="对面那条街", learned_from="agent:neighbor",
                                subjective_impression="听说新开了很多店，但都是年轻人的地方"),
    }
    maps["chen_daye"] = chen_km

    # ─── Alex — 28岁，新区科技从业者 ───
    alex_km = AgentKnowledgeMap(agent_id="alex")
    alex_km.locations = {
        "boutique_apts":    AgentLocationKnowledge(loc_id="boutique_apts", familiarity=F.REGULAR,
                                known_name="公寓", visit_count=365, learned_from="self_visit",
                                subjective_impression="住的地方，安静，健身房不错"),
        "sunrise_cafe":     AgentLocationKnowledge(loc_id="sunrise_cafe", familiarity=F.REGULAR,
                                known_name="Sunrise", visit_count=200, learned_from="self_visit",
                                subjective_impression="每天早上来，认识吧台的Sam"),
        "cowork":           AgentLocationKnowledge(loc_id="cowork", familiarity=F.REGULAR,
                                known_name="WeSpace", visit_count=150, learned_from="self_visit",
                                subjective_impression="月卡用户，三楼有我常用的工位"),
        "brunch_place":     AgentLocationKnowledge(loc_id="brunch_place", familiarity=F.VISITED,
                                known_name="The Table", visit_count=15, learned_from="self_visit"),
        "artisan_grocery":  AgentLocationKnowledge(loc_id="artisan_grocery", familiarity=F.VISITED,
                                known_name="Green Basket", visit_count=30, learned_from="self_visit"),
        "pocket_park":      AgentLocationKnowledge(loc_id="pocket_park", familiarity=F.VISITED,
                                known_name="口袋公园", visit_count=10, learned_from="self_visit"),
        "new_main_st":      AgentLocationKnowledge(loc_id="new_main_st", familiarity=F.REGULAR,
                                known_name="创新路", visit_count=365, learned_from="self_visit"),
        "railway_corridor": AgentLocationKnowledge(loc_id="railway_corridor", familiarity=F.SEEN_EXTERIOR,
                                known_name="铁路边", learned_from="self_visit"),
        "railway_underpass": AgentLocationKnowledge(loc_id="railway_underpass", familiarity=F.HEARD_OF,
                                known_name="那个涵洞", learned_from="agent:colleague",
                                subjective_impression="同事说可以穿过去，但没走过"),
        # 旧区：完全未知
    }
    maps["alex"] = alex_km

    # ─── Mei — 32岁，自由设计师，两侧都有涉足 ───
    mei_km = AgentKnowledgeMap(agent_id="mei")
    mei_km.locations = {
        # New side (work)
        "cowork":           AgentLocationKnowledge(loc_id="cowork", familiarity=F.REGULAR,
                                known_name="WeSpace", visit_count=80, learned_from="self_visit",
                                subjective_impression="灵活工位适合我，不用每天来"),
        "sunrise_cafe":     AgentLocationKnowledge(loc_id="sunrise_cafe", familiarity=F.VISITED,
                                known_name="Sunrise", visit_count=25, learned_from="self_visit"),
        "pocket_park":      AgentLocationKnowledge(loc_id="pocket_park", familiarity=F.VISITED,
                                known_name="口袋公园", visit_count=20, learned_from="self_visit",
                                subjective_impression="下午阳光好的时候在这里画草稿"),
        "new_main_st":      AgentLocationKnowledge(loc_id="new_main_st", familiarity=F.REGULAR,
                                known_name="创新路", visit_count=200, learned_from="self_visit"),
        "artisan_grocery":  AgentLocationKnowledge(loc_id="artisan_grocery", familiarity=F.VISITED,
                                known_name="Green Basket", visit_count=12, learned_from="self_visit"),
        # Transit
        "railway_underpass": AgentLocationKnowledge(loc_id="railway_underpass", familiarity=F.VISITED,
                                known_name="涵洞", visit_count=30, learned_from="self_visit",
                                subjective_impression="走过很多次了，不害怕，但夜里还是不太舒服"),
        "railway_corridor": AgentLocationKnowledge(loc_id="railway_corridor", familiarity=F.SEEN_EXTERIOR,
                                known_name="铁路带", learned_from="self_visit"),
        "old_main_st":      AgentLocationKnowledge(loc_id="old_main_st", familiarity=F.VISITED,
                                known_name="旧区主街", visit_count=15, learned_from="self_visit"),
        # Old side (discovered on walks)
        "old_market":       AgentLocationKnowledge(loc_id="old_market", familiarity=F.VISITED,
                                known_name="菜市场", visit_count=8, learned_from="self_visit",
                                subjective_impression="价格比Green Basket便宜很多，但要早去，语言稍有障碍"),
        "old_park":         AgentLocationKnowledge(loc_id="old_park", familiarity=F.SEEN_EXTERIOR,
                                known_name="旧公园", learned_from="self_visit"),
        "old_teahouse":     AgentLocationKnowledge(loc_id="old_teahouse", familiarity=F.HEARD_OF,
                                known_name="听说有个老茶馆", learned_from="agent:client",
                                subjective_impression="客户说那边有个很有意思的老茶馆，想去看看"),
    }
    maps["mei"] = mei_km

    # ─── Aisha — 35岁，外籍人士 ───
    aisha_km = AgentKnowledgeMap(agent_id="aisha")
    aisha_km.locations = {
        "boutique_apts":    AgentLocationKnowledge(loc_id="boutique_apts", familiarity=F.REGULAR,
                                known_name="My Apartment", visit_count=500, learned_from="self_visit",
                                subjective_impression="Safe, quiet, good gym"),
        "brunch_place":     AgentLocationKnowledge(loc_id="brunch_place", familiarity=F.REGULAR,
                                known_name="The Table", visit_count=40, learned_from="self_visit",
                                subjective_impression="Best brunch in the neighborhood, worth the wait"),
        "sunrise_cafe":     AgentLocationKnowledge(loc_id="sunrise_cafe", familiarity=F.REGULAR,
                                known_name="Sunrise Café", visit_count=60, learned_from="self_visit"),
        "artisan_grocery":  AgentLocationKnowledge(loc_id="artisan_grocery", familiarity=F.REGULAR,
                                known_name="Green Basket", visit_count=80, learned_from="self_visit",
                                subjective_impression="Only place I can find imported ingredients"),
        "cowork":           AgentLocationKnowledge(loc_id="cowork", familiarity=F.VISITED,
                                known_name="WeSpace", visit_count=5, learned_from="self_visit"),
        "pocket_park":      AgentLocationKnowledge(loc_id="pocket_park", familiarity=F.VISITED,
                                known_name="Pocket Park", visit_count=15, learned_from="self_visit"),
        "new_main_st":      AgentLocationKnowledge(loc_id="new_main_st", familiarity=F.REGULAR,
                                known_name="Innovation Road", visit_count=400, learned_from="self_visit"),
        "railway_underpass": AgentLocationKnowledge(loc_id="railway_underpass", familiarity=F.HEARD_OF,
                                known_name="The Underpass", learned_from="agent:neighbor",
                                subjective_impression="Heard it leads to the old side, haven't tried"),
        # Old side: completely unknown
    }
    maps["aisha"] = aisha_km

    return maps


def create_ledger_with_demo_knowledge(atlas: Atlas) -> Ledger:
    """Create a Ledger pre-loaded with demo agent knowledge maps and trace events."""
    ledger = Ledger()
    knowledge_maps = create_demo_knowledge_maps(atlas)
    for km in knowledge_maps.values():
        ledger.set_agent_knowledge_map(km)

    # Seed a few trace events to show social history
    ledger.record_trace_event(
        "old_market", "activity",
        "陈大爷与猪肉摊老张聊了今天的肉价，顺带打听了老王修理铺最近生意如何",
        sim_time="Day 1 07:30", agent_id="chen_daye"
    )
    ledger.record_trace_event(
        "old_park", "activity",
        "十二位老人在东侧进行太极拳晨练，陈大爷是其中之一",
        sim_time="Day 1 06:15", agent_id="chen_daye"
    )
    ledger.record_trace_event(
        "sunrise_cafe", "activity",
        "Alex在靠窗位置工作了三小时，期间与一位产品经理短暂交谈",
        sim_time="Day 1 09:00", agent_id="alex"
    )
    ledger.record_trace_event(
        "cowork", "activity",
        "Mei在三楼完成了一份品牌提案，途中和前台的小李聊了两句",
        sim_time="Day 1 14:00", agent_id="mei"
    )
    ledger.record_trace_event(
        "railway_underpass", "activity",
        "Mei从新区骑车穿越涵洞，发现涵洞南侧有新的涂鸦",
        sim_time="Day 1 12:30", agent_id="mei"
    )

    return ledger
