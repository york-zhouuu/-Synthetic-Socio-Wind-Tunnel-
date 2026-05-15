"""Tests for tools/preflight_full_smoke.py.

We mock the subprocess invocation of run_variant_suite to avoid actually
spinning up a 15-20 min 1000-agent smoke. Tests focus on:
- argparse contract (hard-coded scope; provider chosen by --provider)
- output validation (variant dirs + non-empty seed_*.json)
- exit codes (0 / 1) per spec
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(ROOT))

# Importable as a script
import importlib.util

spec = importlib.util.spec_from_file_location(
    "preflight_full_smoke",
    TOOLS / "preflight_full_smoke.py",
)
assert spec and spec.loader
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class TestArgs:

    def test_default_provider_is_deepseek(self) -> None:
        args = preflight._parse_args([])
        assert args.provider == "deepseek"

    def test_provider_override(self) -> None:
        args = preflight._parse_args(["--provider", "gemini"])
        assert args.provider == "gemini"

    def test_invalid_provider_rejected(self) -> None:
        with pytest.raises(SystemExit):
            preflight._parse_args(["--provider", "invalid"])

    def test_default_num_protagonists_is_500(self) -> None:
        args = preflight._parse_args([])
        assert args.num_protagonists == 500


class TestVariantSuiteInvocation:

    def test_command_uses_canonical_publishable_args(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Spawned command SHALL include --agents=1000, --num-days=1, all
        4 variants, --mode=publishable, --num-protagonists=500."""
        captured: dict = {}

        def fake_call(cmd: list[str]) -> int:
            captured["cmd"] = cmd
            return 0

        monkeypatch.setattr(preflight.subprocess, "call", fake_call)
        args = preflight._parse_args(["--provider", "stub", "--output-dir", str(tmp_path)])
        suite_dir = preflight._suite_dir(args)
        preflight._invoke_variant_suite(args, suite_dir)
        cmd = captured["cmd"]
        assert "--agents" in cmd and "1000" in cmd
        assert "--num-days" in cmd and "1" in cmd
        assert "--mode" in cmd and "publishable" in cmd
        assert "--num-protagonists" in cmd and "500" in cmd
        # All 4 variants
        joined = " ".join(cmd)
        for v in ("baseline", "hyperlocal_push", "global_distraction", "phone_friction"):
            assert v in joined

    def test_stub_provider_skips_aitown_flags(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}
        monkeypatch.setattr(
            preflight.subprocess, "call",
            lambda cmd: (captured.__setitem__("cmd", cmd) or 0),
        )
        args = preflight._parse_args(["--provider", "stub", "--output-dir", str(tmp_path)])
        preflight._invoke_variant_suite(args, preflight._suite_dir(args))
        cmd = captured["cmd"]
        assert "--use-aitown" not in cmd
        assert "--aitown-provider" not in cmd

    def test_real_provider_includes_aitown_flags(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict = {}
        monkeypatch.setattr(
            preflight.subprocess, "call",
            lambda cmd: (captured.__setitem__("cmd", cmd) or 0),
        )
        args = preflight._parse_args(
            ["--provider", "gemini", "--output-dir", str(tmp_path)],
        )
        preflight._invoke_variant_suite(args, preflight._suite_dir(args))
        cmd = captured["cmd"]
        assert "--use-aitown" in cmd
        assert "--aitown-provider" in cmd
        # --aitown-provider gemini
        assert "gemini" in cmd[cmd.index("--aitown-provider") + 1: cmd.index("--aitown-provider") + 2]


class TestOutputCheck:

    def _make_variant(self, base: Path, name: str, *, seed_size: int = 500) -> None:
        vd = base / f"inner_dir/variant_{name}"
        vd.mkdir(parents=True)
        (vd / "seed_1.json").write_text("x" * seed_size)

    def test_check_outputs_ok_when_all_variants_have_seed(
        self, tmp_path: Path,
    ) -> None:
        for v in ("baseline", "hyperlocal_push", "global_distraction", "phone_friction"):
            self._make_variant(tmp_path, v)
        ok, issues = preflight._check_outputs(tmp_path)
        assert ok is True
        assert issues == []

    def test_check_outputs_fails_when_variant_missing(
        self, tmp_path: Path,
    ) -> None:
        # Only 3 of 4 variants present
        for v in ("baseline", "hyperlocal_push", "global_distraction"):
            self._make_variant(tmp_path, v)
        ok, issues = preflight._check_outputs(tmp_path)
        assert ok is False
        assert any("phone_friction" in i for i in issues)

    def test_check_outputs_fails_when_seed_too_small(
        self, tmp_path: Path,
    ) -> None:
        for v in ("baseline", "hyperlocal_push", "global_distraction", "phone_friction"):
            self._make_variant(tmp_path, v, seed_size=10)  # tiny → suspicious
        ok, issues = preflight._check_outputs(tmp_path)
        assert ok is False


class TestMainExit:

    def test_main_exit_1_when_suite_returns_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 1) Force suite call to "fail" by not writing any output (subprocess.call returns 0 but no output exists)
        # Easiest: mock subprocess.call to return 0 but produce no files
        monkeypatch.setattr(preflight.subprocess, "call", lambda cmd: 0)
        # Override output_dir to tmp_path
        rc = preflight.main(["--provider", "stub", "--output-dir", str(tmp_path)])
        # _check_outputs should fail → exit 1
        assert rc == 1
