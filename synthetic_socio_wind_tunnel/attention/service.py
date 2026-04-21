"""
AttentionService - 数字注意力通道的读写路径

职责：
- 把 FeedItem 投递给目标 agent（生成 NotificationEvent，写入 Ledger）
- 支持"算法偏向"的概率抑制（feed_bias_suppression）
- 提供 pending / 历史查询
- 导出投递日志供 metrics 使用

MUST NOT 修改 AgentProfile 或 ObserverContext（agent 下一次构造 context 时
自行拼装 AttentionState）；MUST NOT 触发物理 audible_range / visible_range
传播。
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import TYPE_CHECKING, Iterable, Mapping

from synthetic_socio_wind_tunnel.attention.models import (
    DigitalProfile,
    FeedDeliveryRecord,
    FeedItem,
    NotificationEvent,
    create_notification_event,
)

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.ledger import Ledger


def _should_deliver(
    item: FeedItem,
    profile: DigitalProfile,
    *,
    suppression: float,
    rng: random.Random,
) -> bool:
    """
    最小的算法偏向建模：

    - 全球偏向者丢失本地推送：local_news 在 feed_bias="global" 下按概率 suppression 丢弃
    - 本地偏向者丢失全球推送：global_news 在 feed_bias="local" 下对称
    - 其它情况一律投递
    """
    if profile.feed_bias == "global" and item.source == "local_news":
        return rng.random() >= suppression
    if profile.feed_bias == "local" and item.source == "global_news":
        return rng.random() >= suppression
    return True


class AttentionService:
    """
    Digital attention channel writer & reader.

    Writes to Ledger.notifications on inject; reads for pending / log export.
    """

    __slots__ = (
        "_ledger",
        "_profiles",
        "_feed_index",
        "_feed_bias_suppression",
        "_rng",
        "_delivery_log",
        "_consumed",
    )

    def __init__(
        self,
        ledger: "Ledger",
        *,
        profiles: Mapping[str, DigitalProfile] | None = None,
        feed_bias_suppression: float = 0.2,
        seed: int | None = None,
    ) -> None:
        """
        Args:
            ledger: Target Ledger (notifications are appended here).
            profiles: Per-agent DigitalProfile lookup. If None, all recipients
                use a default profile (feed_bias="global", responsiveness=0.5).
            feed_bias_suppression: Probability that a bias-mismatched feed item
                is suppressed.
            seed: RNG seed for deterministic suppression decisions.
        """
        self._ledger = ledger
        self._profiles: dict[str, DigitalProfile] = dict(profiles or {})
        self._feed_index: dict[str, FeedItem] = {}
        self._feed_bias_suppression = feed_bias_suppression
        self._rng = random.Random(seed)
        self._delivery_log: list[FeedDeliveryRecord] = []
        # Consumed tracking: per-agent set of feed_item_ids that perception
        # has already surfaced once. Prevents duplicate DIGITAL observations
        # on subsequent renders.
        self._consumed: dict[str, set[str]] = {}

    # ---- Profile bookkeeping ----

    def set_profile(self, agent_id: str, profile: DigitalProfile) -> None:
        self._profiles[agent_id] = profile

    def _profile_for(self, agent_id: str) -> DigitalProfile:
        return self._profiles.get(agent_id, DigitalProfile())

    # ---- FeedItem catalog ----

    def register_feed_item(self, item: FeedItem) -> None:
        """Register a FeedItem so filter / pending callers can look it up by id."""
        self._feed_index[item.feed_item_id] = item

    def get_feed_item(self, feed_item_id: str) -> FeedItem | None:
        return self._feed_index.get(feed_item_id)

    # ---- Injection ----

    def inject_feed_item(
        self,
        item: FeedItem,
        recipients: Iterable[str],
        *,
        recipient_locations: Mapping[str, str] | None = None,
    ) -> list[NotificationEvent]:
        """
        Deliver `item` to each recipient (respecting algorithmic bias).

        For each recipient:
        - If _should_deliver returns False (bias suppression), a delivery
          record with delivered=False and suppressed_by_bias=True is logged,
          no NotificationEvent is appended to Ledger.
        - Otherwise, a NotificationEvent is created with the recipient's
          current location (looked up via Ledger or override map) and
          appended to Ledger.

        The item is registered in `_feed_index` for later lookup.

        Args:
            item: The feed item to deliver.
            recipients: Iterable of agent ids.
            recipient_locations: Optional explicit mapping from agent_id to
                location_id (used when Ledger doesn't have the entity state).

        Returns:
            The list of NotificationEvent instances actually delivered
            (suppressed ones excluded).
        """
        self.register_feed_item(item)

        now = self._ledger.current_time
        delivered_events: list[NotificationEvent] = []
        overrides = dict(recipient_locations or {})

        for agent_id in recipients:
            profile = self._profile_for(agent_id)
            should = _should_deliver(
                item,
                profile,
                suppression=self._feed_bias_suppression,
                rng=self._rng,
            )
            if not should:
                self._delivery_log.append(FeedDeliveryRecord(
                    feed_item_id=item.feed_item_id,
                    recipient_id=agent_id,
                    delivered=False,
                    delivered_at=now,
                    origin_hack_id=item.origin_hack_id,
                    suppressed_by_bias=True,
                ))
                continue

            location_id = overrides.get(agent_id)
            if location_id is None:
                entity = self._ledger.get_entity(agent_id)
                location_id = entity.location_id if entity else "unknown"

            event = create_notification_event(
                feed_item_id=item.feed_item_id,
                recipient_entity_id=agent_id,
                recipient_location_id=location_id,
                timestamp=now,
                origin_hack_id=item.origin_hack_id,
            )
            self._ledger.add_notification(event)
            delivered_events.append(event)
            self._delivery_log.append(FeedDeliveryRecord(
                feed_item_id=item.feed_item_id,
                recipient_id=agent_id,
                delivered=True,
                delivered_at=now,
                origin_hack_id=item.origin_hack_id,
                suppressed_by_bias=False,
            ))

        return delivered_events

    # ---- Query ----

    def notifications_for(
        self,
        agent_id: str,
        *,
        since: datetime | None = None,
    ) -> list[NotificationEvent]:
        """Proxy to Ledger; exposed here so callers don't need to touch Ledger."""
        return self._ledger.notifications_for(agent_id, since=since)

    def pending_for(self, agent_id: str) -> tuple[str, ...]:
        """
        Return feed_item_ids delivered to agent but not yet surfaced to perception.

        Pipeline calls this once per render; after surfacing the observations,
        pipeline calls mark_consumed() so subsequent renders don't duplicate.
        Order matches delivery order (oldest first).
        """
        consumed = self._consumed.get(agent_id, set())
        events = self.notifications_for(agent_id)
        pending = [ev.feed_item_id for ev in events if ev.feed_item_id not in consumed]
        return tuple(pending)

    def mark_consumed(self, agent_id: str, feed_item_ids: Iterable[str]) -> None:
        """
        Mark feed items as surfaced for this agent.

        Called by PerceptionPipeline after gathering DIGITAL observations
        so the same feed item isn't re-injected on the next render.
        """
        bucket = self._consumed.setdefault(agent_id, set())
        for fid in feed_item_ids:
            bucket.add(fid)

    def reset_consumed(self, agent_id: str | None = None) -> None:
        """Clear consumed tracking (testing / reset between experiments)."""
        if agent_id is None:
            self._consumed.clear()
        else:
            self._consumed.pop(agent_id, None)

    # ---- Log export ----

    def export_feed_log(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[FeedDeliveryRecord]:
        """Return delivery log, optionally filtered by time window."""
        if since is None and until is None:
            return list(self._delivery_log)
        filtered: list[FeedDeliveryRecord] = []
        for record in self._delivery_log:
            if since is not None and record.delivered_at < since:
                continue
            if until is not None and record.delivered_at > until:
                continue
            filtered.append(record)
        return filtered
