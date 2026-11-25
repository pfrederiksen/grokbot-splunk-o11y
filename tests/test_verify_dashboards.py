#!/usr/bin/env python3
"""Unit tests for dashboard verification helpers. No network."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import verify_dashboards as v  # noqa: E402


class UrlAndConfigTests(unittest.TestCase):
    def test_metrics_helpers_reject_missing_or_placeholder_realm(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPLUNK_O11Y_REALM", None)
            os.environ.pop("SPLUNK_O11Y_API_URL", None)
            os.environ.pop("SPLUNK_O11Y_APP_URL", None)
            with self.assertRaises(ValueError):
                v.api_base()
            self.assertEqual(
                v.app_dashboard_url("<DASHBOARD_ID_HOME>"),
                "https://app.<REALM>.signalfx.com/#/dashboard/<DASHBOARD_ID_HOME>",
            )
        with mock.patch.dict(os.environ, {"SPLUNK_O11Y_REALM": "<REALM>"}, clear=False):
            os.environ.pop("SPLUNK_O11Y_API_URL", None)
            with self.assertRaises(ValueError):
                v.api_base()
        with mock.patch.dict(os.environ, {"SPLUNK_O11Y_REALM": "eu0"}, clear=False):
            os.environ.pop("SPLUNK_O11Y_API_URL", None)
            os.environ.pop("SPLUNK_O11Y_APP_URL", None)
            self.assertEqual(v.api_base(), "https://api.eu0.signalfx.com")
            self.assertEqual(
                v.app_dashboard_url("abc", realm="eu0"),
                "https://app.eu0.signalfx.com/#/dashboard/abc",
            )


class WindowAndSanityTests(unittest.TestCase):
    def test_golf_charts_use_seven_day_window(self) -> None:
        start, stop, res, label = v.window_for("Handicap index", "data('grokbot.golf.handicap_index')")
        self.assertEqual(label, "7d")
        self.assertEqual(res, 3600000)
        self.assertEqual(stop - start, 7 * 86400 * 1000)

    def test_default_window_is_24h(self) -> None:
        start, stop, res, label = v.window_for("HA status age", "data('grokbot.home.status.age_minutes')")
        self.assertEqual(label, "24h")
        self.assertEqual(res, 900000)
        self.assertEqual(stop - start, 24 * 3600 * 1000)

    def test_age_minutes_bounds_and_budget_percent(self) -> None:
        self.assertIsNone(v.sanity("grokbot.home.status.age_minutes", 12.5))
        self.assertIsNotNone(v.sanity("grokbot.home.status.age_minutes", -1))
        self.assertIsNone(v.sanity("grokbot.pipeline.age_ratio*100", 150))
        self.assertIsNotNone(v.sanity("grokbot.pipeline.age_ratio*100", 9000))

    def test_metric_for_series_maps_budget_percent(self) -> None:
        metric = v.metric_for_series(
            "% used",
            ["grokbot.pipeline.age_ratio"],
            "(data('grokbot.pipeline.age_ratio') * 100).publish('% used')",
        )
        self.assertEqual(metric, "grokbot.pipeline.age_ratio*100")

    def test_check_text_links_ignores_known_placeholders(self) -> None:
        md = "See [Home](https://app.<REALM>.signalfx.com/#/dashboard/<DASHBOARD_ID_HOME>)"
        self.assertEqual(v.check_text_links(md, {"<DASHBOARD_ID_HOME>"}), [])
        issues = v.check_text_links(md, set())
        self.assertTrue(any("unknown dashboard id" in i for i in issues))


class DetectorClassificationTests(unittest.TestCase):
    def test_sample_detector_names_are_ours(self) -> None:
        self.assertTrue(v.is_our_detector("HA down"))
        self.assertTrue(v.is_our_detector("Pipeline overdue"))
        self.assertTrue(v.is_our_detector("Emitter collector failing"))
        self.assertFalse(v.is_our_detector("Splunk operational Autodetect"))


if __name__ == "__main__":
    unittest.main()
