#!/usr/bin/env python3
"""
fetch_popular_times — pull Popular Times for top-N Lane Cove POIs via Outscraper.

Outscraper free tier (500 businesses/month) covers our scale (~20 POIs);
single fetch ships JSON snapshot to git. See `agent-calibration` design D2.

Usage:
    OUTSCRAPER_API_KEY=... python3 tools/fetch_popular_times.py
    OUTSCRAPER_API_KEY=... python3 tools/fetch_popular_times.py --num-pois 20

Output:
    data/calibration/lanecove_popular_times.json

Schema:
    {
      "source": "Outscraper Google Maps API",
      "fetched": "2026-04-27",
      "pois": [
        {
          "id": "...", "name": "...", "place_id": "...",
          "category": "cafe|park|library|...",
          "popularity": [
            [%peak, ...24 ints],   # Mon
            ...
            [%peak, ...24 ints],   # Sun
          ]
        },
        ...
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    sys.stderr.write("error: requests not installed; pip install requests\n")
    sys.exit(2)


_OUTSCRAPER_BASE = "https://api.outscraper.cloud"
_OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "calibration" / "lanecove_popular_times.json"
_LANE_COVE_QUERY = "Lane Cove NSW Australia"


# Categories we care about for behavioral calibration
# (matches roughly what `_pick_community_location` and atlas affordances target)
_TARGET_CATEGORIES = (
    "cafe", "restaurant", "library", "park", "playground",
    "community_centre", "supermarket", "pharmacy", "school",
)


def _require_api_key() -> str:
    key = os.environ.get("OUTSCRAPER_API_KEY") or ""
    if not key:
        sys.stderr.write(
            "error: OUTSCRAPER_API_KEY env required.\n"
            "  Sign up at https://outscraper.com (free tier 500 businesses/mo).\n"
            "  Then export OUTSCRAPER_API_KEY=... and re-run.\n"
        )
        sys.exit(2)
    return key


def _outscraper_get_async(api_key: str, query: str, limit: int) -> str:
    """Submit search; return request_id (Outscraper API is async)."""
    resp = requests.get(
        f"{_OUTSCRAPER_BASE}/maps/search-v3",
        params={"query": query, "limit": limit, "language": "en", "async": "true"},
        headers={"X-API-KEY": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    request_id = payload.get("id")
    if not request_id:
        raise RuntimeError(f"Outscraper response missing id: {payload}")
    return request_id


def _outscraper_poll(
    api_key: str, request_id: str, *, max_wait_s: int = 300, poll_interval: int = 10,
) -> dict:
    """Poll Outscraper request until finished."""
    elapsed = 0
    while elapsed < max_wait_s:
        resp = requests.get(
            f"{_OUTSCRAPER_BASE}/requests/{request_id}",
            headers={"X-API-KEY": api_key},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        status = body.get("status")
        if status == "Success":
            return body
        if status == "Failed":
            raise RuntimeError(f"Outscraper request failed: {body}")
        time.sleep(poll_interval)
        elapsed += poll_interval
    raise RuntimeError(f"Outscraper request {request_id} timed out after {max_wait_s}s")


def _normalize_popularity(raw: Any) -> list[list[int]] | None:
    """
    Outscraper returns popularity as either a 7-element list of 24-int arrays
    or as a list of {day, hours: [...]} dicts. Normalize to 7×24 ints.
    """
    if raw is None:
        return None
    if isinstance(raw, list) and len(raw) == 7:
        # Two shapes possible: list-of-lists, or list-of-dicts
        if all(isinstance(d, list) and len(d) == 24 for d in raw):
            return [[int(v or 0) for v in d] for d in raw]
        if all(isinstance(d, dict) for d in raw):
            grid: list[list[int]] = []
            for d in raw:
                hours = d.get("hours") or d.get("popular_times") or [0] * 24
                if len(hours) == 24:
                    grid.append([int(v or 0) for v in hours])
                else:
                    return None
            return grid
    return None


def _classify_category(types: list[str] | None, subtypes: str | None) -> str:
    haystack = " ".join((types or [])).lower() + " " + (subtypes or "").lower()
    for cat in _TARGET_CATEGORIES:
        if cat.replace("_", " ") in haystack:
            return cat
    return "other"


def fetch(num_pois: int = 20) -> dict:
    api_key = _require_api_key()
    print(f"[fetch] querying Outscraper for {num_pois} POIs in Lane Cove...")
    rid = _outscraper_get_async(api_key, _LANE_COVE_QUERY, limit=num_pois * 2)
    print(f"[fetch] request id {rid}; polling...")
    body = _outscraper_poll(api_key, rid)

    raw_pois = body.get("data") or []
    if isinstance(raw_pois, list) and raw_pois and isinstance(raw_pois[0], list):
        raw_pois = raw_pois[0]  # nested

    pois_out = []
    for raw in raw_pois:
        if not isinstance(raw, dict):
            continue
        pop = _normalize_popularity(raw.get("popular_times"))
        if pop is None:
            continue
        pois_out.append({
            "id": raw.get("place_id") or raw.get("name", "")[:40],
            "name": raw.get("name", ""),
            "place_id": raw.get("place_id"),
            "category": _classify_category(raw.get("types"), raw.get("subtypes")),
            "lat": raw.get("latitude"),
            "lon": raw.get("longitude"),
            "popularity": pop,
        })
        if len(pois_out) >= num_pois:
            break

    return {
        "source": "Outscraper Google Maps API",
        "fetched": str(date.today()),
        "query": _LANE_COVE_QUERY,
        "n_pois": len(pois_out),
        "pois": pois_out,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch Lane Cove Popular Times")
    ap.add_argument("--num-pois", type=int, default=20)
    ap.add_argument("--output", default=str(_OUT_PATH))
    args = ap.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = fetch(num_pois=args.num_pois)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"[done] wrote {len(payload['pois'])} POIs → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
