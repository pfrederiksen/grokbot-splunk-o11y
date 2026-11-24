#!/usr/bin/env python3
"""Verify every non-text chart on the Grok Bot dashboards returns data.

Looks up dashboards by name (Overview / Mission Control, Bot Ops, ...), not by
a hardcoded object id. Requires SPLUNK_O11Y_API_TOKEN and SPLUNK_O11Y_REALM.
Never prints tokens.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from sfq import query  # noqa: E402

DASHBOARD_NAMES = [
    "Overview / Mission Control",
    "Bot Ops",
    "Golf",
    "Trading",
    "Birds",
    "Home",
    "Ops",
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


def dashboards_by_name() -> dict[str, str]:
    found: dict[str, str] = {}
    offset = 0
    while True:
        status, body, err = api("/v2/dashboard", {"limit": 200, "offset": offset})
        if status != 200:
            raise SystemExit(f"dashboard list failed: {status} {err}")
        results = body.get("results") or []
        for item in results:
            name = item.get("name")
            if name in DASHBOARD_NAMES and name not in found:
                found[name] = item["id"]
        if len(results) < 200:
            break
        offset += len(results)
    return found


def main() -> int:
    try:
        ids = dashboards_by_name()
    except ValueError as exc:
        print(f"verify: err={exc}")
        return 0
    missing = [name for name in DASHBOARD_NAMES if name not in ids]
    if missing:
        print(f"verify: missing dashboards={missing}")
    now = int(time.time() * 1000)
    bad = 0
    total = 0
    for name in DASHBOARD_NAMES:
        did = ids.get(name)
        if not did:
            continue
        status, dash, _ = api(f"/v2/dashboard/{did}")
        if status != 200:
            print(f"  FAIL {name}: dashboard fetch {status}")
            bad += 1
            continue
        for entry in dash.get("charts") or []:
            status, chart, _ = api(f"/v2/chart/{entry['chartId']}")
            typ = (chart.get("options") or {}).get("type")
            prog = chart.get("programText") or ""
            if typ in ("Text",):
                continue
            total += 1
            if typ == "Event":
                print(f"  ok   {name}: {chart.get('name')} (event feed)")
                continue
            series, err = query(prog, now - 3 * 3600 * 1000, now, 300000, timeout=25)
            n = sum(1 for item in series for _t, value in item["points"] if value is not None)
            ok = n > 0 and not err
            bad += 0 if ok else 1
            print(f"  {'ok  ' if ok else 'EMPTY'} {name}: {chart.get('name')} series={len(series)} pts={n} {err}")
    print(f"charts={total} empty={bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
