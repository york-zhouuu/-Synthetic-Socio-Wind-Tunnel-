"""
Agent Perception Inspector — dump SubjectiveView for a given (seed, agent, day, tick).

A1 / realism-perception-loop debug tool. Pure read-only CLI.

Future: data feed for 2.5D 沙盘 (C3) inspector panel.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta

from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.cartography.lanecove import (
    create_atlas_from_osm,
)
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.perception import PerceptionPipeline
from synthetic_socio_wind_tunnel.perception.models import ObserverContext


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--agent", type=str, required=True,
                   help="Agent ID (e.g. a_42_0001)")
    p.add_argument("--day", type=int, default=0)
    p.add_argument("--tick", type=int, default=0)
    p.add_argument("--location", type=str, default=None,
                   help="Override agent's location (debug)")
    return p.parse_args(argv)


def _build_minimal_ledger(agent_id: str, location_id: str) -> Ledger:
    """Build a minimal ledger with one entity at the given location."""
    led = Ledger()
    led.current_time = datetime(2026, 4, 21, 8, 0)
    led.set_entity(EntityState(
        entity_id=agent_id,
        position=Coord(x=0.0, y=0.0),
        location_id=location_id,
    ))
    return led


def _format_section(title: str, lines: list[str]) -> str:
    if not lines:
        return f"  ({title}: 无)\n"
    return f"  {title}:\n" + "\n".join(f"    - {line}" for line in lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    sim_time = datetime(2026, 4, 21) + timedelta(
        days=args.day, minutes=args.tick * 5,
    )

    location_id = args.location or "home"

    try:
        atlas = create_atlas_from_osm()
    except Exception as exc:
        print(f"error: failed to load atlas: {exc}", file=sys.stderr)
        return 2

    if not args.agent or not args.agent.strip():
        print("error: --agent is required and must be non-empty", file=sys.stderr)
        return 2

    led = _build_minimal_ledger(args.agent, location_id)

    try:
        area = atlas.get_outdoor_area(location_id)
    except Exception:
        area = None
    if area is None:
        print(
            f"error: location {location_id!r} not in atlas; "
            f"pass --location <valid_id>",
            file=sys.stderr,
        )
        return 2

    pipeline = PerceptionPipeline(atlas=atlas, ledger=led)

    obs_ctx = ObserverContext(
        entity_id=args.agent,
        position=Coord(x=0.0, y=0.0),
        location_id=location_id,
    )

    try:
        view = pipeline.render(obs_ctx)
    except Exception as exc:
        print(f"error: perception render failed: {exc}", file=sys.stderr)
        return 3

    print(f"=== {args.agent} @ day {args.day} tick {args.tick} "
          f"({sim_time.strftime('%H:%M')}) ===")
    print(f"  Location: {view.location_id} ({view.location_name})\n")

    visible_lines = [
        f"{e.entity_id} ({e.distance:.1f}m, kind=agent"
        + (f", activity={e.activity}" if e.activity else "")
        + ")"
        for e in view.entity_snapshots
    ]
    print(_format_section("Visible entities", visible_lines), end="")

    item_lines = [
        f"{i.name} ({i.distance:.1f}m"
        + (f", state={i.visible_state}" if i.visible_state else "")
        + ")"
        for i in view.item_snapshots
    ]
    print(_format_section("Visible items", item_lines), end="")

    audible_lines = list(view.ambient_sounds)
    print(_format_section("Audible", audible_lines), end="")

    smell_lines = list(view.ambient_smells)
    print(_format_section("Smells", smell_lines), end="")

    print(f"  Lighting: {view.lighting} | Weather: {view.weather}\n")

    payload = view.model_dump(mode="json")
    print(f"\nJSON: {json.dumps(payload, ensure_ascii=False)[:400]}...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
