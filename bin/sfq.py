#!/usr/bin/env python3
"""Tiny SignalFlow query helper that keeps per-MTS dimensions.

Reads the API token and realm from the environment only. Never prints tokens.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def api_token() -> str:
    token = (os.environ.get("SPLUNK_O11Y_API_TOKEN") or "").strip()
    if not token or (token.startswith("<") and token.endswith(">")):
        raise ValueError("missing_api_token")
    return token


def stream_url(realm: str | None = None) -> str:
    override = os.environ.get("SPLUNK_O11Y_STREAM_URL")
    if override:
        return override.rstrip("/")
    realm = realm if realm is not None else os.environ.get("SPLUNK_O11Y_REALM", "")
    realm = (realm or "").strip()
    if not realm or (realm.startswith("<") and realm.endswith(">")):
        raise ValueError("missing_realm")
    return f"https://stream.{realm}.signalfx.com/v2/signalflow/execute"


def query(program: str, start_ms: int, stop_ms: int, resolution_ms: int = 300000, timeout: int = 40):
    """Run one SignalFlow program and return (series, err).

    Each series is ``{"dims": {...}, "points": [(timestamp_ms, value), ...]}``.
    """
    token = api_token()
    url = stream_url()
    params = urllib.parse.urlencode(
        {
            "start": start_ms,
            "stop": stop_ms,
            "resolution": resolution_ms,
            "maxDelay": 0,
            "immediate": "true",
        }
    )
    request = urllib.request.Request(
        f"{url}?{params}",
        data=program.encode(),
        method="POST",
        headers={
            "X-SF-TOKEN": token,
            "Content-Type": "text/plain",
            "Accept": "text/event-stream",
        },
    )
    meta, pts, err = {}, {}, ""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            event, buf, deadline = "message", [], time.time() + timeout
            while time.time() < deadline:
                line = resp.readline()
                if not line:
                    break
                text = line.decode("utf-8", "replace").rstrip("\r\n")
                if text.startswith("event:"):
                    event = text[6:].strip()
                    continue
                if text.startswith("data:"):
                    buf.append(text[5:].lstrip())
                    continue
                if text == "" and buf:
                    payload = "\n".join(buf)
                    buf = []
                    try:
                        body = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if event == "metadata":
                        meta[body["tsId"]] = body.get("properties", {})
                    elif event == "data":
                        stamp = body.get("logicalTimestampMs")
                        for item in body.get("data", []):
                            pts.setdefault(item["tsId"], []).append((stamp, item["value"]))
                    elif event == "control-message" and body.get("event") == "END_OF_CHANNEL":
                        break
                    elif event == "error":
                        err = str(body)[:200]
                        break
                    event = "message"
    except urllib.error.HTTPError as exc:
        err = f"http_{exc.code}"
    except Exception:
        typ = sys.exc_info()[0]
        err = typ.__name__ if typ else "query_error"
    out = []
    for tsid, points in pts.items():
        props = meta.get(tsid, {})
        dims = {
            k: v
            for k, v in props.items()
            if not k.startswith("sf_") or k in ("sf_metric", "sf_streamLabel")
        }
        out.append({"dims": dims, "points": points})
    return out, err
