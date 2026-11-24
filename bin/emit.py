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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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
PT = ZoneInfo("America/Los_Angeles")

METRIC_CPU = "grokbot.box.cpu.pct"
METRIC_OVERDUE = "grokbot.pipeline.overdue_count"
METRIC_WARN = "grokbot.pipeline.warn_count"
METRIC_COLLECTOR_OK = "grokbot.collector.ok"
METRIC_COLLECTOR_MS = "grokbot.collector.duration_ms"
METRIC_COLLECTOR_FAIL = "grokbot.collector.failed_count"
METRIC_GAP = "grokbot.emitter.gap_minutes"
METRIC_FAILING = "grokbot.routine.failing_count"

# NYSE full closures and 10:00 PT early closes (Trader heartbeat only).
# Keep the sample calendar current; it is not loaded from a live feed.
MARKET_CLOSED = {
    "2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
    "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}
MARKET_EARLY = {"2026-11-27", "2026-12-24", "2027-11-26"}

# Populated per run for the summary line; not exported as module state in tests
# beyond what callers pass in.
SOURCES_OK: dict[str, bool] = {}
SOURCES_ERR: dict[str, str] = {}


def default_host() -> str:
    return os.environ.get("GROKBOT_HOST") or DEFAULT_HOST


def data_root() -> Path:
    raw = os.environ.get("GROKBOT_DATA_ROOT")
    return Path(raw) if raw else Path("data")


def data_path(*parts: str) -> Path:
    return data_root().joinpath(*parts)


def now_pt() -> datetime:
    return datetime.now(PT)


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


SOURCES_MS: dict[str, float] = {}


def safe_collect(source: str, fn, out: list[dict[str, Any]]) -> None:
    started = time.time()
    try:
        points = fn() or []
        add_points(out, *points)
        mark(source, True)
    except Exception as exc:  # noqa: BLE001 — fail-soft per source
        mark(source, False, type(exc).__name__)
    SOURCES_MS[source] = (time.time() - started) * 1000.0


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



def parse_dt(value: str | None) -> datetime | None:
    """Parse a timestamp string, defaulting naive values to Pacific."""
    if not value:
        return None
    text_value = str(value).strip()
    if re.fullmatch(r"\d{13}", text_value):
        return datetime.fromtimestamp(int(text_value) / 1000, tz=PT)
    if re.fullmatch(r"\d{10}", text_value):
        return datetime.fromtimestamp(int(text_value), tz=PT)
    raw = text_value.replace("Z", "+00:00")
    try:
        if re.match(r"[A-Z][a-z]{2} \d{1,2}, \d{4}", raw):
            cleaned = re.sub(r",?\s*(PT|PST|PDT)$", "", raw).strip()
            return datetime.strptime(cleaned, "%b %d, %Y, %I:%M %p").replace(tzinfo=PT)
        if re.match(r"\d{4}-\d{2}-\d{2} ", raw):
            cleaned = re.sub(r"\s+(PT|PST|PDT|UTC|Z)$", "", raw).strip()
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    return datetime.strptime(cleaned, fmt).replace(tzinfo=PT)
                except ValueError:
                    pass
        if "T" in raw:
            if re.search(r"[+-]\d{2}:\d{2}$", raw) or raw.endswith("+00:00"):
                return datetime.fromisoformat(raw).astimezone(PT)
            return datetime.fromisoformat(raw).replace(tzinfo=PT)
        if re.match(r"\d{4}-\d{2}-\d{2}$", raw):
            return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=PT)
    except (TypeError, ValueError):
        return None
    return None


def age_seconds(ts: datetime | None, now: datetime | None = None) -> float | None:
    if not ts:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=PT)
    current = now or now_pt()
    return max(0.0, (current - ts.astimezone(PT)).total_seconds())


def file_mtime(path: str | Path) -> datetime | None:
    target = Path(path)
    if not target.exists():
        return None
    return datetime.fromtimestamp(target.stat().st_mtime, tz=PT)


def rth_slots(day: datetime) -> list[tuple[int, int]]:
    """Regular-trading-hours heartbeat slots in Pacific time.

    Weekends and MARKET_CLOSED dates have no slots. Early-close dates end at
    10:00 PT; a regular session ends at 13:00 PT. Slots start at 06:30 PT
    and repeat every 15 minutes.
    """
    date_key = day.date().isoformat()
    if day.weekday() >= 5 or date_key in MARKET_CLOSED:
        return []
    end_hour = 10 if date_key in MARKET_EARLY else 13
    slots: list[tuple[int, int]] = []
    hour, minute = 6, 30
    while (hour, minute) < (end_hour, 0):
        slots.append((hour, minute))
        minute += 15
        if minute >= 60:
            hour, minute = hour + 1, minute - 60
    return slots


def daily_slots(times: list[tuple[int, int]]):
    """Return a slots-for-day callable that ignores the calendar date."""
    return lambda day: times


def latest_slot(moment: datetime, slots_for_day) -> datetime | None:
    for back in range(0, 10):
        day = (moment - timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
        for hour, minute in sorted(slots_for_day(day), reverse=True):
            candidate = day.replace(hour=hour, minute=minute)
            if candidate <= moment:
                return candidate
    return None


def pipeline_budget_hours(now: datetime, slots_for_day, allowance: float) -> float | None:
    """Max healthy age right now: time since the latest run that should have finished, plus allowance.

    If ``slots_for_day`` is None the budget is a fixed number of hours
    (for example a nightly or weekly refresh). If no slot can be found
    in the lookback window the budget is unknown.
    """
    if slots_for_day is None:
        return float(allowance)
    slot = latest_slot(now - timedelta(hours=allowance), slots_for_day)
    if slot is None:
        return None
    return (now - slot).total_seconds() / 3600.0 + allowance


def _json_timestamp(path: Path, *keys: str):
    def _read() -> datetime | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        for key in keys:
            if payload.get(key):
                return parse_dt(str(payload.get(key)))
        return None
    return _read


def _mtime_timestamp(path: Path):
    return lambda: file_mtime(path)


def pipeline_specs() -> dict[str, tuple]:
    """name -> (last-success fn, slots-for-day or None, allowance/fixed hours).

    Paths are under GROKBOT_DATA_ROOT (default ``data/``). Collectors stay
    quiet when those optional files are absent.
    """
    root = data_root()
    return {
        "email": (_json_timestamp(root / "email" / "summary.json", "synced_at"),
                  daily_slots([(hour, 4) for hour in range(6, 23, 2)]), 1.5),
        "calendar": (_json_timestamp(root / "calendar" / "summary.json", "synced_at"),
                     daily_slots([(hour, 4) for hour in range(6, 23, 2)]), 1.5),
        "birds": (_mtime_timestamp(root / "birds" / "birds.db"),
                  daily_slots([(hour, 0) for hour in range(24)]), 1.25),
        "backup": (_mtime_timestamp(root / "backup" / "last_success"),
                   daily_slots([(2, 0)]), 5.0),
        "finance": (_json_timestamp(root / "finance" / "summary.json", "generated_at"),
                    daily_slots([(6, 0)]), 2.5),
        "home": (_json_timestamp(root / "home" / "status.json", "asOf"),
                 daily_slots([(6, 20), (10, 20), (14, 20), (18, 20), (22, 20)]), 2.0),
        "jobs": (_json_timestamp(root / "jobs" / "status.json", "run_time"),
                 daily_slots([(7, 45), (14, 45)]), 3.0),
        "trader": (_mtime_timestamp(root / "trading" / "journal.md"), rth_slots, 1.0),
        "ls_trading": (_mtime_timestamp(root / "trading" / "trading_block.ts"),
                       daily_slots([(hour, 15) for hour in range(6, 23)]), 1.0),
        "ebay": (_json_timestamp(root / "ebay" / "summary.json", "last_sync", "generated_at"),
                 None, 9.0),
        "golf": (_mtime_timestamp(root / "golf" / "ghin-data.json"), None, 8 * 24.0),
    }


def collect_pipelines(
    now: datetime | None = None,
    timestamp_ms: int | None = None,
    specs: dict[str, tuple] | None = None,
    state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Emit per-pipeline freshness gauges plus overdue/warn counts.

    Missing optional sources are skipped (not counted as overdue) so a
    fresh clone without hobby data stays quiet. An unreadable budget or
    a ratio >= 1.0 counts as overdue; 0.75 <= ratio < 1.0 is a warning.
    """
    pts: list[dict[str, Any]] = []
    current = now or now_pt()
    overdue = warn = 0
    for name, (reader, slots, allowance) in (specs or pipeline_specs()).items():
        dims = {"pipeline": name}
        try:
            ts = reader()
        except Exception:  # noqa: BLE001
            ts = None
        if ts is None:
            continue
        age = age_seconds(ts, now=current)
        budget = pipeline_budget_hours(current, slots, allowance)
        if age is None or budget is None:
            add_points(pts, gauge("grokbot.pipeline.age_ratio", 9.99, dims=dims, timestamp_ms=timestamp_ms))
            overdue += 1
            continue
        age_h = age / 3600.0
        ratio = age_h / budget if budget > 0 else 0.0
        add_points(pts, gauge("grokbot.pipeline.age_hours", age_h, dims=dims, timestamp_ms=timestamp_ms))
        add_points(pts, gauge("grokbot.pipeline.budget_hours", budget, dims=dims, timestamp_ms=timestamp_ms))
        add_points(pts, gauge("grokbot.pipeline.age_ratio", min(ratio, 9.99), dims=dims, timestamp_ms=timestamp_ms))
        if ratio >= 1.0:
            overdue += 1
        elif ratio >= 0.75:
            warn += 1
    add_points(pts, gauge(METRIC_OVERDUE, overdue, timestamp_ms=timestamp_ms))
    add_points(pts, gauge(METRIC_WARN, warn, timestamp_ms=timestamp_ms))
    add_points(pts, gauge(METRIC_FAILING, overdue, timestamp_ms=timestamp_ms))
    if state and state.get("last_success_epoch") is not None:
        try:
            last_ms = int(state["last_success_epoch"]) * 1000
            gap = ((timestamp_ms if timestamp_ms is not None else now_ms()) - last_ms) / 60000.0
            add_points(pts, gauge(METRIC_GAP, max(0.0, gap), timestamp_ms=timestamp_ms))
        except (TypeError, ValueError):
            pass
    return pts


def collect_cpu(timestamp_ms: int | None = None) -> list[dict[str, Any]]:
    """Optional Linux CPU percent from /proc/stat. Skipped on other hosts."""
    proc = Path("/proc/stat")
    if not proc.is_file():
        return []

    def _read() -> tuple[int, int]:
        parts = proc.read_text(encoding="utf-8").splitlines()[0].split()
        nums = list(map(int, parts[1:]))
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
        return idle, sum(nums)

    idle1, total1 = _read()
    time.sleep(0.05)
    idle2, total2 = _read()
    delta_total, delta_idle = (total2 - total1), (idle2 - idle1)
    cpu = (1.0 - (delta_idle / delta_total)) * 100.0 if delta_total > 0 else 0.0
    point = gauge(METRIC_CPU, max(0.0, min(100.0, cpu)), timestamp_ms=timestamp_ms)
    return [point] if point else []


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
    global SOURCES_OK, SOURCES_ERR, SOURCES_MS
    SOURCES_OK = {}
    SOURCES_ERR = {}
    SOURCES_MS = {}
    args = parse_args(argv)
    started = time.time()
    ts = now_ms()
    epoch = int(started)
    out: list[dict[str, Any]] = []
    path = state_path()
    prior = load_state(path)

    protocol = selected_protocol(args)
    tracer = None
    if protocol == "otlp":
        try:
            import otlp as otlp_mod
            tracer = otlp_mod.start_tracer()
        except Exception:
            tracer = None
    root_span = None
    if tracer is not None:
        try:
            from opentelemetry.trace import SpanKind
            root_span = tracer.start_as_current_span("emit", kind=SpanKind.SERVER)
            root_span.__enter__()
        except Exception:
            root_span = None
    try:
        safe_collect("cpu", lambda: collect_cpu(timestamp_ms=ts), out)
        safe_collect("disk", lambda: collect_disk(timestamp_ms=ts), out)
        safe_collect("mem", lambda: collect_mem(timestamp_ms=ts), out)
        safe_collect("load", lambda: collect_load(timestamp_ms=ts), out)
        safe_collect("freshness", lambda: collect_freshness(prior, now_epoch=epoch, timestamp_ms=ts), out)
        safe_collect("pipelines", lambda: collect_pipelines(timestamp_ms=ts, state=prior), out)
    finally:
        if root_span is not None:
            try:
                root_span.__exit__(None, None, None)
            except Exception:
                pass

    duration_ms = (time.time() - started) * 1000.0
    for source, ok in list(SOURCES_OK.items()):
        add_points(out, gauge(METRIC_COLLECTOR_OK, ok, dims={"collector": source}, timestamp_ms=ts))
        add_points(out, gauge(METRIC_COLLECTOR_MS, SOURCES_MS.get(source), dims={"collector": source}, timestamp_ms=ts))
    add_points(out, gauge(METRIC_COLLECTOR_FAIL, sum(1 for ok in SOURCES_OK.values() if not ok), timestamp_ms=ts))
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

    if protocol == "otlp":
        try:
            import otlp as otlp_tr
            tok, terr = otlp_tr.flush_traces()
            if not tok and terr and terr != "no_tracer":
                err = err if not success else terr
        except Exception:
            pass
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
