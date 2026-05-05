"""Lightweight `.env` loader for tools/* CLIs.

Reads KEY=VALUE lines from `<repo>/.env` into `os.environ` (no-op if absent).
Existing env vars take precedence over `.env` values (so a shell `export` still
wins). Avoids a hard dep on `python-dotenv`.

Tools that call LLM clients (`make_llm_client` from suite_stub_llm) should
`from tools._env import load_dotenv; load_dotenv()` near the top of their
module.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv() -> None:
    """Load `<repo>/.env` into `os.environ`. Idempotent; safe to call multiple times."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)
