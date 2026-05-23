"""Extract rich per-agent data from simulation snapshot:
- All push notifications Mary/Mike received (real content + delivery timestamps)
- Their final plans (with reason / social_intent)
- Their memory hints (recent encounters with names)
- Their familiar agents
- Their current dialogue if any

Output: data/analysis/case_studies/{mary,mike}_snapshot_data.json
"""
import json
import ijson
from pathlib import Path
from decimal import Decimal

REPO = Path("/Users/york_z/Documents/GitHub/-Synthetic-Socio-Wind-Tunnel-")
SNAP_HP = REPO / "data/experiments/20260521_185100_publishable_v6_day4to13_fork_seed43_BACKUP_20260522_143245/variant_hyperlocal_push/seed_43_pid69976_tick4020.snapshot.json"
OUT_DIR = REPO / "data/analysis/case_studies"


def decimal_to_float(o):
    if isinstance(o, Decimal): return float(o)
    if isinstance(o, dict): return {k: decimal_to_float(v) for k, v in o.items()}
    if isinstance(o, list): return [decimal_to_float(x) for x in o]
    return o


AGENT_IDS = {
    "mary": "a_43_0405",
    "mike": "a_43_0192",
    "agent_12": "a_43_0012",
}


def extract_agent_data(aid):
    """Extract for one agent: runtime state + push history + dialogue."""
    data = {"agent_id": aid, "runtime_state": None, "push_deliveries": [],
            "push_contents": {}, "dialogues_involved": [], "encounters_recent": []}

    print(f"\nExtracting for {aid}...")

    # 1. Runtime state for this agent
    with open(SNAP_HP) as f:
        for item in ijson.items(f, f"agent_runtime_states.{aid}"):
            data["runtime_state"] = decimal_to_float(item)
            break

    # 2. All push deliveries to this agent
    delivered_feed_ids = []
    with open(SNAP_HP) as f:
        for entry in ijson.items(f, "attention_service_state.delivery_log.item"):
            if entry.get("recipient_id") == aid:
                data["push_deliveries"].append(decimal_to_float(entry))
                delivered_feed_ids.append(entry["feed_item_id"])
    print(f"  push deliveries: {len(data['push_deliveries'])}")

    # 3. Push content lookup — stream feed_index to find matching IDs
    needed = set(delivered_feed_ids)
    found_count = 0
    with open(SNAP_HP) as f:
        # feed_index is a dict; iterate keys
        for fid, item in ijson.kvitems(f, "attention_service_state.feed_index"):
            if fid in needed:
                data["push_contents"][fid] = decimal_to_float(item)
                found_count += 1
                if found_count >= len(needed): break
    print(f"  push contents fetched: {len(data['push_contents'])}")

    # 4. Dialogues involving this agent — peek dialogue_service_state
    with open(SNAP_HP) as f:
        try:
            for item in ijson.items(f, "dialogue_service_state"):
                if isinstance(item, dict):
                    # Look for keys mentioning this agent
                    for sub_key in list(item.keys())[:5]:
                        v = item[sub_key]
                        if isinstance(v, dict):
                            for k2 in list(v.keys())[:5]:
                                if aid in k2 or aid in str(v.get(k2, ""))[:200]:
                                    data["dialogues_involved"].append({sub_key: k2, "preview": str(v[k2])[:300]})
                break
        except Exception as e:
            print(f"  dialogue parse err: {e}")

    return data


for label, aid in AGENT_IDS.items():
    data = extract_agent_data(aid)
    out_path = OUT_DIR / f"{label}_snapshot_data.json"
    json.dump(data, open(out_path, "w"), ensure_ascii=False, indent=2)
    print(f"  -> {out_path} ({out_path.stat().st_size / 1e3:.1f} KB)")

    # Summary
    print(f"\n  {label} summary:")
    if data["runtime_state"]:
        rs = data["runtime_state"]
        print(f"    current_location: {rs.get('current_location')}")
        plan = rs.get("plan", {})
        if plan and plan.get("steps"):
            for step in plan["steps"]:
                print(f"    plan step: {step.get('activity')} (reason={step.get('reason')})")
        hints = rs.get("hints", {})
        if hints.get("recent_memory_hint"):
            print(f"    recent memories:")
            for m in hints["recent_memory_hint"][:5]:
                print(f"      - {m}")
    pushes_by_day = {}
    for p in data["push_deliveries"]:
        day = p["delivered_at"][:10]
        pushes_by_day.setdefault(day, 0)
        pushes_by_day[day] += 1
    print(f"    pushes by day: {pushes_by_day}")
