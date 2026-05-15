"""Subprocess-level integration test for HotfixSignalHandler + MultiDayRunner.

Spawn a real Python subprocess that runs a short multi-day simulation with
HotfixSignalHandler installed, send it SIGUSR1 mid-run, and verify:
- subprocess exits cleanly (rc==0, NOT KeyboardInterrupt/SIGKILL)
- per-day partial JSON files are written for the completed days
- result reflects truncation (per_day_summaries < num_days requested)

This is the real proof of the "热修复" promise: kill --USR1 mid-run →
graceful stop → resume-ready state.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


_CHILD_SCRIPT = """
import json, os, sys, time
from datetime import date
from pathlib import Path

sys.path.insert(0, __ROOT__)

from synthetic_socio_wind_tunnel.agent import (
    AgentProfile, AgentRuntime,
)
from synthetic_socio_wind_tunnel.atlas import Atlas
from synthetic_socio_wind_tunnel.atlas.models import Coord
from synthetic_socio_wind_tunnel.cartography.builder import RegionBuilder
from synthetic_socio_wind_tunnel.ledger import Ledger
from synthetic_socio_wind_tunnel.ledger.models import EntityState
from synthetic_socio_wind_tunnel.orchestrator import MultiDayRunner, Orchestrator
from synthetic_socio_wind_tunnel.run_resilience import HotfixSignalHandler
from datetime import datetime

OUT = Path(__OUT__)

def _atlas():
    region = (
        RegionBuilder("r", "r")
        .add_outdoor("a", "A", area_type="street")
        .polygon([(0,0),(10,0),(10,10),(0,10)])
        .end_outdoor()
        .build()
    )
    return Atlas(region)

agent = AgentRuntime(
    profile=AgentProfile(
        agent_id="alpha", name="alpha", age=30, occupation="x",
        household="single", home_location="a",
    ),
    current_location="a",
)
atlas = _atlas()
ledger = Ledger()
ledger.current_time = datetime(2026, 4, 22)
ledger.set_entity(EntityState(
    entity_id="alpha", location_id="a", position=Coord(x=0.0, y=0.0),
))
orch = Orchestrator(atlas, ledger, [agent])

runner = MultiDayRunner(
    orchestrator=orch, seed=77,
    output_dir=OUT, provider_name="stub",
)

# Slow each tick so SIGUSR1 from parent has time to land mid-loop.
# At 1ms/tick × 288 tick/day = ~290ms/day → 14 days = ~4s wall time.
import time as _time
orch.register_on_tick_end(lambda _tr: _time.sleep(0.001))

handler = HotfixSignalHandler()
handler.install(runner)

# Write a "ready" marker so the parent test knows it's safe to fire SIGUSR1
(OUT / "child_ready.txt").write_text(str(os.getpid()))

# Run for 14 days; SIGUSR1 from parent should truncate us early
result = runner.run_multi_day(
    start_date=date(2026, 4, 22), num_days=14,
)

(OUT / "child_result.json").write_text(json.dumps({
    "per_day_count": len(result.per_day_summaries),
    "graceful_stop": result.metadata.get("graceful_stop", False),
    "seed": result.seed,
}))
sys.exit(0)
"""


def test_sigusr1_subprocess_graceful_stop_and_partials(tmp_path: Path) -> None:
    venv_py = ROOT / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else sys.executable

    script = (
        _CHILD_SCRIPT
        .replace("__ROOT__", repr(str(ROOT)))
        .replace("__OUT__", repr(str(tmp_path)))
    )
    script_path = tmp_path / "child.py"
    script_path.write_text(script)

    # Start the child in its own process group so SIGUSR1 affects only it
    proc = subprocess.Popen(
        [py, str(script_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    # Wait up to 5s for the child to write child_ready.txt
    ready_path = tmp_path / "child_ready.txt"
    deadline = time.time() + 8.0
    while time.time() < deadline and not ready_path.exists():
        time.sleep(0.05)
    if not ready_path.exists():
        out, err = proc.communicate(timeout=2)
        proc.kill()
        pytest.fail(
            f"child never wrote ready marker. rc={proc.returncode}\n"
            f"stdout={out.decode()}\nstderr={err.decode()}",
        )

    child_pid = int(ready_path.read_text())
    assert child_pid == proc.pid

    # Let it run for a moment so at least 1 day completes before stop
    time.sleep(0.5)

    # Fire SIGUSR1 → graceful stop after current tick
    os.kill(child_pid, signal.SIGUSR1)

    # Wait up to 10s for child to land
    out, err = proc.communicate(timeout=15)
    rc = proc.returncode

    # 1. Clean exit
    assert rc == 0, (
        f"child should exit 0 after SIGUSR1; got rc={rc}\n"
        f"stdout={out.decode()}\nstderr={err.decode()}"
    )

    # 2. result JSON shows truncation + graceful_stop flag
    result_path = tmp_path / "child_result.json"
    assert result_path.exists(), f"no child_result.json. stderr={err.decode()}"
    data = json.loads(result_path.read_text())
    assert data["graceful_stop"] is True, (
        f"graceful_stop flag not set; data={data}"
    )
    assert data["per_day_count"] < 14, (
        f"expected truncated run < 14 days; got {data['per_day_count']}"
    )
    assert data["per_day_count"] >= 1, (
        f"at least 1 day should have completed; got {data['per_day_count']}"
    )

    # 3. partial files exist for each completed day
    partials = sorted(tmp_path.glob("seed_77_day*.partial.json"))
    assert len(partials) == data["per_day_count"], (
        f"partial count {len(partials)} != per_day_count {data['per_day_count']}; "
        f"partials={[p.name for p in partials]}"
    )

    # 4. partial JSONs are well-formed
    for p in partials:
        payload = json.loads(p.read_text())
        assert payload["schema_version"] == "1"
        assert payload["seed"] == 77
        assert payload["provider"] == "stub"
        assert "run_metrics" in payload
