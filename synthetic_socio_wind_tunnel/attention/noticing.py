"""Attention-induced nearby blindness — noticing gate + helpers.

Implements the thesis-critical mechanism: phone attention drains the agent's
capacity to notice nearby co-located people, blocking weak-tie formation
despite physical co-presence.

The math:
    phone_attention[t+1] = max(baseline, phone_attention[t] * 0.85)
                         + sum(notification.delta for newly arrived)
    noticing_prob(a, b)  = max(0, 1 - max(a, b)) * BASE_NOTICING_RATE

Notifications accumulate attention via:
    delta = NOTIFICATION_BASE_DELTA
          × urgency
          × (1 + (responsiveness - 0.5) × NOTIFICATION_RESPONSIVENESS_GAIN)
          × (0.5 + openness)
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.attention.models import DigitalProfile


# ---------------------------------------------------------------------------
# Tunable constants (calibration disclosure: first-order estimates, no
# empirical fitting against real ABS/Census attention data).
# ---------------------------------------------------------------------------

PHONE_ATTENTION_MIN = 0.0
PHONE_ATTENTION_MAX = 1.5  # transiently > 1 during burst of pushes
PHONE_ATTENTION_DECAY_PER_TICK = 0.85  # half-life ≈ 4 ticks (20 min)

NOTIFICATION_BASE_DELTA = 0.10
NOTIFICATION_RESPONSIVENESS_GAIN = 2.0

import os as _os
BASE_NOTICING_RATE = float(_os.environ.get("SSWT_BASE_NOTICING_RATE", "0.3"))
"""Ideal-condition noticing rate when both agents have zero phone attention.

The 0.3 reflects realistic street-level co-presence — most physical
proximity does not produce social registration even without phones (passing
strangers, agents focused on tasks). Phone attention scales this further down.

B3 sensitivity: override via env `SSWT_BASE_NOTICING_RATE=0.2` etc. to
verify thesis direction is robust to this calibration choice.
"""

WAKING_HOURS = 16.0


# ---------------------------------------------------------------------------
# Baseline + delta computation
# ---------------------------------------------------------------------------

def baseline_screen_share(digital: "DigitalProfile | None") -> float:
    """Return the ambient phone-attention share derived from daily screen hours.

    `digital.daily_screen_hours / 16h waking` clamped to [0, 1]. Agents with
    no DigitalProfile fall back to 0.0 (no baseline phone occupation).
    """
    if digital is None:
        return 0.0
    hours = getattr(digital, "daily_screen_hours", 0.0) or 0.0
    return min(1.0, max(0.0, hours / WAKING_HOURS))


def compute_notification_delta(
    urgency: float,
    responsiveness: float,
    openness: float,
    *,
    notifications_received_today: int = 0,
) -> float:
    """Compute the phone_attention increment from a single notification.

    B5 fix: cumulative fatigue. The N-th notification today produces less
    attention bump than the first. Half-life FATIGUE_HALFLIFE_N (8):
    delta_n = delta_0 × exp(-ln(2) × n / 8).

    This prevents pf (5 push/day per target) inflating attention by 5× over
    baseline ambient — each successive push has decreasing impact.
    """
    u = max(0.0, min(1.0, urgency))
    r = max(0.0, min(1.0, responsiveness))
    o = max(0.0, min(1.0, openness))
    delta = (
        NOTIFICATION_BASE_DELTA
        * u
        * (1.0 + (r - 0.5) * NOTIFICATION_RESPONSIVENESS_GAIN)
        * (0.5 + o)
    )
    # B5 cumulative fatigue
    if notifications_received_today > 0:
        import math as _math
        fatigue = _math.exp(
            -_math.log(2) * notifications_received_today / FATIGUE_HALFLIFE_N
        )
        delta *= fatigue
    return max(0.0, delta)


FATIGUE_HALFLIFE_N = 8.0
"""B5: Cumulative-fatigue half-life. After 8 notifications today, each new
push contributes 50% as much attention. Captures desensitization."""


def decay_phone_attention(current: float, baseline: float) -> float:
    """One tick of decay toward baseline."""
    decayed = current * PHONE_ATTENTION_DECAY_PER_TICK
    return max(baseline, decayed)


# ---------------------------------------------------------------------------
# Noticing gate
# ---------------------------------------------------------------------------

def noticing_prob(
    a_attn: float, b_attn: float,
    *,
    polygon_extent_m: float | None = None,
) -> float:
    """Probability that two co-located agents 'notice' each other.

    Three factors:
    1. attention: when either agent is glued to phone, noticing → 0
    2. polygon size (A3 fix): in a 1.4km park, two agents at opposite ends
       are technically "at same location_id" but in reality wouldn't see
       each other. Discount by typical_human_visual_range / polygon_extent
       (capped at 1.0 for small polygons where the factor doesn't bite).

    When polygon_extent_m is None → assume small location (no discount).
    """
    max_attn = max(a_attn, b_attn)
    free_share = max(0.0, 1.0 - max_attn)
    spatial_factor = 1.0
    if polygon_extent_m and polygon_extent_m > VISUAL_RANGE_M:
        # 50m visual range ÷ 1400m polygon ≈ 0.036 → in a giant park,
        # only ~3.6% of "raw" noticing actually fires
        spatial_factor = VISUAL_RANGE_M / polygon_extent_m
    return free_share * BASE_NOTICING_RATE * spatial_factor


# A3 fix: typical "noticing" range — beyond this you don't perceive another
# person well enough to register as social encounter.
VISUAL_RANGE_M = 50.0


def noticed_pair(
    a_attn: float,
    b_attn: float,
    *,
    seed: int,
    day: int,
    tick: int,
    pair: tuple[str, str],
    polygon_extent_m: float | None = None,
) -> bool:
    """Deterministic noticing decision.

    Uses a hash-derived RNG so that same (seed, day, tick, pair) inputs always
    produce the same boolean — preserves reproducibility without consuming
    global RNG state.

    polygon_extent_m: pass the shared-location's polygon extent (m) so large
    parks discount the noticing probability (A3 fix).
    """
    h = hash((seed, day, tick, pair[0], pair[1]))
    rng = random.Random(h)
    return rng.random() < noticing_prob(
        a_attn, b_attn, polygon_extent_m=polygon_extent_m,
    )
