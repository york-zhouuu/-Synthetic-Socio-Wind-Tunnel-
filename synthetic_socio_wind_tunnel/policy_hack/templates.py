"""Preset PushTemplate pool (push-content-individualization).

5 hand-crafted templates covering typical Lane Cove hyperlocal scenarios.
Each template MUST contain a "default" audience variant and non-empty
target_audience_tags. base_salience ∈ [0.6, 0.9] (hyperlocal range).
"""

from __future__ import annotations

from synthetic_socio_wind_tunnel.policy_hack.personalizer import PushTemplate


# 1. Saturday market — primarily for parents + young adults
_MARKET = PushTemplate(
    template_id="market_v1",
    topic_id="hp_market",
    base_content="本街 {location} 周六举办市集",
    audience_variants={
        "parents": "{location} 周六亲子市集开场啦——孩子家长可来逛逛、交换童书、试试本地手作。",
        "young_adult": "{location} 周六街角市集——第一次办，欢迎刚搬来的邻居一起来认识人。",
        "elderly": "{location} 周六街区市集——上午 9-11 点，无障碍通道齐全，可坐着喝咖啡聊天。",
        "newcomer": "{location} 周六本街市集——本街第一次，新搬来的可以来认识下邻居。",
        "default": "本街 {location} 周六上午 9-12 点举办市集，欢迎来逛。",
    },
    target_audience_tags=("parents", "young_adult"),
    base_salience=0.85,
)


# 2. Reading group at the library — primarily for elderly + default
_READING_GROUP = PushTemplate(
    template_id="reading_group_v1",
    topic_id="hp_reading_group",
    base_content="本街 {location} 周三晚读书会",
    audience_variants={
        "elderly": "{location} 周三晚读书会——本月主题《Lane Cove 简史》，茶水点心齐全。",
        "default": "{location} 周三晚 7 点读书会——本月主题《Lane Cove 简史》。",
        "parents": "{location} 周三晚 7 点读书会——可带较大孩子，环境安静。",
        "young_adult": "{location} 周三晚读书会——可参加，欢迎本地话题讨论。",
        "newcomer": "{location} 周三晚读书会——新搬来的可以来认识邻居 + 了解本街历史。",
    },
    target_audience_tags=("elderly", "default"),
    base_salience=0.7,
)


# 3. Newcomer meet-and-greet — primarily for newcomers
_NEIGHBOUR_MEET = PushTemplate(
    template_id="neighbour_meet_v1",
    topic_id="hp_neighbour_meet",
    base_content="本街 {location} 周日新邻居见面会",
    audience_variants={
        "newcomer": "{location} 周日下午 3 点新邻居见面会——刚搬来的一定要来，大家轮流自我介绍 + 介绍自己怎么找到 Lane Cove。",
        "default": "{location} 周日下午 3 点新邻居见面会——已经住了一阵的也可以来欢迎新邻居。",
        "parents": "{location} 周日下午 3 点新邻居见面会——孩子可一起来，会有简单游戏。",
        "elderly": "{location} 周日下午 3 点新邻居见面会——老邻居来欢迎下新搬来的邻居。",
        "young_adult": "{location} 周日下午 3 点新邻居见面会——刚搬来或想认识下邻居都可以来。",
    },
    target_audience_tags=("newcomer",),
    base_salience=0.8,
)


# 4. Kids event at the playground — primarily for parents
_KID_EVENT = PushTemplate(
    template_id="kid_event_v1",
    topic_id="hp_kid_event",
    base_content="本街 {location} 周六儿童活动",
    audience_variants={
        "parents": "{location} 周六上午 10 点儿童活动——本街妈妈群组织，免费、有手作、有零食，可带 3-12 岁孩子。",
        "default": "{location} 周六上午 10 点本街儿童活动。",
        "young_adult": "{location} 周六儿童活动——可来当志愿者帮忙，认识本街家长。",
        "elderly": "{location} 周六儿童活动——可以来看看孙子辈。",
        "newcomer": "{location} 周六儿童活动——新搬来有孩子的可以来认识本街家长。",
    },
    target_audience_tags=("parents",),
    base_salience=0.85,
)


# 5. Community clean-up day — broad / default
_COMMUNITY_CLEAN = PushTemplate(
    template_id="community_clean_v1",
    topic_id="hp_community_clean",
    base_content="本街 {location} 周日社区清扫日",
    audience_variants={
        "default": "{location} 周日上午社区清扫日——大家带垃圾袋手套来，清扫完一起 BBQ。",
        "parents": "{location} 周日上午社区清扫日——可带较大孩子参加，让 ta 们认识社区。",
        "young_adult": "{location} 周日上午社区清扫日——好场合认识本街邻居。",
        "elderly": "{location} 周日上午社区清扫日——不必下场清扫，来现场指点 / 聊天就行。",
        "newcomer": "{location} 周日上午社区清扫日——新搬来的好机会快速融入本街。",
    },
    target_audience_tags=("default",),
    base_salience=0.65,
)


PUSH_TEMPLATES: tuple[PushTemplate, ...] = (
    _MARKET,
    _READING_GROUP,
    _NEIGHBOUR_MEET,
    _KID_EVENT,
    _COMMUNITY_CLEAN,
)


__all__ = ["PUSH_TEMPLATES"]
