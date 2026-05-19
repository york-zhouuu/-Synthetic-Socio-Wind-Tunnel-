"""RuntimeInstrumentation — process-singleton structured event emitter.

Spec: openspec/specs/runtime-instrumentation/spec.md (created by
comprehensive-runtime-instrumentation 2026-05-20).

Design: openspec/changes/comprehensive-runtime-instrumentation/design.md

Three JSONL outputs + sparse human-readable log lines. Best-effort:
any emit failure logs warning and continues without raising —埋点
SHALL NOT crash the worker.
"""

from __future__ import annotations

import atexit
import gc
import json
import logging
import os
import random
import sys
import threading
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TextIO


logger = logging.getLogger(__name__)


_SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _read_current_rss_mb() -> tuple[int, int]:
    """Return (current_rss_mb, peak_rss_mb_ru_maxrss).

    Tries psutil first (true current RSS). Falls back to
    `resource.getrusage().ru_maxrss` (LIFETIME PEAK, not current) with
    a warning — the ru_maxrss path can cause RSS caps to misfire after
    a single high-RSS event.

    Returns (rss_mb, peak_mb). When psutil unavailable, both are equal
    (ru_maxrss filled into both fields).
    """
    peak = 0
    try:
        import resource
        ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            peak = ru // (1024 * 1024)
        else:
            peak = ru // 1024
    except (ImportError, OSError):
        peak = 0

    try:
        import psutil  # noqa: F401
        try:
            current = (
                psutil.Process().memory_info().rss // (1024 * 1024)
            )
            return current, peak
        except (psutil.Error, OSError):
            pass
    except ImportError:
        logger.warning(
            "[instrumentation] psutil unavailable; falling back to "
            "ru_maxrss (LIFETIME PEAK, not current RSS) — RSS cap may "
            "misfire after a single high-RSS event",
        )
        return peak, peak

    # psutil import worked but readings failed — same fallback
    return peak, peak


def _read_vms_mb() -> int:
    try:
        import psutil
        return psutil.Process().memory_info().vms // (1024 * 1024)
    except Exception:  # noqa: BLE001
        return 0


def _read_uss_mb() -> int | None:
    """USS = unique set size, the most accurate "what this process owns"
    measure. Not always available (requires elevated privileges on macOS).
    """
    try:
        import psutil
        return psutil.Process().memory_full_info().uss // (1024 * 1024)
    except Exception:  # noqa: BLE001
        return None


def _read_thread_count() -> int:
    try:
        import psutil
        return psutil.Process().num_threads()
    except Exception:  # noqa: BLE001
        return threading.active_count()


def _read_open_fds() -> int | None:
    try:
        import psutil
        return psutil.Process().num_fds()
    except Exception:  # noqa: BLE001
        return None


def _read_cpu_times() -> tuple[float, float]:
    """Return (user_sec, sys_sec) for this process."""
    try:
        import psutil
        ct = psutil.Process().cpu_times()
        return float(ct.user), float(ct.system)
    except Exception:  # noqa: BLE001
        try:
            import resource
            ru = resource.getrusage(resource.RUSAGE_SELF)
            return ru.ru_utime, ru.ru_stime
        except (ImportError, OSError):
            return 0.0, 0.0


def _read_cpu_percent() -> float:
    """Rolling CPU percent. First call returns 0.0 (psutil warms up)."""
    try:
        import psutil
        return psutil.Process().cpu_percent(interval=None)
    except Exception:  # noqa: BLE001
        return 0.0


# ---------------------------------------------------------------------------
# No-op stub
# ---------------------------------------------------------------------------


class _NoOpStub:
    """Returned by get_instrumentation() when INSTRUMENTATION_DISABLE=1.

    All emit methods are silent no-ops. No file IO performed.
    """

    def emit_event(self, **kwargs: Any) -> None:
        pass

    def emit_llm_call(self, **kwargs: Any) -> None:
        pass

    def emit_snapshot_write(self, **kwargs: Any) -> None:
        pass

    def sample_metrics(self, **kwargs: Any) -> None:
        pass

    def shutdown(self, reason: str = "noop") -> None:
        pass


# ---------------------------------------------------------------------------
# Real instrumentation
# ---------------------------------------------------------------------------


class RuntimeInstrumentation:
    """Process-singleton structured event emitter.

    Construct via `from_env()` — reads INSTRUMENTATION_* env vars.
    Accessed in module via `get_instrumentation()`.
    """

    def __init__(
        self,
        *,
        output_dir: Path,
        seed: int,
        sample_every_n_ticks: int = 12,
        llm_sample_rate: float = 0.01,
        llm_record_errors_all: bool = True,
    ) -> None:
        self._output_dir = output_dir
        self._seed = seed
        self._sample_every_n_ticks = sample_every_n_ticks
        self._llm_sample_rate = max(0.0, min(1.0, llm_sample_rate))
        self._llm_record_errors_all = llm_record_errors_all

        self._memstat_fh: Optional[TextIO] = None
        self._events_fh: Optional[TextIO] = None
        self._llm_fh: Optional[TextIO] = None

        # Sampling state for memstat (between calls)
        self._last_sample_monotonic = time.monotonic()
        self._last_sample_tick_global = 0
        # Throwaway first cpu_percent() call to warm up psutil
        _read_cpu_percent()

        # Phase / shutdown tracking
        self._process_start_emitted = False
        self._shutdown_emitted = False
        self._rng = random.Random(seed * 1000 + 7)

    @classmethod
    def from_env(cls) -> RuntimeInstrumentation:
        output_dir = Path(
            os.environ.get("INSTRUMENTATION_OUTPUT_DIR", "."),
        )
        try:
            seed = int(os.environ.get("INSTRUMENTATION_SEED", "0"))
        except ValueError:
            seed = 0
        try:
            sample_every = int(
                os.environ.get("INSTRUMENTATION_SAMPLE_EVERY_N_TICKS", "12"),
            )
        except ValueError:
            sample_every = 12
        try:
            llm_rate = float(os.environ.get("LLM_SAMPLE_RATE", "0.01"))
        except ValueError:
            llm_rate = 0.01
        record_all = os.environ.get(
            "LLM_RECORD_ERRORS_ALL", "true",
        ).strip().lower() in ("1", "true", "yes")

        inst = cls(
            output_dir=output_dir, seed=seed,
            sample_every_n_ticks=sample_every,
            llm_sample_rate=llm_rate,
            llm_record_errors_all=record_all,
        )
        # Open files lazily on first emit (don't create empties)
        atexit.register(inst._atexit_handler)
        return inst

    # ---- file management ----

    def _ensure_files(self) -> None:
        if self._events_fh is not None:
            return
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            base = f"seed_{self._seed}"
            self._memstat_fh = open(
                self._output_dir / f"{base}.memstat.jsonl",
                "a", buffering=1, encoding="utf-8",
            )
            self._events_fh = open(
                self._output_dir / f"{base}.events.jsonl",
                "a", buffering=1, encoding="utf-8",
            )
            self._llm_fh = open(
                self._output_dir / f"{base}.llm.jsonl",
                "a", buffering=1, encoding="utf-8",
            )
        except OSError as exc:
            logger.warning(
                "[instrumentation] failed to open JSONL files in %s: %s",
                self._output_dir, exc,
            )

    def _close_files(self) -> None:
        for fh in (self._memstat_fh, self._events_fh, self._llm_fh):
            if fh is not None:
                try:
                    fh.flush()
                    fh.close()
                except OSError:
                    pass
        self._memstat_fh = self._events_fh = self._llm_fh = None

    # ---- emit ----

    def emit_event(self, *, kind: str, **kw: Any) -> None:
        """Append a single event line to events.jsonl. Best-effort."""
        try:
            self._ensure_files()
            rss_mb, _ = _read_current_rss_mb()
            payload = {
                "v": _SCHEMA_VERSION,
                "ts_iso": _now_iso(),
                "ts_monotonic": time.monotonic(),
                "kind": kind,
                "rss_mb": rss_mb,
                **kw,
            }
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            fh = self._events_fh
            if fh is None:
                return
            fh.write(line)
            fh.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[instrumentation] emit_event(%s) failed: %s",
                kind, exc,
            )

    def emit_llm_call(
        self, *,
        tier: str, provider: str, model: str,
        kind: str, agent_id: str | None,
        latency_ms: int, status: str,
        attempt: int, max_attempts: int,
        exc_class: str | None = None,
        key_id: int | None = None,
        prompt_chars: int | None = None,
        response_chars: int | None = None,
    ) -> None:
        """Sampled per LLM_SAMPLE_RATE for status='success'; 100% for
        errors when LLM_RECORD_ERRORS_ALL=true (default)."""
        try:
            # Sampling decision
            is_success = status == "success"
            if is_success:
                if self._llm_sample_rate <= 0:
                    return
                if self._rng.random() > self._llm_sample_rate:
                    return
            else:
                if not self._llm_record_errors_all:
                    if self._rng.random() > self._llm_sample_rate:
                        return

            self._ensure_files()
            payload = {
                "v": _SCHEMA_VERSION,
                "ts_iso": _now_iso(),
                "tier": tier, "provider": provider, "model": model,
                "kind": kind, "agent_id": agent_id,
                "key_id": key_id,
                "attempt": attempt, "max_attempts": max_attempts,
                "latency_ms": latency_ms, "status": status,
                "exc_class": exc_class,
                "prompt_chars": prompt_chars,
                "response_chars": response_chars,
            }
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            fh = self._llm_fh
            if fh is None:
                return
            fh.write(line)
            fh.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[instrumentation] emit_llm_call failed: %s", exc)

    def emit_snapshot_write(
        self, *, tick_global: int, path: str,
        duration_sec: float,
        rss_before_mb: int, rss_peak_during_mb: int, rss_after_mb: int,
        events_evicted_before_write: int = 0,
    ) -> None:
        """Emit SNAPSHOT_WRITE event with actual file size (read at
        emit time, not trusted from caller).

        `events_evicted_before_write` reflects the count freed by
        `prune-before-snapshot-write` immediately before write_atomic
        (2026-05-20); 0 when disabled or before grace window."""
        try:
            size_bytes: int | None = None
            try:
                size_bytes = os.path.getsize(path)
            except OSError:
                size_bytes = 0
            self.emit_event(
                kind="SNAPSHOT_WRITE", tick_global=tick_global,
                path=path, duration_sec=duration_sec,
                size_bytes=size_bytes,
                rss_before_mb=rss_before_mb,
                rss_peak_during_mb=rss_peak_during_mb,
                rss_after_mb=rss_after_mb,
                events_evicted_before_write=events_evicted_before_write,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[instrumentation] emit_snapshot_write failed: %s", exc,
            )

    def sample_metrics(
        self, *, tick_global: int, day_index: int, tick_in_day: int,
        memory_service: Any = None, dialogue_service: Any = None,
        llm_tracker: Any = None, handler_times: dict | None = None,
        sim_time_iso: str | None = None,
    ) -> None:
        """Append one memstat sample. Caller passes optional refs so we
        can avoid global lookups."""
        try:
            self._ensure_files()
            now = time.monotonic()
            wall_since_last = now - self._last_sample_monotonic
            ticks_since_last = (
                tick_global - self._last_sample_tick_global
            )
            self._last_sample_monotonic = now
            self._last_sample_tick_global = tick_global

            rss_mb, peak_mb = _read_current_rss_mb()
            user_sec, sys_sec = _read_cpu_times()

            # memory_store stats
            ms_stats: dict[str, Any] = {
                "agents": 0, "total_events": 0, "events_by_kind": {},
            }
            if memory_service is not None:
                try:
                    stores = getattr(memory_service, "_stores", {}) or {}
                    ms_stats["agents"] = len(stores)
                    by_kind: dict[str, int] = {}
                    total = 0
                    for store in stores.values():
                        events = getattr(store, "_events", None)
                        if events is None:
                            continue
                        total += len(events)
                        for ev in events:
                            k = getattr(ev, "kind", "unknown")
                            by_kind[k] = by_kind.get(k, 0) + 1
                    ms_stats["total_events"] = total
                    ms_stats["events_by_kind"] = by_kind
                except Exception:  # noqa: BLE001
                    pass

            # dialogue_service stats
            ds_stats: dict[str, Any] = {"live": 0, "evicted_total": 0}
            if dialogue_service is not None:
                try:
                    ds_stats["live"] = len(getattr(
                        dialogue_service, "_active_dialogues", {},
                    ) or {})
                    ds_stats["evicted_total"] = getattr(
                        dialogue_service, "_evicted_count", 0,
                    )
                except Exception:  # noqa: BLE001
                    pass

            # llm_health stats
            llm_stats: dict[str, Any] = {
                "rolling_fallback_rate": 0.0,
                "rolling_sample_n": 0,
                "keys_open": 0, "keys_total": 0,
            }
            if llm_tracker is not None:
                try:
                    rate, n = llm_tracker.rolling_rate()
                    llm_stats["rolling_fallback_rate"] = rate
                    llm_stats["rolling_sample_n"] = n
                except Exception:  # noqa: BLE001
                    pass

            gc_count = gc.get_count()
            payload = {
                "v": _SCHEMA_VERSION,
                "ts_iso": _now_iso(),
                "ts_monotonic": now,
                "tick_global": tick_global,
                "day_index": day_index,
                "tick_in_day": tick_in_day,
                "sim_time_iso": sim_time_iso,
                "memory": {
                    "rss_mb": rss_mb,
                    "vms_mb": _read_vms_mb(),
                    "uss_mb": _read_uss_mb(),
                    "rss_peak_mb": peak_mb,
                    "open_fds": _read_open_fds(),
                    "threads": _read_thread_count(),
                },
                "cpu": {
                    "percent_recent": _read_cpu_percent(),
                    "user_sec": user_sec, "sys_sec": sys_sec,
                    "wall_since_last_sample_sec": wall_since_last,
                    "tick_count_since_last_sample": ticks_since_last,
                },
                "gc": {
                    "gen0": gc_count[0] if len(gc_count) > 0 else 0,
                    "gen1": gc_count[1] if len(gc_count) > 1 else 0,
                    "gen2": gc_count[2] if len(gc_count) > 2 else 0,
                },
                "memory_store": ms_stats,
                "dialogue_service": ds_stats,
                "llm_health": llm_stats,
                "handler_times_sec": handler_times or {},
            }
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            fh = self._memstat_fh
            if fh is None:
                return
            fh.write(line)
            fh.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[instrumentation] sample_metrics failed: %s", exc,
            )

    def shutdown(self, reason: str = "normal") -> None:
        if self._shutdown_emitted:
            return
        self._shutdown_emitted = True
        rss_mb, _ = _read_current_rss_mb()
        self.emit_event(
            kind="PHASE", phase="EXIT", reason=reason,
            final_rss_mb=rss_mb,
        )
        self._close_files()

    def _atexit_handler(self) -> None:
        if not self._shutdown_emitted:
            self.shutdown(reason="atexit")


# ---------------------------------------------------------------------------
# Process singleton
# ---------------------------------------------------------------------------


_GLOBAL: Optional[RuntimeInstrumentation] = None
_IS_NOOP: bool = False


def get_instrumentation():
    """Return process-wide RuntimeInstrumentation (or _NoOpStub when
    INSTRUMENTATION_DISABLE=1)."""
    global _GLOBAL, _IS_NOOP
    if _GLOBAL is not None:
        return _GLOBAL
    if os.environ.get("INSTRUMENTATION_DISABLE", "").strip() == "1":
        _IS_NOOP = True
        _GLOBAL = _NoOpStub()  # type: ignore[assignment]
        return _GLOBAL

    inst = RuntimeInstrumentation.from_env()
    _GLOBAL = inst
    # First-ever instantiation emits PROCESS_START
    if not inst._process_start_emitted:
        inst._process_start_emitted = True
        inst.emit_event(kind="PHASE", phase="PROCESS_START",
                        pid=os.getpid(),
                        python=sys.version.split()[0])
    return inst


def reset_for_tests() -> None:
    """Clear the module singleton + close any open files. Test-only."""
    global _GLOBAL, _IS_NOOP
    if _GLOBAL is not None and not _IS_NOOP:
        try:
            _GLOBAL._close_files()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    _GLOBAL = None
    _IS_NOOP = False
