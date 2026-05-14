"""
SubjectiveView → 中文 prose 拼接 helper.

被 `Planner.replan` 的 `【环境】` block + `tools/agent_perception_inspector.py`
共同消费。把 SubjectiveView 的结构化字段转成 ≤ 200 字中文 prose 描述
agent 此刻看见 / 听见 / 闻到的场景。

设计：
- 空 view 返回空字符串（不返"环境平静无奇"等占位文本）—— 让上层决定整块省略
- crowd 信息显式带数字，让 LLM 能 reasoning（"看到 5 个人"）
- item 的 content / name 真出现在 prose 里
- 文本硬性 ≤ 200 字（中文字符）
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.perception.models import SubjectiveView


_MAX_CHARS = 200


def render_subjective_view_prose(view: "SubjectiveView | None") -> str:
    """Render a SubjectiveView as ≤ 200-char Chinese prose.

    Returns empty string for None / empty views — caller should omit the
    surrounding prompt block entirely when this returns "".
    """
    if view is None:
        return ""

    parts: list[str] = []

    # Crowd: count entity_snapshots
    n_entities = len(view.entity_snapshots)
    if n_entities >= 5:
        parts.append(f"这里现在有 {n_entities} 个人")
    elif n_entities >= 2:
        parts.append(f"周围有 {n_entities} 个人")
    elif n_entities == 1:
        e = view.entity_snapshots[0]
        name = e.name or e.entity_id
        if e.activity:
            parts.append(f"附近只有 {name}，正在{e.activity}")
        else:
            parts.append(f"附近只有 {name}")

    # Items: pick up to 2 notable / nearby items
    notable_items = [i for i in view.item_snapshots if i.is_notable]
    items_to_show = notable_items[:2] if notable_items else view.item_snapshots[:2]
    for item in items_to_show:
        if item.position_description:
            parts.append(f"看到 {item.name}（{item.position_description}）")
        else:
            parts.append(f"看到 {item.name}")

    # Ambient sounds: 1 most recent
    if view.ambient_sounds:
        parts.append(f"听到{view.ambient_sounds[0]}")

    # Ambient smells: 1 most recent
    if view.ambient_smells:
        parts.append(f"闻到{view.ambient_smells[0]}")

    # Lighting (only if non-default)
    if view.lighting and view.lighting not in ("normal", ""):
        parts.append(f"光线{view.lighting}")

    if not parts:
        return ""

    prose = "；".join(parts) + "。"
    if len(prose) > _MAX_CHARS:
        prose = prose[: _MAX_CHARS - 1] + "…"
    return prose


__all__ = ["render_subjective_view_prose"]
