#!/usr/bin/env python3
"""Optional OTLP/HTTP helpers for the Grok Bot emitter.

The default ingest path is still the SignalFx /v2/datapoint JSON API
(stdlib, no extra packages). This module is used only when the emitter is
run with --protocol otlp (or GROKBOT_O11Y_PROTOCOL=otlp).

Live export needs the optional OpenTelemetry SDK:

    pip install -r requirements-otel.txt

URL and mapping helpers here are stdlib and are covered by tests without
the SDK and without a network. Never print or log token values.
"""
from __future__ import annotations

import os
from typing import Any

OTLP_METRICS_PATH = "/v2/datapoint/otlp"
HEADER_TOKEN = "X-SF-TOKEN"
SERVICE_NAME = "grokbot-emitter"


def otlp_metrics_url(realm: str | None = None) -> str:
    """Splunk Observability Cloud OTLP/HTTP metrics endpoint for a realm."""
    override = os.environ.get("SPLUNK_O11Y_OTLP_URL")
    if override:
        return override.rstrip("/")
    realm = realm if realm is not None else os.environ.get("SPLUNK_O11Y_REALM", "")
    realm = (realm or "").strip()
    if not realm or (realm.startswith("<") and realm.endswith(">")):
        raise ValueError("missing_realm")
    return f"https://ingest.{realm}.signalfx.com{OTLP_METRICS_PATH}"


def collector_otlp_url() -> str:
    """Local collector default (OTLP/HTTP). Used when SPLUNK_O11Y_OTLP_URL points at it."""
    return os.environ.get("SPLUNK_O11Y_OTLP_URL") or "http://127.0.0.1:4318/v1/metrics"


def auth_headers(token: str) -> dict[str, str]:
    """Headers for Splunk's OTLP ingest. Caller must not print the result."""
    return {HEADER_TOKEN: token}


def sdk_available() -> bool:
    try:
        import opentelemetry.exporter.otlp.proto.http.metric_exporter  # noqa: F401
        import opentelemetry.sdk.metrics  # noqa: F401
        return True
    except ImportError:
        return False


def points_to_series(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize emitter gauge dicts into {name, value, timestamp_ms, attributes}."""
    series = []
    for point in points:
        if not point:
            continue
        name = point.get("metric")
        value = point.get("value")
        if name is None or value is None:
            continue
        dims = dict(point.get("dimensions") or {})
        series.append(
            {
                "name": str(name),
                "value": float(value),
                "timestamp_ms": int(point.get("timestamp") or 0),
                "attributes": {str(k): str(v) for k, v in dims.items()},
            }
        )
    return series


def resource_attributes(host: str | None = None) -> dict[str, str]:
    attrs = {"service.name": SERVICE_NAME}
    host = host or os.environ.get("GROKBOT_HOST") or "example-box"
    attrs["host.name"] = host
    return attrs


def export_gauges(points: list[dict[str, Any]], token: str, realm: str | None = None, timeout: int = 15) -> tuple[int | None, str]:
    """One-shot OTLP/HTTP export of gauge points. Returns (status, err).

    status is 200 on a successful SDK flush, or None on a local error.
    Never includes the token in the error string.
    """
    if not points:
        return None, "no_points"
    if not sdk_available():
        return None, "missing_otel_sdk"
    try:
        url = otlp_metrics_url(realm)
    except ValueError as exc:
        return None, str(exc) or "missing_realm"

    # Imports stay inside the function so stdlib tests can import this module
    # without the optional SDK installed.
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.metrics import Observation
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource

    series = points_to_series(points)
    host = None
    if series and series[0]["attributes"].get("host"):
        host = series[0]["attributes"]["host"]

    # Splunk's OTLP metrics ingest expects the token in X-SF-TOKEN, not the
    # generic Authorization header the exporter uses by default.
    exporter = OTLPMetricExporter(
        endpoint=url,
        headers=auth_headers(token),
        timeout=timeout,
    )
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60_000)
    provider = MeterProvider(
        resource=Resource.create(resource_attributes(host)),
        metric_readers=[reader],
    )
    meter = provider.get_meter(SERVICE_NAME)

    # Snapshot for the observable callbacks (one reading each).
    snapshot = {(s["name"], tuple(sorted(s["attributes"].items()))): s for s in series}

    def make_callback(metric_name: str):
        def _cb(options):
            for (name, attr_items), item in snapshot.items():
                if name == metric_name:
                    yield Observation(item["value"], dict(attr_items))
        return _cb

    for name in sorted({s["name"] for s in series}):
        meter.create_observable_gauge(name, callbacks=[make_callback(name)])

    try:
        ok = provider.force_flush(timeout_millis=timeout * 1000)
        provider.shutdown(timeout_millis=timeout * 1000)
    except Exception:
        import sys
        typ = sys.exc_info()[0]
        return None, typ.__name__ if typ else "otlp_error"
    if not ok:
        return None, "otlp_flush_failed"
    return 200, "ok"
