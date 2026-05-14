"""PositionTraceRecorder — sparse per-tick agent position logging.

Subscribes to Orchestrator on_tick_end hook. Records only position CHANGES
(not every tick) per agent, so storage scales with movement, not time.

A 100-agent × 14-day baseline run produces ~28k entries (~1MB JSON);
1000-agent × 14-day ~280k (~10MB). Well within HTML-embeddable range.

The recorder writes a separate `seed_<N>_positions.json` file in the suite
output dir to keep the main metrics JSON lean.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synthetic_socio_wind_tunnel.orchestrator.models import TickResult


@dataclass
class PositionChange:
    """One agent moving from one location to another at a specific tick."""
    tick: int
    day_index: int
    agent_id: str
    location_id: str  # the NEW location (where they are at end-of-tick)


class PositionTraceRecorder:
    """Accumulate sparse per-agent position-change events.

    Idempotent: re-running the same tick on the same agent won't double-record
    when the location hasn't changed. Memory-bounded by total moves, not by
    tick count × agent count.
    """

    __slots__ = ("_last_location", "_changes", "_initial_recorded")

    def __init__(self) -> None:
        self._last_location: dict[str, str] = {}
        self._changes: list[PositionChange] = []
        self._initial_recorded: bool = False

    def on_tick_end(self, tick_result: "TickResult") -> None:
        """Record per-agent location changes for this tick.

        For agents that walked through multiple street segments within
        this tick (movement_traces present), records EACH segment as a
        distinct change so the trajectory follows the real street network.

        For agents that stayed put or only have end-of-tick info, falls
        back to entity_locations.
        """
        tick = tick_result.tick_index
        day = tick_result.day_index

        # Agents whose intra-tick path is known
        traced_agents: set[str] = set()
        for agent_id, locations in tick_result.movement_traces:
            traced_agents.add(agent_id)
            for loc_id in locations:
                if not loc_id:
                    continue
                prev = self._last_location.get(agent_id)
                if prev == loc_id:
                    continue
                self._changes.append(PositionChange(
                    tick=tick, day_index=day, agent_id=agent_id,
                    location_id=loc_id,
                ))
                self._last_location[agent_id] = loc_id

        # Stationary agents — only end-of-tick location
        for agent_id, loc_id in tick_result.entity_locations:
            if agent_id in traced_agents:
                continue  # already covered by movement_traces above
            if not loc_id:
                continue
            prev = self._last_location.get(agent_id)
            if prev == loc_id:
                continue
            self._changes.append(PositionChange(
                tick=tick, day_index=day, agent_id=agent_id,
                location_id=loc_id,
            ))
            self._last_location[agent_id] = loc_id

    def to_dict(self) -> dict:
        """Serialize for JSON output."""
        return {
            "schema": "position_trace_v1",
            "n_agents": len(self._last_location),
            "n_changes": len(self._changes),
            "changes": [
                {
                    "tick": c.tick, "day": c.day_index,
                    "agent_id": c.agent_id, "location_id": c.location_id,
                }
                for c in self._changes
            ],
        }

    def write(self, path: Path) -> None:
        """Write trace to a JSON file.

        C5 capacity fix: when the trace is large (>500K changes ~ 15-20MB),
        also write a gzipped sibling `<path>.gz` to save publishable-run
        disk (1000 agent × 14d × 15 seed × 4 variants estimated ~6.6GB raw
        → ~1GB gzipped). Plain JSON kept for tooling compatibility.
        """
        data = self.to_dict()
        text = json.dumps(data, ensure_ascii=False)
        path.write_text(text, encoding="utf-8")
        if len(self._changes) > 500_000:
            import gzip
            gz_path = path.with_suffix(path.suffix + ".gz")
            gz_path.write_bytes(gzip.compress(text.encode("utf-8")))

    @property
    def total_changes(self) -> int:
        return len(self._changes)
