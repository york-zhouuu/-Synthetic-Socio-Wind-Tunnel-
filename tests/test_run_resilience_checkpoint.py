"""Tests for synthetic_socio_wind_tunnel.run_resilience.checkpoint."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from synthetic_socio_wind_tunnel.run_resilience.checkpoint import (
    DayCheckpointWriter,
    IncompatibleCheckpointError,
)


def _make_payload() -> dict[str, object]:
    return {
        "run_metrics": {"foo": 1, "bar": [1, 2, 3]},
        "ledger_snapshot": {"agents": {"a1": "home_1"}},
        "memory_dump": {"a1": {"events": []}},
    }


def test_write_and_read_round_trip(tmp_path: Path) -> None:
    w = DayCheckpointWriter()
    payload = _make_payload()
    out = w.write_partial(
        output_dir=tmp_path, seed=42, day_index=5,
        simulated_date=date(2026, 4, 27),
        run_metrics=payload["run_metrics"],  # type: ignore[arg-type]
        ledger_snapshot=payload["ledger_snapshot"],  # type: ignore[arg-type]
        memory_dump=payload["memory_dump"],  # type: ignore[arg-type]
        provider="deepseek",
    )
    assert out == tmp_path / "seed_42_day5.partial.json"
    assert out.exists()

    loaded = w.read_partial(out)
    assert loaded["seed"] == 42
    assert loaded["day_index"] == 5
    assert loaded["simulated_date"] == "2026-04-27"
    assert loaded["provider"] == "deepseek"
    assert loaded["schema_version"] == "1"
    assert loaded["run_metrics"] == payload["run_metrics"]
    assert loaded["ledger_snapshot"] == payload["ledger_snapshot"]
    assert loaded["memory_dump"] == payload["memory_dump"]
    assert "created_at" in loaded


def test_partial_includes_all_required_fields(tmp_path: Path) -> None:
    w = DayCheckpointWriter()
    out = w.write_partial(
        output_dir=tmp_path, seed=1, day_index=0,
        simulated_date=date(2026, 1, 1),
        run_metrics={}, ledger_snapshot={}, memory_dump={},
        provider="stub",
    )
    data = json.loads(out.read_text())
    for required in (
        "schema_version", "seed", "day_index", "simulated_date",
        "run_metrics", "ledger_snapshot", "memory_dump",
        "provider", "created_at",
    ):
        assert required in data, f"missing field {required}"


def test_atomic_no_partial_residue_after_normal_write(tmp_path: Path) -> None:
    w = DayCheckpointWriter()
    w.write_partial(
        output_dir=tmp_path, seed=1, day_index=0,
        simulated_date=date(2026, 1, 1),
        run_metrics={}, ledger_snapshot={}, memory_dump={},
        provider="stub",
    )
    leftover_tmps = list(tmp_path.glob("*.tmp"))
    assert leftover_tmps == []


def test_atomic_leaves_unrelated_tmp_alone(tmp_path: Path) -> None:
    """harden-worker-resilience: a stale .tmp from a crashed run is NOT
    swept by write_partial — it might be a concurrent worker's in-flight
    tmp. Each write uses a unique tmp name (tempfile.mkstemp) so orphan
    .tmp residue is harmless.
    """
    stale = tmp_path / "seed_42_day3.partial.json.tmp"
    tmp_path.mkdir(exist_ok=True)
    stale.write_text("not ours — could be a concurrent worker mid-write")
    w = DayCheckpointWriter()
    target = w.write_partial(
        output_dir=tmp_path, seed=42, day_index=4,
        simulated_date=date(2026, 1, 1),
        run_metrics={}, ledger_snapshot={}, memory_dump={},
        provider="stub",
    )
    # New partial landed correctly
    assert target.exists()
    # Unrelated tmp is preserved (left for its owner)
    assert stale.exists()
    # Our own tmp is cleaned up by the rename
    own_tmps = [p for p in tmp_path.glob("*.tmp") if p != stale]
    assert own_tmps == []


def test_read_partial_incompatible_schema_raises(tmp_path: Path) -> None:
    bad = tmp_path / "seed_1_day0.partial.json"
    bad.write_text(json.dumps({"schema_version": "99", "seed": 1, "day_index": 0}))
    w = DayCheckpointWriter()
    with pytest.raises(IncompatibleCheckpointError) as exc_info:
        w.read_partial(bad)
    assert "99" in str(exc_info.value)
    assert exc_info.value.expected == "1"
    assert exc_info.value.found == "99"


def test_cleanup_partials_removes_only_target_seed(tmp_path: Path) -> None:
    w = DayCheckpointWriter()
    for d in range(3):
        w.write_partial(
            output_dir=tmp_path, seed=42, day_index=d,
            simulated_date=date(2026, 1, 1 + d),
            run_metrics={}, ledger_snapshot={}, memory_dump={},
            provider="stub",
        )
    # 不同 seed 的 partial 应保留
    w.write_partial(
        output_dir=tmp_path, seed=99, day_index=0,
        simulated_date=date(2026, 1, 1),
        run_metrics={}, ledger_snapshot={}, memory_dump={},
        provider="stub",
    )
    removed = w.cleanup_partials(output_dir=tmp_path, seed=42)
    assert len(removed) == 3
    assert not list(tmp_path.glob("seed_42_*"))
    assert (tmp_path / "seed_99_day0.partial.json").exists()


def test_cleanup_partials_keeps_final_seed_json(tmp_path: Path) -> None:
    final = tmp_path / "seed_42.json"
    final.write_text("{}")
    w = DayCheckpointWriter()
    w.write_partial(
        output_dir=tmp_path, seed=42, day_index=0,
        simulated_date=date(2026, 1, 1),
        run_metrics={}, ledger_snapshot={}, memory_dump={},
        provider="stub",
    )
    w.cleanup_partials(output_dir=tmp_path, seed=42)
    assert final.exists()  # final 不带 _day 模式，不会被清


def test_find_latest_partial_returns_highest_day(tmp_path: Path) -> None:
    w = DayCheckpointWriter()
    for d in (0, 1, 5, 3):
        w.write_partial(
            output_dir=tmp_path, seed=7, day_index=d,
            simulated_date=date(2026, 1, 1 + d),
            run_metrics={}, ledger_snapshot={}, memory_dump={},
            provider="stub",
        )
    latest = w.find_latest_partial(output_dir=tmp_path, seed=7)
    assert latest is not None
    assert latest.name == "seed_7_day5.partial.json"


def test_find_latest_partial_none_when_empty(tmp_path: Path) -> None:
    w = DayCheckpointWriter()
    assert w.find_latest_partial(output_dir=tmp_path, seed=99) is None


def test_write_large_memory_dump_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    # 构造一个 > 200 MB 的 dump：用 250 万条 ~100 字节的 fake event
    big = {"events": ["x" * 80 for _ in range(2_500_000)]}
    w = DayCheckpointWriter()
    with caplog.at_level("WARNING"):
        w.write_partial(
            output_dir=tmp_path, seed=1, day_index=0,
            simulated_date=date(2026, 1, 1),
            run_metrics={}, ledger_snapshot={},
            memory_dump={"agent_1": big},
            provider="stub",
        )
    assert any("200 MB" in rec.message for rec in caplog.records)
