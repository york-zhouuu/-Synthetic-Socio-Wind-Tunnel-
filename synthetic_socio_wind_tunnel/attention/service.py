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
from typing import TYPE_CHECKING, Any, Iterable, Mapping

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
        "_phone_attention",
        "_phone_attention_baseline",
        "_personality_openness",
        "_notifications_today",
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
        # add-attention-induced-nearby-blindness: per-agent dynamic phone
        # attention share. baseline = ambient screen-time fraction; current
        # value rises with notification arrivals and decays per tick.
        self._phone_attention: dict[str, float] = {}
        self._phone_attention_baseline: dict[str, float] = {}
        # Personality cache for delta computation (openness only); other
        # fields read from DigitalProfile directly.
        self._personality_openness: dict[str, float] = {}
        # B5 fix: per-agent per-day notification count for fatigue computation.
        # Resets at on_day_start (via reset_daily_counters).
        self._notifications_today: dict[str, int] = {}

    # ---- Snapshot (tick-level-resume 2026-05-16) ----

    def to_snapshot_state(self) -> dict[str, Any]:
        """Serialize all mutable per-agent attention state.

        Ledger reference NOT serialized — caller reattaches. Notification
        history lives on Ledger (already covered by Ledger.to_snapshot_state).
        Only AttentionService-private state is dumped here.
        """
        from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
            _rng_state_to_json,
        )

        return {
            "profiles": {
                aid: p.model_dump(mode="json") for aid, p in self._profiles.items()
            },
            "feed_index": {
                fid: fi.model_dump(mode="json") for fid, fi in self._feed_index.items()
            },
            "feed_bias_suppression": self._feed_bias_suppression,
            "delivery_log": [
                rec.model_dump(mode="json") for rec in self._delivery_log
            ],
            "consumed": {
                aid: sorted(ids) for aid, ids in self._consumed.items()
            },
            "phone_attention": dict(self._phone_attention),
            "phone_attention_baseline": dict(self._phone_attention_baseline),
            "personality_openness": dict(self._personality_openness),
            "notifications_today": dict(self._notifications_today),
            "rng_state": _rng_state_to_json(self._rng.getstate()),
        }

    def from_snapshot_state(self, state: dict[str, Any]) -> None:
        """Replace state from snapshot. Existing state discarded."""
        from synthetic_socio_wind_tunnel.attention.models import (
            DigitalProfile, FeedDeliveryRecord, FeedItem,
        )
        from synthetic_socio_wind_tunnel.run_resilience.state_snapshot import (
            _rng_state_from_json,
        )

        if not isinstance(state, dict):
            raise ValueError(
                f"AttentionService.from_snapshot_state expects dict, "
                f"got {type(state).__name__}",
            )

        self._profiles = {
            aid: DigitalProfile.model_validate(p)
            for aid, p in (state.get("profiles") or {}).items()
        }
        self._feed_index = {
            fid: FeedItem.model_validate(fi)
            for fid, fi in (state.get("feed_index") or {}).items()
        }
        self._feed_bias_suppression = float(
            state.get("feed_bias_suppression", self._feed_bias_suppression),
        )
        self._delivery_log = [
            FeedDeliveryRecord.model_validate(rec)
            for rec in (state.get("delivery_log") or [])
        ]
        self._consumed = {
            aid: set(ids) for aid, ids in (state.get("consumed") or {}).items()
        }
        self._phone_attention = dict(state.get("phone_attention") or {})
        self._phone_attention_baseline = dict(
            state.get("phone_attention_baseline") or {},
        )
        self._personality_openness = dict(state.get("personality_openness") or {})
        self._notifications_today = dict(state.get("notifications_today") or {})

        rng_state = state.get("rng_state")
        if rng_state is not None:
            try:
                self._rng.setstate(_rng_state_from_json(rng_state))
            except Exception:  # noqa: BLE001
                pass

    # ---- Profile bookkeeping ----

    def set_profile(self, agent_id: str, profile: DigitalProfile) -> None:
        self._profiles[agent_id] = profile

    def _profile_for(self, agent_id: str) -> DigitalProfile:
        return self._profiles.get(agent_id, DigitalProfile())

    # ---- Phone-attention state (add-attention-induced-nearby-blindness) ----

    def set_phone_attention_baseline(
        self, agent_id: str, baseline: float,
    ) -> None:
        """Register an agent's resting-state phone attention share.

        Typically called once during simulation setup, e.g.
        `set_phone_attention_baseline(a.id, baseline_screen_share(a.digital))`.
        """
        from synthetic_socio_wind_tunnel.attention.noticing import (
            PHONE_ATTENTION_MAX, PHONE_ATTENTION_MIN,
        )
        b = max(PHONE_ATTENTION_MIN, min(PHONE_ATTENTION_MAX, baseline))
        self._phone_attention_baseline[agent_id] = b
        # Initialize current value to baseline if not set
        if agent_id not in self._phone_attention:
            self._phone_attention[agent_id] = b

    def set_personality_openness(self, agent_id: str, openness: float) -> None:
        """Cache personality.openness for notification-delta calculation."""
        self._personality_openness[agent_id] = max(0.0, min(1.0, openness))

    def get_phone_attention(self, agent_id: str) -> float:
        """Current phone_attention for the agent (baseline if never delivered).

        Unseen agents return 0.0 (assumed no phone presence).
        """
        if agent_id in self._phone_attention:
            return self._phone_attention[agent_id]
        return self._phone_attention_baseline.get(agent_id, 0.0)

    def tick_decay_all(self) -> None:
        """Apply one tick of geometric decay to every tracked agent."""
        from synthetic_socio_wind_tunnel.attention.noticing import (
            decay_phone_attention,
        )
        for aid, current in list(self._phone_attention.items()):
            baseline = self._phone_attention_baseline.get(aid, 0.0)
            self._phone_attention[aid] = decay_phone_attention(current, baseline)

    def _accumulate_phone_attention(
        self, agent_id: str, feed_item,
    ) -> None:
        """Add the delta from a delivered FeedItem to phone_attention.

        B5: per-day notification count drives diminishing-returns fatigue.
        """
        from synthetic_socio_wind_tunnel.attention.noticing import (
            PHONE_ATTENTION_MAX, compute_notification_delta,
        )
        digital = self._profile_for(agent_id)
        responsiveness = getattr(digital, "notification_responsiveness", 0.5)
        openness = self._personality_openness.get(agent_id, 0.5)
        urgency = float(getattr(feed_item, "urgency", 0.5) or 0.5)
        n_today = self._notifications_today.get(agent_id, 0)
        delta = compute_notification_delta(
            urgency, responsiveness, openness,
            notifications_received_today=n_today,
        )
        self._notifications_today[agent_id] = n_today + 1
        current = self._phone_attention.get(
            agent_id, self._phone_attention_baseline.get(agent_id, 0.0),
        )
        self._phone_attention[agent_id] = min(
            PHONE_ATTENTION_MAX, current + delta,
        )

    def reset_daily_counters(self) -> None:
        """B5: reset per-day notification counts on day boundary."""
        self._notifications_today.clear()

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
            # add-attention-induced-nearby-blindness: successful delivery
            # accumulates phone_attention on the recipient. Suppressed deliveries
            # don't update attention (no notification reached the user).
            self._accumulate_phone_attention(agent_id, item)

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
