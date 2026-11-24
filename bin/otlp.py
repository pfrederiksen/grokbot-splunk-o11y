#!/usr/bin/env python3
"""Optional OTLP/HTTP helpers for the Grok Bot emitter.

The default ingest path is still the SignalFx /v2/datapoint JSON API
(stdlib, no extra packages). This module is used only when the emitter is
run with --protocol otlp (or GROKBOT_O11Y_PROTOCOL=otlp).

Live export needs the optional OpenTelemetry SDK. Metrics keep an empty
resource so MTS identities stay on the original dimensions (typically
``host``). Traces use service.name=grokbot-emitter so they show up in APM.


    pip install -r requirements-otel.txt

URL and mapping helpers here are stdlib and are covered by tests without
the SDK and without a network. Never print or log token values.
"""
from __future__ import annotations

import os
from typing import Any

OTLP_METRICS_PATH = "/v2/datapoint/otlp"
OTLP_TRACES_PATH = "/v2/trace/otlp"
HEADER_TOKEN = "X-SF-TOKEN"
SERVICE_NAME = "grokbot-emitter"

_tracer = None
_tracer_provider = None


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


def otlp_traces_url(realm: str | None = None) -> str:
    """Splunk Observability Cloud OTLP/HTTP traces endpoint for a realm."""
    override = os.environ.get("SPLUNK_O11Y_OTLP_TRACES_URL")
    if override:
        return override.rstrip("/")
    realm = realm if realm is not None else os.environ.get("SPLUNK_O11Y_REALM", "")
    realm = (realm or "").strip()
    if not realm or (realm.startswith("<") and realm.endswith(">")):
        raise ValueError("missing_realm")
    return f"https://ingest.{realm}.signalfx.com{OTLP_TRACES_PATH}"


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

    # Splunk's OTLP metrics ingest expects the token in X-SF-TOKEN, not the
    # generic Authorization header the exporter uses by default.
    # An empty resource keeps service.name / host.name off the metric MTS.
    exporter = OTLPMetricExporter(
        endpoint=url,
        headers=auth_headers(token),
        timeout=timeout,
    )
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60_000)
    provider = MeterProvider(
        resource=Resource.create({}),
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


def _ingest_token() -> str:
    token = (os.environ.get("SPLUNK_O11Y_INGEST_TOKEN") or "").strip()
    if not token or (token.startswith("<") and token.endswith(">")):
        raise ValueError("missing_ingest_token")
    return token


def start_tracer():
    """Install a tracer provider that exports one batch of traces via OTLP/HTTP.

    Traces use service.name=grokbot-emitter (required for APM). That resource
    is not applied to metrics, so it does not split custom MTS. Host and
    deployment environment come from GROKBOT_HOST / GROKBOT_ENVIRONMENT
    when set. Returns None if the SDK or credentials are unavailable.
    """
    global _tracer, _tracer_provider
    if _tracer is not None:
        return _tracer
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.semconv.resource import ResourceAttributes
    except ImportError:
        return None
    try:
        token = _ingest_token()
        url = otlp_traces_url()
    except ValueError:
        return None
    attributes = {ResourceAttributes.SERVICE_NAME: SERVICE_NAME}
    host = os.environ.get("GROKBOT_HOST")
    if host:
        attributes["host"] = host
    environment = os.environ.get("GROKBOT_ENVIRONMENT")
    if environment:
        attributes["deployment.environment"] = environment
    try:
        provider = TracerProvider(resource=Resource(attributes=attributes))
        exporter = OTLPSpanExporter(
            endpoint=url,
            headers=auth_headers(token),
            timeout=30,
        )
        provider.add_span_processor(
            BatchSpanProcessor(exporter, max_export_batch_size=32, schedule_delay_millis=500)
        )
        trace.set_tracer_provider(provider)
        _tracer_provider = provider
        _tracer = trace.get_tracer(SERVICE_NAME)
        return _tracer
    except Exception:
        _tracer = None
        _tracer_provider = None
        return None


def get_tracer():
    return _tracer


def flush_traces(timeout_ms: int = 15000) -> tuple[bool, str]:
    """Force-flush traces. Returns (ok, err). Errors are type names only."""
    provider = _tracer_provider
    if provider is None:
        return False, "no_tracer"
    try:
        ok = provider.force_flush(timeout_ms)
        provider.shutdown()
        return (True, "ok") if ok else (False, "trace_flush_failed")
    except Exception:
        typ = __import__("sys").exc_info()[0]
        return False, typ.__name__ if typ else "trace_error"
