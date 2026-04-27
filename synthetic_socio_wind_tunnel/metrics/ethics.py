"""
Ethics statement for publishable artifacts.

Single source of truth — `metrics/report.py::write_markdown` injects this
into report.md, and `docs/agent_system/13-research-design.md` Part V
references the same text. Tests assert keyword consistency.
"""

from __future__ import annotations


ETHICS_STATEMENT = """\
## Research Posture Statement

> 本项目是探索性研究装置，类比物理学的云室（cloud chamber）——让"注意力位移
> 造成的附近性盲区"这一社会现象在合成 agent 上可观察、可拆解；**不主张
> 任何真实世界部署**。
>
> 工具本身的对称性使其既可用于促进本地连接，也可用于放大孤立；我们的
> mirror experiment 显式展示这一 dual-use 属性。
>
> 部署需要居民同意、透明治理、反馈机制——这些在本项目 scope 之外。
"""


__all__ = ["ETHICS_STATEMENT"]
