#!/usr/bin/env python3
"""Unit tests for datapoint payload helpers. No network."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import emit  # noqa: E402


class GaugeTests(unittest.TestCase):
    def test_numeric_gauge(self) -> None:
        point = emit.gauge("grokbot.box.disk.pct", 42.5, timestamp_ms=1_700_000_000_000, host="example-box")
        self.assertIsNotNone(point)
        assert point is not None
        self.assertEqual(point["metric"], "grokbot.box.disk.pct")
        self.assertEqual(point["value"], 42.5)
        self.assertEqual(point["timestamp"], 1_700_000_000_000)
        self.assertEqual(point["dimensions"], {"host": "example-box"})

    def test_bool_becomes_one_or_zero(self) -> None:
        self.assertEqual(emit.gauge("grokbot.emitter.ok", True, timestamp_ms=1, host="example-box")["value"], 1.0)
        self.assertEqual(emit.gauge("grokbot.emitter.ok", False, timestamp_ms=1, host="example-box")["value"], 0.0)

    def test_skips_none_nan_and_inf(self) -> None:
        self.assertIsNone(emit.gauge("grokbot.box.mem.pct", None, timestamp_ms=1))
        self.assertIsNone(emit.gauge("grokbot.box.mem.pct", float("nan"), timestamp_ms=1))
        self.assertIsNone(emit.gauge("grokbot.box.mem.pct", float("inf"), timestamp_ms=1))
        self.assertIsNone(emit.gauge("grokbot.box.mem.pct", "not-a-number", timestamp_ms=1))

    def test_merges_extra_dimensions_without_dropping_host(self) -> None:
        point = emit.gauge(
            "grokbot.box.load.1",
            0.5,
            dims={"role": "bot"},
            timestamp_ms=1,
            host="example-box",
        )
        self.assertEqual(point["dimensions"], {"host": "example-box", "role": "bot"})


class PayloadTests(unittest.TestCase):
    def test_batch_body_shape(self) -> None:
        points = [
            emit.gauge("grokbot.box.disk.pct", 10, timestamp_ms=1, host="example-box"),
            emit.gauge("grokbot.box.mem.pct", 20, timestamp_ms=1, host="example-box"),
        ]
        payload = emit.build_payload(points)
        self.assertEqual(set(payload.keys()), {"gauge"})
        self.assertEqual(len(payload["gauge"]), 2)
        self.assertTrue(all("metric" in p and "value" in p and "dimensions" in p for p in payload["gauge"]))

    def test_mts_counts_unique_metric_and_dims(self) -> None:
        points = [
            emit.gauge("grokbot.box.disk.pct", 10, timestamp_ms=1, host="example-box"),
            emit.gauge("grokbot.box.disk.pct", 11, timestamp_ms=2, host="example-box"),
            emit.gauge("grokbot.box.mem.pct", 20, timestamp_ms=1, host="example-box"),
        ]
        # Same metric+dims counted once, even with two timestamps/values.
        self.assertEqual(emit.count_mts(points), 2)

    def test_add_points_skips_nones(self) -> None:
        out: list = []
        emit.add_points(out, None, emit.gauge("grokbot.emitter.ok", 1, timestamp_ms=1, host="example-box"), [None])
        self.assertEqual(len(out), 1)

    def test_ingest_url_requires_realm_and_uses_signalfx_host(self) -> None:
        self.assertEqual(
            emit.ingest_url("us0"),
            "https://ingest.us0.signalfx.com/v2/datapoint",
        )
        with self.assertRaises(ValueError):
            emit.ingest_url("")
        with self.assertRaises(ValueError):
            emit.ingest_url("<REALM>")

    def test_freshness_from_prior_success(self) -> None:
        state = {"last_success_epoch": 1_000}
        self.assertEqual(emit.routine_age_seconds(state, now_epoch=1_400), 400.0)
        self.assertIsNone(emit.routine_age_seconds(emit.empty_state(), now_epoch=1_400))

    def test_collect_disk_returns_percentage(self) -> None:
        points = emit.collect_disk("/", timestamp_ms=1)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["metric"], "grokbot.box.disk.pct")
        self.assertGreaterEqual(points[0]["value"], 0.0)
        self.assertLessEqual(points[0]["value"], 100.0)


if __name__ == "__main__":
    unittest.main()
