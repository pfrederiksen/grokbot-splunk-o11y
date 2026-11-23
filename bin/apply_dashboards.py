#!/usr/bin/env python3
"""Create or update the Bot Health dashboard and detectors via the Observability Cloud API.

Stdlib only. Idempotent: look up each object by name, then create or update.
Support --dry-run (print the JSON that would be sent; no network).
Never print or log token values.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

GROUP_NAME = "Grok Bot"
DASHBOARD_NAME = "Bot Health"
PLACEHOLDER_EMAIL = "alerts@example.com"

METRIC_DISK = "grokbot.box.disk.pct"
METRIC_MEM = "grokbot.box.mem.pct"
METRIC_LOAD = "grokbot.box.load.1"
METRIC_AGE = "grokbot.routine.age_seconds"
METRIC_OK = "grokbot.emitter.ok"
METRIC_DURATION = "grokbot.emitter.duration_ms"

DISK_THRESHOLD = 85
MEM_THRESHOLD = 90
SILENT_LASTING = "20m"
THRESHOLD_LASTING = "15m"
STALE_SECONDS = 21600  # 6 hours


def api_base(realm: str | None = None) -> str:
    override = os.environ.get("SPLUNK_O11Y_API_URL")
    if override:
        return override.rstrip("/")
    realm = realm if realm is not None else os.environ.get("SPLUNK_O11Y_REALM", "")
    realm = (realm or "").strip()
    if not realm or (realm.startswith("<") and realm.endswith(">")):
        raise ValueError("missing_realm")
    return f"https://api.{realm}.signalfx.com"


def chart_definitions() -> list[dict[str, Any]]:
    """SignalFlow charts for the Bot Health dashboard, in layout order."""
    return [
        {
            "name": "Disk used %",
            "programText": f"data('{METRIC_DISK}').publish('disk')\n",
            "description": "Root filesystem percent used on the Grok Bot box.",
        },
        {
            "name": "Memory used %",
            "programText": f"data('{METRIC_MEM}').publish('mem')\n",
            "description": "Memory percent used on the Grok Bot box.",
        },
        {
            "name": "Load average (1m)",
            "programText": f"data('{METRIC_LOAD}').publish('load')\n",
            "description": "One-minute load average.",
        },
        {
            "name": "Emitter heartbeat",
            "programText": f"data('{METRIC_OK}').publish('ok')\n",
            "description": "1 when the emitter produced a batch. The silent detector fires if this stops arriving.",
        },
        {
            "name": "Routine freshness",
            "programText": f"data('{METRIC_AGE}').publish('age')\n",
            "description": "Seconds since the last successful ingest.",
        },
        {
            "name": "Emitter duration",
            "programText": f"data('{METRIC_DURATION}').publish('duration')\n",
            "description": "Emitter runtime in milliseconds.",
        },
    ]


def _chart_options() -> dict[str, Any]:
    return {
        "type": "TimeSeriesChart",
        "axisPrecision": 0,
        "defaultPlotType": "line",
        "showEventLines": False,
    }


def chart_payload(definition: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": definition["name"],
        "description": definition.get("description", ""),
        "programText": definition["programText"],
        "options": _chart_options(),
    }


def dashboard_definition(group_id: str | None = None, chart_ids: list[str] | None = None) -> dict[str, Any]:
    """Bot Health dashboard body. chart_ids may be placeholders in dry-run."""
    charts = chart_definitions()
    ids = chart_ids if chart_ids is not None else [f"<CHART_ID_{i}>" for i in range(len(charts))]
    layout = []
    # 12-column grid, two charts per row, width 6, height 1.
    for index, chart_id in enumerate(ids):
        row, column = divmod(index, 2)
        layout.append(
            {
                "chartId": chart_id,
                "row": row,
                "column": column * 6,
                "height": 1,
                "width": 6,
            }
        )
    body: dict[str, Any] = {
        "name": DASHBOARD_NAME,
        "description": (
            "Basic Grok Bot health: box disk, memory, and load; emitter heartbeat; "
            "routine freshness; and emitter runtime."
        ),
        "charts": layout,
    }
    if group_id:
        body["groupId"] = group_id
    return body


def dashboard_group_definition() -> dict[str, Any]:
    return {
        "name": GROUP_NAME,
        "description": "Dashboards for a Grok Bot box emitting grokbot.* metrics.",
        "dashboards": [],
    }


def detector_definitions(notify_email: str = PLACEHOLDER_EMAIL) -> list[dict[str, Any]]:
    """Detector payloads. The email is a placeholder; replace it before applying live."""
    notifications = [{"type": "Email", "email": notify_email}]
    return [
        {
            "name": "Emitter silent",
            "description": (
                f"No {METRIC_OK} datapoints for {SILENT_LASTING}. "
                "Usually a stopped routine, an expired ingest token, or a network failure."
            ),
            "programText": (
                f"ok = data('{METRIC_OK}').publish('ok')\n"
                f"detect(when(ok is None, lasting='{SILENT_LASTING}')).publish('Emitter silent')\n"
            ),
            "notifications": notifications,
            "maxDelay": 0,
        },
        {
            "name": "Box disk high",
            "description": f"{METRIC_DISK} is above {DISK_THRESHOLD}% for {THRESHOLD_LASTING}.",
            "programText": (
                f"disk = data('{METRIC_DISK}').publish('disk')\n"
                f"detect(when(disk > {DISK_THRESHOLD}, lasting='{THRESHOLD_LASTING}')).publish('Box disk high')\n"
            ),
            "notifications": notifications,
            "maxDelay": 0,
        },
        {
            "name": "Box memory high",
            "description": f"{METRIC_MEM} is above {MEM_THRESHOLD}% for {THRESHOLD_LASTING}.",
            "programText": (
                f"mem = data('{METRIC_MEM}').publish('mem')\n"
                f"detect(when(mem > {MEM_THRESHOLD}, lasting='{THRESHOLD_LASTING}')).publish('Box memory high')\n"
            ),
            "notifications": notifications,
            "maxDelay": 0,
        },
        {
            "name": "Stale sync",
            "description": (
                f"{METRIC_AGE} is above {STALE_SECONDS} seconds (6 hours) for {THRESHOLD_LASTING}."
            ),
            "programText": (
                f"age = data('{METRIC_AGE}').publish('age')\n"
                f"detect(when(age > {STALE_SECONDS}, lasting='{THRESHOLD_LASTING}')).publish('Stale sync')\n"
            ),
            "notifications": notifications,
            "maxDelay": 0,
        },
    ]


def planned_requests(notify_email: str = PLACEHOLDER_EMAIL) -> list[dict[str, Any]]:
    """The sequence of API bodies --dry-run would send (create path, names only)."""
    charts = [chart_payload(defn) for defn in chart_definitions()]
    return [
        {"method": "PUT", "collection": "dashboardgroup", "body": dashboard_group_definition()},
        *[
            {"method": "PUT", "collection": "chart", "body": chart}
            for chart in charts
        ],
        {
            "method": "PUT",
            "collection": "dashboard",
            "body": dashboard_definition(group_id="<GROUP_ID>"),
        },
        *[
            {"method": "PUT", "collection": "detector", "body": det}
            for det in detector_definitions(notify_email=notify_email)
        ],
    ]


def _token() -> str:
    token = (os.environ.get("SPLUNK_O11Y_API_TOKEN") or "").strip()
    if not token or (token.startswith("<") and token.endswith(">")):
        raise ValueError("missing_api_token")
    return token


def api_request(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
    timeout: int = 30,
) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-SF-TOKEN": token,
            "Accept": "application/json",
        },
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Do not include response body verbatim; it could echo request context.
        raise RuntimeError(f"http_{exc.code}") from None


def list_results(base: str, token: str, collection: str, query: dict[str, str] | None = None) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(query or {})
    path = f"{base}/v2/{collection}"
    if params:
        path = f"{path}?{params}"
    payload = api_request("GET", path, token)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            return results
    return []


def find_by_name(base: str, token: str, collection: str, name: str) -> dict[str, Any] | None:
    # Prefer a name query when the API honors it; always filter locally too.
    results = list_results(base, token, collection, {"name": name, "limit": "200"})
    for item in results:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    if results:
        return None
    # Fallback: unfiltered first page, still filtered by exact name.
    for item in list_results(base, token, collection, {"limit": "200"}):
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


def upsert(
    base: str,
    token: str,
    collection: str,
    body: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    name = body["name"]
    if dry_run:
        return {"action": "would_create_or_update", "collection": collection, "name": name, "body": body}
    existing = find_by_name(base, token, collection, name)
    if existing and existing.get("id"):
        url = f"{base}/v2/{collection}/{existing['id']}"
        result = api_request("PUT", url, token, body)
        result.setdefault("id", existing["id"])
        result["_action"] = "updated"
        return result
    result = api_request("POST", f"{base}/v2/{collection}", token, body)
    result["_action"] = "created"
    return result


def apply(dry_run: bool, notify_email: str) -> dict[str, Any]:
    report: dict[str, Any] = {"dry_run": dry_run, "objects": []}
    if dry_run:
        report["objects"] = planned_requests(notify_email=notify_email)
        return report

    base = api_base()
    token = _token()

    group = upsert(base, token, "dashboardgroup", dashboard_group_definition(), dry_run=False)
    group_id = group.get("id")
    report["objects"].append({"collection": "dashboardgroup", "name": GROUP_NAME, "action": group.get("_action"), "id": group_id})

    chart_ids: list[str] = []
    for definition in chart_definitions():
        created = upsert(base, token, "chart", chart_payload(definition), dry_run=False)
        chart_ids.append(str(created.get("id", "")))
        report["objects"].append(
            {
                "collection": "chart",
                "name": definition["name"],
                "action": created.get("_action"),
                "id": created.get("id"),
            }
        )

    dash = upsert(
        base,
        token,
        "dashboard",
        dashboard_definition(group_id=group_id, chart_ids=chart_ids),
        dry_run=False,
    )
    report["objects"].append(
        {"collection": "dashboard", "name": DASHBOARD_NAME, "action": dash.get("_action"), "id": dash.get("id")}
    )

    for det in detector_definitions(notify_email=notify_email):
        created = upsert(base, token, "detector", det, dry_run=False)
        report["objects"].append(
            {
                "collection": "detector",
                "name": det["name"],
                "action": created.get("_action"),
                "id": created.get("id"),
            }
        )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Idempotently create or update the Bot Health dashboard and detectors."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the JSON that would be sent; do not call the API.",
    )
    parser.add_argument(
        "--notify-email",
        default=PLACEHOLDER_EMAIL,
        help=f"Email notification target (default placeholder: {PLACEHOLDER_EMAIL}). Replace before a live apply.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = apply(dry_run=args.dry_run, notify_email=args.notify_email)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
