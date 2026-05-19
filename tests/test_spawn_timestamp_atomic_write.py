"""Layer 3 — timestamp atomic-write fault injection (Phase G4).

Spec: openspec/specs/worker-spawn-coordination/spec.md
Requirement: "spawn timestamp 持久化协议" — atomic write via tempfile+rename.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest


def _get_helpers():
    from tools.resume_publishable import (
        _read_last_spawn_timestamp,
        _write_last_spawn_timestamp,
    )
    return _read_last_spawn_timestamp, _write_last_spawn_timestamp


@pytest.fixture
def tmp_ts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "spawn-ts.json"
    monkeypatch.setenv("SPAWN_STAGGER_TIMESTAMP_FILE", str(path))
    return path


def test_atomic_write_uses_tempfile_rename(tmp_ts: Path) -> None:
    """spec: atomic write SHALL use tempfile + os.rename (not in-place write)."""
    import os as _os
    _, write_ts = _get_helpers()
    # Spy on os.rename to verify it's called
    rename_calls: list = []
    orig_rename = _os.rename

    def _spy_rename(src, dst):
        rename_calls.append((str(src), str(dst)))
        return orig_rename(src, dst)

    with patch("os.rename", _spy_rename):
        write_ts({"seed": 42, "variant": "baseline"})
    assert len(rename_calls) >= 1
    # At least one rename target is the timestamp file
    targets = {dst for _, dst in rename_calls}
    assert str(tmp_ts) in targets


def test_disk_full_during_write_logs_and_continues(
    tmp_ts: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """spec: OSError on write SHALL log warning + NOT raise (caller continues)."""
    _, write_ts = _get_helpers()
    import logging
    with patch("tempfile.NamedTemporaryFile",
               side_effect=OSError("simulated disk full")):
        with caplog.at_level(logging.WARNING):
            # Must not raise
            write_ts({"seed": 42, "variant": "baseline"})
    # A warning SHALL have been logged
    warns = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warns) >= 1


def test_concurrent_read_during_write_sees_old_or_new_never_partial(
    tmp_ts: Path,
) -> None:
    """spec: atomic write SHALL ensure readers never see partial JSON.

    Stress: 1 writer + 4 readers in a barrier, 20 iterations. Every
    successful read SHALL parse as valid JSON. (If write were in-place,
    a reader could see truncated content.)
    """
    read_ts, write_ts = _get_helpers()
    # Seed initial value
    write_ts({"seed": 1, "variant": "v0"})

    n_iters = 20
    barrier = threading.Barrier(5)
    errors: list[Exception] = []

    def _writer():
        barrier.wait()
        for i in range(n_iters):
            try:
                write_ts({"seed": i, "variant": f"v{i}"})
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

    def _reader():
        barrier.wait()
        for _ in range(n_iters * 2):
            try:
                data = read_ts()
                if data is not None:
                    # Must be valid dict with documented keys
                    assert "last_spawn_epoch" in data, data
                    assert "version" in data, data
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            time.sleep(0)  # yield

    threads = [threading.Thread(target=_writer)] + [
        threading.Thread(target=_reader) for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"concurrent stress saw errors: {errors[:3]}"
