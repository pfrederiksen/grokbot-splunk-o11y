#!/usr/bin/env python3
"""Collect basic Grok Bot gauges and POST one batch to Splunk Observability Cloud.

Stdlib only. Read-only collectors. Fail-soft per source. Always exit 0.
Print a one-line summary. Never print or log secrets.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

METRIC_DISK = "grokbot.box.disk.pct"
METRIC_MEM = "grokbot.box.mem.pct"
METRIC_LOAD = "grokbot.box.load.1"
METRIC_AGE = "grokbot.routine.age_seconds"
METRIC_OK = "grokbot.emitter.ok"
METRIC_DURATION = "grokbot.emitter.duration_ms"
METRIC_DATAPOINTS = "grokbot.emitter.datapoints"

DEFAULT_HOST = "example-box"
DEFAULT_STATE = Path(".state/emit-status.json")
INGEST_PATH = "/v2/datapoint"
ALERT_THRESHOLD = 2

# Populated per run for the summary line; not exported as module state in tests
# beyond what callers pass in.
SOURCES_OK: dict[str, bool] = {}
SOURCES_ERR: dict[str, str] = {}


def default_host() -> str:
    return os.environ.get("GROKBOT_HOST") or DEFAULT_HOST


def disk_path() -> str:
    return os.environ.get("GROKBOT_DISK_PATH") or "/"


def state_path() -> Path:
    raw = os.environ.get("GROKBOT_STATE_FILE")
    return Path(raw) if raw else DEFAULT_STATE


def ingest_url(realm: str | None = None) -> str:
    override = os.environ.get("SPLUNK_O11Y_INGEST_URL")
    if override:
        return override
    realm = realm if realm is not None else os.environ.get("SPLUNK_O11Y_REALM", "")
    realm = (realm or "").strip()
    if not realm:
        raise ValueError("missing_realm")
    # Do not accept placeholder text as a realm.
    if realm.startswith("<") and realm.endswith(">"):
        raise ValueError("missing_realm")
    return f"https://ingest.{realm}.signalfx.com{INGEST_PATH}"


def now_ms() -> int:
    return int(time.time() * 1000)


def gauge(
    metric: str,
    value: Any,
    dims: dict[str, str] | None = None,
    timestamp_ms: int | None = None,
    host: str | None = None,
) -> dict[str, Any] | None:
    """Build one SignalFx gauge datapoint, or None if the value is not finite."""
    if value is None:
        return None
    try:
        if isinstance(value, bool):
            num = 1.0 if value else 0.0
        else:
            num = float(value)
        if num != num or num in (float("inf"), float("-inf")):
            return None
    except (TypeError, ValueError):
        return None
    dimensions = {"host": host or default_host()}
    if dims:
        for key, val in dims.items():
            if val is not None:
                dimensions[str(key)] = str(val)
    ts = int(timestamp_ms if timestamp_ms is not None else now_ms())
    return {
        "metric": metric,
        "value": num,
        "dimensions": dimensions,
        "timestamp": ts,
    }


def add_points(out: list[dict[str, Any]], *points: Any) -> None:
    for item in points:
        if item is None:
            continue
        if isinstance(item, dict):
            out.append(item)
        else:
            for point in item:
                if point:
                    out.append(point)


def build_payload(points: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {"gauge": list(points)}


def count_mts(points: list[dict[str, Any]]) -> int:
    unique = {
        (p["metric"], tuple(sorted(p.get("dimensions", {}).items())))
        for p in points
        if isinstance(p, dict) and "metric" in p
    }
    return len(unique)


def mark(source: str, ok: bool, err: str = "") -> None:
    SOURCES_OK[source] = ok
    if not ok and err:
        SOURCES_ERR[source] = err[:80]


def safe_collect(source: str, fn, out: list[dict[str, Any]]) -> None:
    try:
        points = fn() or []
        add_points(out, *points)
        mark(source, True)
    except Exception as exc:  # noqa: BLE001 — fail-soft per source
        mark(source, False, type(exc).__name__)


def empty_state() -> dict[str, Any]:
    return {
        "consecutive_failures": 0,
        "last_success_epoch": None,
        "last_run_epoch": None,
        "last_error": "",
    }


def load_state(path: Path) -> dict[str, Any]:
    state = empty_state()
    if not path.is_file():
        return state
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return state
    if isinstance(loaded, dict):
        state.update(loaded)
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def record_result(
    state: dict[str, Any],
    success: bool,
    error: str = "",
    now_epoch: int | None = None,
) -> dict[str, Any]:
    """Pure failure-counter update. Does not touch the filesystem."""
    updated = dict(state)
    epoch = int(now_epoch if now_epoch is not None else time.time())
    updated["last_run_epoch"] = epoch
    if success:
        updated["consecutive_failures"] = 0
        updated["last_success_epoch"] = epoch
        updated["last_error"] = ""
    else:
        failures = int(updated.get("consecutive_failures") or 0) + 1
        updated["consecutive_failures"] = failures
        updated["last_error"] = (error or "error")[:80]
    return updated


def should_alert(state: dict[str, Any], threshold: int = ALERT_THRESHOLD) -> bool:
    return int(state.get("consecutive_failures") or 0) >= int(threshold)


def routine_age_seconds(state: dict[str, Any], now_epoch: int | None = None) -> float | None:
    last = state.get("last_success_epoch")
    if last is None:
        return None
    try:
        last_i = int(last)
    except (TypeError, ValueError):
        return None
    epoch = int(now_epoch if now_epoch is not None else time.time())
    return float(max(0, epoch - last_i))


def collect_disk(path: str | None = None, timestamp_ms: int | None = None) -> list[dict[str, Any]]:
    usage = shutil.disk_usage(path or disk_path())
    if usage.total <= 0:
        raise RuntimeError("disk_total_zero")
    pct = (usage.used / usage.total) * 100.0
    point = gauge(METRIC_DISK, pct, timestamp_ms=timestamp_ms)
    return [point] if point else []


def _mem_pct_proc() -> float:
    text = Path("/proc/meminfo").read_text(encoding="utf-8")
    values: dict[str, int] = {}
    for line in text.splitlines():
        match = re.match(r"^(\w+):\s+(\d+)", line)
        if match:
            values[match.group(1)] = int(match.group(2))
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total:
        raise RuntimeError("meminfo_missing_total")
    if available is None:
        free = values.get("MemFree", 0)
        buffers = values.get("Buffers", 0)
        cached = values.get("Cached", 0)
        available = free + buffers + cached
    used = max(0, total - available)
    return (used / total) * 100.0


def _mem_pct_darwin() -> float:
    page_size = 4096
    stats: dict[str, int] = {}
    raw = subprocess.check_output(["vm_stat"], text=True, timeout=5)
    for line in raw.splitlines():
        size_match = re.search(r"page size of (\d+) bytes", line)
        if size_match:
            page_size = int(size_match.group(1))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        digits = re.search(r"(\d+)", value)
        if digits:
            stats[key.strip()] = int(digits.group(1))
    total = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=5))
    if total <= 0:
        raise RuntimeError("memsize_zero")
    free_pages = stats.get("Pages free", 0) + stats.get("Pages speculative", 0)
    used = total - (free_pages * page_size)
    return max(0.0, min(100.0, (used / total) * 100.0))


def collect_mem(timestamp_ms: int | None = None) -> list[dict[str, Any]]:
    if Path("/proc/meminfo").is_file():
        pct = _mem_pct_proc()
    elif sys.platform == "darwin":
        pct = _mem_pct_darwin()
    else:
        raise RuntimeError("mem_unsupported")
    point = gauge(METRIC_MEM, pct, timestamp_ms=timestamp_ms)
    return [point] if point else []


def collect_load(timestamp_ms: int | None = None) -> list[dict[str, Any]]:
    load1, _load5, _load15 = os.getloadavg()
    point = gauge(METRIC_LOAD, load1, timestamp_ms=timestamp_ms)
    return [point] if point else []


def collect_freshness(
    state: dict[str, Any],
    now_epoch: int | None = None,
    timestamp_ms: int | None = None,
) -> list[dict[str, Any]]:
    age = routine_age_seconds(state, now_epoch=now_epoch)
    point = gauge(METRIC_AGE, age, timestamp_ms=timestamp_ms)
    return [point] if point else []


def ingest(payload: dict[str, Any], url: str, token: str, timeout: int = 15) -> tuple[int | None, str]:
    """POST a datapoint batch. Returns (status, error_token). Never includes the token."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-SF-TOKEN": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            if status in (200, 204):
                return status, "ok"
            return status, f"http_{status}"
    except urllib.error.HTTPError as exc:
        return int(exc.code), f"http_{exc.code}"
    except urllib.error.URLError:
        return None, "url_error"
    except TimeoutError:
        return None, "timeout"
    except OSError:
        return None, "os_error"


def summary_line(
    *,
    status: int | str | None,
    points: int,
    mts: int,
    duration_ms: float,
    sources_fail: list[str],
    err: str,
    alert: bool,
) -> str:
    fail_note = ",".join(sources_fail) if sources_fail else "none"
    ingest_note = "err" if status is None else str(status)
    return (
        f"o11y emit: ingest={ingest_note} points={points} mts~{mts} "
        f"ms={duration_ms:.0f} sources_fail={fail_note} err={err} "
        f"alert={'yes' if alert else 'no'}"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit basic Grok Bot gauges to Splunk Observability Cloud.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the payload and print a redacted summary without posting.",
    )
    parser.add_argument(
        "--protocol",
        choices=("signalfx", "otlp"),
        default=None,
        help="Ingest protocol. Default: otlp (OTLP/HTTP). "
        "signalfx is the legacy /v2/datapoint path and should not be combined with otlp in the same org.",
    )
    return parser.parse_args(argv)


def selected_protocol(args: argparse.Namespace | None = None) -> str:
    raw = (args.protocol if args is not None and args.protocol else None) or os.environ.get("GROKBOT_O11Y_PROTOCOL") or "otlp"
    raw = str(raw).strip().lower()
    if raw not in {"signalfx", "otlp"}:
        return "otlp"
    return raw


def run(argv: list[str] | None = None) -> int:
    global SOURCES_OK, SOURCES_ERR
    SOURCES_OK = {}
    SOURCES_ERR = {}
    args = parse_args(argv)
    started = time.time()
    ts = now_ms()
    epoch = int(started)
    out: list[dict[str, Any]] = []
    path = state_path()
    prior = load_state(path)

    safe_collect("disk", lambda: collect_disk(timestamp_ms=ts), out)
    safe_collect("mem", lambda: collect_mem(timestamp_ms=ts), out)
    safe_collect("load", lambda: collect_load(timestamp_ms=ts), out)
    safe_collect("freshness", lambda: collect_freshness(prior, now_epoch=epoch, timestamp_ms=ts), out)

    duration_ms = (time.time() - started) * 1000.0
    add_points(out, gauge(METRIC_OK, 1, timestamp_ms=ts))
    add_points(out, gauge(METRIC_DURATION, duration_ms, timestamp_ms=ts))
    add_points(out, gauge(METRIC_DATAPOINTS, 0, timestamp_ms=ts))
    for point in out:
        if point["metric"] == METRIC_DATAPOINTS:
            point["value"] = float(len(out))
            break

    payload = build_payload(out)
    mts = count_mts(out)
    failed_sources = [name for name, ok in SOURCES_OK.items() if not ok]
    dry_run = args.dry_run or os.environ.get("GROKBOT_DRY_RUN") == "1"

    if dry_run:
        metrics = ",".join(sorted({p["metric"] for p in out}))
        print(
            summary_line(
                status="dry-run",
                points=len(out),
                mts=mts,
                duration_ms=duration_ms,
                sources_fail=failed_sources,
                err=f"ok metrics={metrics}",
                alert=False,
            )
        )
        return 0

    token = (os.environ.get("SPLUNK_O11Y_INGEST_TOKEN") or "").strip()
    if not token or (token.startswith("<") and token.endswith(">")):
        updated = record_result(prior, False, "missing_ingest_token", now_epoch=epoch)
        try:
            save_state(path, updated)
        except OSError:
            pass
        print(
            summary_line(
                status="err",
                points=len(out),
                mts=mts,
                duration_ms=duration_ms,
                sources_fail=failed_sources or ["secrets"],
                err="missing_ingest_token",
                alert=should_alert(updated),
            )
        )
        return 0

    try:
        url = ingest_url()
    except ValueError as exc:
        err = str(exc) or "missing_realm"
        updated = record_result(prior, False, err, now_epoch=epoch)
        try:
            save_state(path, updated)
        except OSError:
            pass
        print(
            summary_line(
                status="err",
                points=len(out),
                mts=mts,
                duration_ms=duration_ms,
                sources_fail=failed_sources or ["config"],
                err=err,
                alert=should_alert(updated),
            )
        )
        return 0

    protocol = selected_protocol(args)
    if protocol == "otlp":
        import otlp as otlp_mod
        if not otlp_mod.sdk_available():
            status, err = None, "missing_otel_sdk"
        else:
            status, err = otlp_mod.export_gauges(out, token, realm=os.environ.get("SPLUNK_O11Y_REALM")) if out else (None, "no_points")
    else:
        status, err = ingest(payload, url, token) if out else (None, "no_points")
    success = status in (200, 204)
    updated = record_result(prior, success, err if not success else "", now_epoch=epoch)
    try:
        save_state(path, updated)
    except OSError:
        mark("state", False, "OSError")
        failed_sources = [name for name, ok in SOURCES_OK.items() if not ok]

    print(
        summary_line(
            status=status,
            points=len(out),
            mts=mts,
            duration_ms=duration_ms,
            sources_fail=failed_sources,
            err=err if not success else "ok",
            alert=should_alert(updated),
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except Exception:  # noqa: BLE001 — scheduler-friendly; type name only
        exc_type = sys.exc_info()[0]
        name = exc_type.__name__ if exc_type else "fatal"
        print(
            summary_line(
                status="err",
                points=0,
                mts=0,
                duration_ms=0,
                sources_fail=["fatal"],
                err=name,
                alert=False,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
