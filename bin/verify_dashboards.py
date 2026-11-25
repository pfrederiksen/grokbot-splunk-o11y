#!/usr/bin/env python3
"""Verify every chart in the Grok Bot Splunk Observability dashboard group.

Pulls live dashboard/chart definitions, runs each SignalFlow program over a
sensible window (7d for golf, 24h otherwise), and reports per-chart
OK / EMPTY / ERROR / SKIP. Also lists detectors and active incidents.

Configuration comes only from the environment:

  SPLUNK_O11Y_API_TOKEN   required org API token
  SPLUNK_O11Y_REALM       required realm (or set SPLUNK_O11Y_API_URL)
  SPLUNK_O11Y_API_URL     optional API base, default https://api.<realm>.signalfx.com
  GROKBOT_DASHBOARD_GROUP optional group name, default "Grok Bot"
  GROKBOT_DASHBOARD_GROUP_ID  optional group id if you prefer not to search by name

Never prints tokens. Exit 0 if every data chart is OK and no unexpected
active incidents; 1 otherwise.

    python3 bin/verify_dashboards.py
    python3 bin/verify_dashboards.py --json /tmp/verify.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sfq import query  # noqa: E402

PT = ZoneInfo("America/Los_Angeles")
DEFAULT_GROUP_NAME = "Grok Bot"
# Sample detector names used when classifying "ours" vs other org detectors.
OUR_DETECTOR_PREFIXES = (
    "Emitter",
    "Box ",
    "HA ",
    "UniFi",
    "Backup",
    "Email",
    "Birds",
    "Pipeline",
)
METRIC_RE = re.compile(r"data\('([^']+)'")
ID_RE = re.compile(r"(?:HX[A-Za-z0-9_-]+|<DASHBOARD_ID_[A-Z0-9_]+>|<GROUP_ID>)")

# Last-value sanity. None = skip numeric bounds.
BOUNDS: list[tuple[re.Pattern, float, float, str]] = [
    (re.compile(r"\.pct$|fir_pct|gir_pct|volume_used_pct|win_rate$"), 0, 110, "percent-like"),
    (re.compile(r"age_ratio"), 0, 20, "ratio"),
    (re.compile(r"age_hours|last_detection_age_hours"), 0, 720, "hours"),
    (re.compile(r"age_minutes|gap_minutes"), 0, 20000, "minutes"),
    (re.compile(r"age_seconds"), 0, 30 * 86400, "seconds"),
    (re.compile(r"duration_ms"), 0, 300000, "ms"),
    (re.compile(r"ha\.up|nas\.ok|watchdog_ok|poller_running|entries_allowed|backup\.success|oldest_counting|charging$|fw_update"), 0, 1, "0/1"),
    (re.compile(r"handicap_index|low_hi|diff_to_beat|last\.differential|last\.diff_minus_hi|hi_change"), -40, 54, "golf-index"),
    (re.compile(r"temp_f"), -20, 200, "deg_f"),
    (re.compile(r"account_value|cash|equity_value|options_value|crypto_value|headroom|day_pnl_usd|week_pnl_usd|open_risk"), -20000, 200000, "usd"),
]


def api_token() -> str:
    token = (os.environ.get("SPLUNK_O11Y_API_TOKEN") or "").strip()
    if not token or (token.startswith("<") and token.endswith(">")):
        raise ValueError("missing_api_token")
    return token


def api_base() -> str:
    override = os.environ.get("SPLUNK_O11Y_API_URL")
    if override:
        return override.rstrip("/")
    realm = (os.environ.get("SPLUNK_O11Y_REALM") or "").strip()
    if not realm or (realm.startswith("<") and realm.endswith(">")):
        raise ValueError("missing_realm")
    return f"https://api.{realm}.signalfx.com"


def app_dashboard_url(dashboard_id: str, realm: str | None = None) -> str:
    override = os.environ.get("SPLUNK_O11Y_APP_URL")
    if override:
        return f"{override.rstrip('/')}/#/dashboard/{dashboard_id}"
    realm = realm if realm is not None else os.environ.get("SPLUNK_O11Y_REALM", "")
    realm = (realm or "").strip()
    if not realm or (realm.startswith("<") and realm.endswith(">")):
        return f"https://app.<REALM>.signalfx.com/#/dashboard/{dashboard_id}"
    return f"https://app.{realm}.signalfx.com/#/dashboard/{dashboard_id}"


def api(path: str, query_params: dict | None = None, timeout: int = 30):
    url = api_base() + path
    if query_params:
        url += "?" + urllib.parse.urlencode(query_params)
    request = urllib.request.Request(
        url,
        headers={"X-SF-TOKEN": api_token(), "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}"), None
    except urllib.error.HTTPError as exc:
        return exc.code, {}, f"http_{exc.code}"
    except Exception:
        typ = sys.exc_info()[0]
        return None, {}, typ.__name__ if typ else "api_error"


def now_pt() -> datetime:
    return datetime.now(PT)


def latest(points: list[tuple[int, Any]]) -> tuple[int, float] | None:
    for t, v in reversed(points):
        if v is not None and v == v:  # not NaN
            return t, float(v)
    return None


def bounds_for(metric: str) -> tuple[float, float, str] | None:
    for pat, lo, hi, label in BOUNDS:
        if pat.search(metric):
            return lo, hi, label
    return None


def window_for(chart_name: str, program: str) -> tuple[int, int, int, str]:
    """Return (start_ms, stop_ms, resolution_ms, label)."""
    stop = int(time.time() * 1000)
    blob = (chart_name + " " + program).lower()
    if "golf" in blob or "handicap" in blob or "differential" in blob or "ghin" in blob:
        return stop - 7 * 86400 * 1000, stop, 3600000, "7d"
    return stop - 24 * 3600 * 1000, stop, 900000, "24h"


def metric_for_series(stream_label: str, metrics: list[str], program: str) -> str | None:
    """Pick the data() metric that this published stream actually represents."""
    compact = program.replace(" ", "")
    label = (stream_label or "").lower()
    ratio = "grokbot.pipeline.age_ratio"
    if "age_ratio" in compact and ("*100" in compact or "% used" in label or "budget used" in label or label in {"ratio", "v", "% used"}):
        if len(metrics) == 1 and metrics[0] == ratio:
            return f"{ratio}*100"
        if "% used" in label or label == "ratio" or "budget used" in label:
            return f"{ratio}*100"
    for m in metrics:
        tail = m.split(".")[-1].replace("_", " ")
        if tail and tail in label:
            return m
        if m.split(".")[-1] in label.replace(" ", "_"):
            return m
    if len(metrics) == 1:
        if metrics[0] == ratio and "*100" in compact:
            return f"{ratio}*100"
        return metrics[0]
    return None


def sanity(metric: str, value: float) -> str | None:
    if metric == "grokbot.pipeline.age_ratio*100":
        if value < 0 or value > 2000:
            return f"insane budget-percent {value:g} not in [0, 2000]"
        return None
    b = bounds_for(metric)
    if not b:
        return None
    lo, hi, label = b
    if value < lo or value > hi:
        return f"insane {label} {value:g} not in [{lo}, {hi}] (metric {metric})"
    return None


def verify_program(name: str, program: str) -> dict[str, Any]:
    start, stop, res, win = window_for(name, program)
    series, err = query(program, start, stop, res, timeout=30)
    metrics = METRIC_RE.findall(program)
    n_pts = 0
    last_vals: list[dict[str, Any]] = []
    issues: list[str] = []
    for s in series:
        pts = [(t, v) for t, v in s.get("points") or [] if v is not None]
        n_pts += len(pts)
        lv = latest(s.get("points") or [])
        if not lv:
            continue
        ts, val = lv
        dims = s.get("dims") or {}
        label = str(dims.get("sf_streamLabel") or "")
        metric = metric_for_series(label, metrics, program)
        msg = sanity(metric, val) if metric else None
        last_vals.append({
            "value": val,
            "ts": datetime.fromtimestamp(ts / 1000, PT).strftime("%Y-%m-%d %H:%M PT"),
            "dims": {
                k: v
                for k, v in dims.items()
                if k not in ("sf_metric", "sf_streamLabel", "computationId", "host")
                and not str(k).startswith("_SF")
            },
            "stream": label,
            "metric": metric,
        })
        if msg:
            issues.append(msg)
    if err:
        status = "ERROR"
        issues.append(f"signalflow: {err}")
    elif n_pts == 0:
        status = "EMPTY"
    elif issues:
        status = "WARN"
    else:
        status = "OK"
    return {
        "status": status,
        "window": win,
        "series": len(series),
        "points": n_pts,
        "metrics": metrics,
        "last": last_vals[:8],
        "issues": issues,
    }


def check_text_links(markdown: str, known_ids: set[str]) -> list[str]:
    issues = []
    text = markdown or ""
    for hid in ID_RE.findall(text):
        if hid in known_ids:
            continue
        if f"/dashboard/{hid}" in text and hid not in known_ids:
            issues.append(f"text link points at unknown dashboard id {hid}")
    return issues


def resolve_group_id() -> str:
    explicit = (os.environ.get("GROKBOT_DASHBOARD_GROUP_ID") or "").strip()
    if explicit and not (explicit.startswith("<") and explicit.endswith(">")):
        return explicit
    want = (os.environ.get("GROKBOT_DASHBOARD_GROUP") or DEFAULT_GROUP_NAME).strip()
    offset = 0
    while True:
        status, body, err = api("/v2/dashboardgroup", {"limit": 200, "offset": offset})
        if status != 200:
            raise SystemExit(f"dashboard group list failed: {status} {err}")
        results = body.get("results") or []
        for item in results:
            if item.get("name") == want:
                return item["id"]
        if len(results) < 200:
            break
        offset += len(results)
    raise SystemExit(f"dashboard group not found: {want}")


def pull_group() -> tuple[list[dict], dict[str, dict], set[str]]:
    group_id = resolve_group_id()
    st, g, err = api(f"/v2/dashboardgroup/{group_id}")
    if st != 200 or not isinstance(g, dict):
        raise SystemExit(f"failed to read dashboard group: {st} {err}")
    dashes = []
    charts: dict[str, dict] = {}
    ids = set(g.get("dashboards") or [])
    ids.add(group_id)
    for did in g.get("dashboards") or []:
        st, d, err = api(f"/v2/dashboard/{did}")
        if st != 200 or not isinstance(d, dict):
            dashes.append({"id": did, "name": "?", "error": err or f"http_{st}", "charts": []})
            continue
        ids.add(did)
        items = []
        for c in sorted(d.get("charts") or [], key=lambda x: (x.get("row", 0), x.get("column", 0))):
            cid = c.get("chartId")
            st, ch, err = api(f"/v2/chart/{cid}")
            charts[cid] = ch if isinstance(ch, dict) else {}
            items.append({**c, "chart": charts[cid], "fetch_error": err})
        dashes.append({
            "id": did,
            "name": d.get("name"),
            "description": d.get("description"),
            "filters": d.get("filters"),
            "charts": items,
        })
    return dashes, charts, ids, group_id  # type: ignore[return-value]


def is_our_detector(name: str | None) -> bool:
    text = name or ""
    return text.startswith(OUR_DETECTOR_PREFIXES) or text.startswith("Emitter collector")


def detectors_report() -> dict[str, Any]:
    st, dets, err = api("/v2/detector", {"limit": 200})
    results = dets.get("results", []) if isinstance(dets, dict) else []
    ours, other = [], []
    for d in results:
        rec = {
            "id": d.get("id"),
            "name": d.get("name"),
            "status": d.get("status"),
            "overMTSLimit": d.get("overMTSLimit"),
            "program": (d.get("programText") or "").replace("\n", " ; ")[:240],
            "disabled": [r.get("disabled") for r in (d.get("rules") or [])],
        }
        if is_our_detector(d.get("name")):
            ours.append(rec)
        elif (d.get("name") or "").startswith("Splunk operational"):
            continue
        else:
            other.append(rec)
    st, inc, _ = api("/v2/incident", {"limit": 50})
    items = inc if isinstance(inc, list) else (inc.get("results") if isinstance(inc, dict) else []) or []
    active = [i for i in items if (i.get("anomalyState") or "").upper() not in ("OK", "STOPPED", "")]
    return {
        "ours": ours,
        "other_non_operational": other,
        "active_incidents": [
            {
                "detector": i.get("detectorName"),
                "state": i.get("anomalyState"),
                "severity": i.get("severity"),
                "label": i.get("detectLabel"),
            }
            for i in active
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", dest="json_path", default="", help="write full report JSON to this path")
    ap.add_argument("--quiet", action="store_true", help="only print a per-dashboard summary and failures")
    args = ap.parse_args(argv)

    try:
        dashes, _, known_ids, group_id = pull_group()  # type: ignore[misc]
    except ValueError as exc:
        print(f"verify: err={exc}")
        return 0

    report: dict[str, Any] = {
        "as_of": now_pt().strftime("%Y-%m-%d %H:%M PT"),
        "group": group_id,
        "dashboards": [],
        "counts": {"OK": 0, "EMPTY": 0, "ERROR": 0, "WARN": 0, "SKIP": 0},
    }
    lines: list[str] = []

    for d in dashes:
        drec = {
            "id": d["id"],
            "name": d.get("name"),
            "url": app_dashboard_url(d["id"]),
            "charts": [],
            "counts": {"OK": 0, "EMPTY": 0, "ERROR": 0, "WARN": 0, "SKIP": 0},
        }
        if d.get("error"):
            drec["error"] = d["error"]
            report["dashboards"].append(drec)
            continue
        for item in d["charts"]:
            ch = item.get("chart") or {}
            typ = (ch.get("options") or {}).get("type") or "?"
            name = ch.get("name") or item.get("chartId")
            prog = ch.get("programText") or ""
            rec: dict[str, Any] = {
                "id": item.get("chartId"),
                "name": name,
                "type": typ,
                "row": item.get("row"),
                "column": item.get("column"),
            }
            if typ == "Text":
                issues = check_text_links((ch.get("options") or {}).get("markdown") or "", known_ids)
                rec["status"] = "WARN" if issues else "SKIP"
                rec["issues"] = issues
            elif typ == "Event":
                rec["status"] = "SKIP"
                rec["note"] = "event feed (not a metric query)"
            elif item.get("fetch_error") and typ == "?":
                rec["status"] = "ERROR"
                rec["issues"] = [item["fetch_error"]]
            else:
                rec.update(verify_program(name, prog))
            drec["charts"].append(rec)
            drec["counts"][rec["status"]] = drec["counts"].get(rec["status"], 0) + 1
            report["counts"][rec["status"]] = report["counts"].get(rec["status"], 0) + 1
            flag = rec["status"]
            if flag in ("EMPTY", "ERROR", "WARN") or not args.quiet:
                issue = ("; ".join(rec.get("issues") or [])) or rec.get("note") or ""
                last = ""
                if rec.get("last"):
                    last = " last=" + ",".join(f"{x['value']:g}" for x in rec["last"][:4])
                lines.append(f"  {flag:<5} {drec['name']}: {name}{last} {issue}".rstrip())
        report["dashboards"].append(drec)

    det = detectors_report()
    report["detectors"] = det
    stuck = [d for d in det["ours"] if (d.get("status") or "ACTIVE") not in ("ACTIVE",) or d.get("overMTSLimit")]
    report["detector_issues"] = stuck

    print(f"as of {report['as_of']}")
    for drec in report["dashboards"]:
        c = drec["counts"]
        print(
            f"{drec['name']} {drec['url']}: "
            f"OK={c['OK']} WARN={c['WARN']} EMPTY={c['EMPTY']} ERROR={c['ERROR']} SKIP={c['SKIP']}"
        )
    for line in lines:
        if args.quiet and line[2:7].strip() not in ("EMPTY", "ERROR", "WARN"):
            continue
        if line.startswith("  "):
            print(line)
    tot = report["counts"]
    print(
        f"TOTAL data-charts: OK={tot['OK']} WARN={tot['WARN']} EMPTY={tot['EMPTY']} ERROR={tot['ERROR']}  "
        f"(SKIP text/event={tot['SKIP']})"
    )
    print(
        f"our detectors: {len(det['ours'])}  issues: {len(stuck) or 0}  "
        f"active incidents: {len(det['active_incidents'])}"
    )
    for i in det["active_incidents"]:
        print(f"  INCIDENT {i}")
    for d in stuck:
        print(f"  DETECTOR ISSUE {d['name']} status={d['status']} overMTS={d['overMTSLimit']}")

    if args.json_path:
        Path(args.json_path).write_text(json.dumps(report, indent=2) + "\n")
        print(f"wrote {args.json_path}")

    bad = tot["EMPTY"] + tot["ERROR"] + len(stuck)
    our_names = {d["name"] for d in det["ours"]}
    bad += sum(1 for i in det["active_incidents"] if i.get("detector") in our_names)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
