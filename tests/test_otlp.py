#!/usr/bin/env python3
"""Unit tests for optional OTLP helpers. No network, no SDK required."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import otlp  # noqa: E402
import emit  # noqa: E402


class OtlpUrlTests(unittest.TestCase):
    def test_metrics_url_uses_realm_and_otlp_path(self) -> None:
        self.assertEqual(
            otlp.otlp_metrics_url("us1"),
            "https://ingest.us1.signalfx.com/v2/datapoint/otlp",
        )

    def test_metrics_url_rejects_missing_or_placeholder_realm(self) -> None:
        with self.assertRaises(ValueError):
            otlp.otlp_metrics_url("")
        with self.assertRaises(ValueError):
            otlp.otlp_metrics_url("<REALM>")

    def test_override_env_wins(self) -> None:
        with mock.patch.dict(os.environ, {"SPLUNK_O11Y_OTLP_URL": "http://127.0.0.1:4318/v1/metrics"}):
            self.assertEqual(otlp.otlp_metrics_url("us1"), "http://127.0.0.1:4318/v1/metrics")

    def test_auth_header_name_is_x_sf_token(self) -> None:
        headers = otlp.auth_headers("dummy-token")
        self.assertEqual(set(headers), {otlp.HEADER_TOKEN})
        self.assertEqual(otlp.HEADER_TOKEN, "X-SF-TOKEN")
        # The function accepts a token; tests must not print it.


class MappingTests(unittest.TestCase):
    def test_points_to_series_keeps_metric_dims_and_value(self) -> None:
        points = [
            emit.gauge("grokbot.box.disk.pct", 42.5, timestamp_ms=1_700_000_000_000, host="example-box"),
            emit.gauge("grokbot.emitter.ok", 1, timestamp_ms=1_700_000_000_000, host="example-box"),
        ]
        series = otlp.points_to_series(points)
        self.assertEqual(len(series), 2)
        by_name = {s["name"]: s for s in series}
        self.assertEqual(by_name["grokbot.box.disk.pct"]["value"], 42.5)
        self.assertEqual(by_name["grokbot.box.disk.pct"]["attributes"]["host"], "example-box")

    def test_resource_attributes_include_service_and_host(self) -> None:
        attrs = otlp.resource_attributes("example-box")
        self.assertEqual(attrs["service.name"], "grokbot-emitter")
        self.assertEqual(attrs["host.name"], "example-box")


class ProtocolFlagTests(unittest.TestCase):
    def test_default_protocol_is_otlp(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GROKBOT_O11Y_PROTOCOL", None)
            args = emit.parse_args([])
            self.assertEqual(emit.selected_protocol(args), "otlp")

    def test_flag_and_env_select_otlp(self) -> None:
        args = emit.parse_args(["--protocol", "signalfx"])
        self.assertEqual(emit.selected_protocol(args), "signalfx")
        with mock.patch.dict(os.environ, {"GROKBOT_O11Y_PROTOCOL": "otlp"}):
            args = emit.parse_args([])
            self.assertEqual(emit.selected_protocol(args), "otlp")

    def test_export_without_sdk_returns_clear_error(self) -> None:
        with mock.patch.object(otlp, "sdk_available", return_value=False):
            status, err = otlp.export_gauges(
                [{"metric": "grokbot.emitter.ok", "value": 1, "timestamp": 1, "dimensions": {"host": "example-box"}}],
                "dummy-token",
                realm="us1",
            )
        self.assertIsNone(status)
        self.assertEqual(err, "missing_otel_sdk")


if __name__ == "__main__":
    unittest.main()
