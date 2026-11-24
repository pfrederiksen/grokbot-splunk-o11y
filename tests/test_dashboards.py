#!/usr/bin/env python3
"""Unit tests for dashboard and detector definitions. No network."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import apply_dashboards as dash  # noqa: E402


class ChartAndDashboardTests(unittest.TestCase):
    def test_bot_health_charts_cover_core_metrics(self) -> None:
        programs = "\n".join(c["programText"] for c in dash.chart_definitions())
        for metric in (
            "grokbot.box.disk.pct",
            "grokbot.box.mem.pct",
            "grokbot.box.load.1",
            "grokbot.emitter.ok",
            "grokbot.routine.age_seconds",
            "grokbot.emitter.duration_ms",
        ):
            self.assertIn(metric, programs)
        names = [c["name"] for c in dash.chart_definitions()]
        self.assertEqual(len(names), len(set(names)), "chart names must be unique")

    def test_dashboard_name_is_stable_and_layout_is_valid(self) -> None:
        body = dash.dashboard_definition(group_id="group-placeholder", chart_ids=["a", "b", "c", "d", "e", "f"])
        self.assertEqual(body["name"], "Bot Health")
        self.assertEqual(body["groupId"], "group-placeholder")
        self.assertEqual(len(body["charts"]), 6)
        for entry in body["charts"]:
            self.assertIn(entry["chartId"], list("abcdef"))
            self.assertGreaterEqual(entry["width"], 1)
            self.assertGreaterEqual(entry["height"], 1)
            self.assertGreaterEqual(entry["row"], 0)
            self.assertGreaterEqual(entry["column"], 0)

    def test_group_name_is_stable(self) -> None:
        self.assertEqual(dash.dashboard_group_definition()["name"], "Grok Bot")


class DetectorTests(unittest.TestCase):
    def _by_name(self) -> dict:
        return {d["name"]: d for d in dash.detector_definitions()}

    def test_expected_detector_names(self) -> None:
        self.assertEqual(
            set(self._by_name()),
            {"Emitter silent", "Box disk high", "Box memory high", "Stale sync"},
        )

    def test_emitter_silent_uses_ok_metric_and_2h15m(self) -> None:
        program = self._by_name()["Emitter silent"]["programText"]
        self.assertIn("grokbot.emitter.ok", program)
        self.assertIn("lasting='2h15m'", program)
        self.assertIn("is None", program)

    def test_disk_high_threshold(self) -> None:
        program = self._by_name()["Box disk high"]["programText"]
        self.assertIn("grokbot.box.disk.pct", program)
        self.assertIn("> 85", program)
        self.assertIn("lasting='1h15m'", program)

    def test_memory_high_threshold(self) -> None:
        program = self._by_name()["Box memory high"]["programText"]
        self.assertIn("grokbot.box.mem.pct", program)
        self.assertIn("> 90", program)
        self.assertIn("lasting='1h15m'", program)

    def test_stale_sync_threshold(self) -> None:
        program = self._by_name()["Stale sync"]["programText"]
        self.assertIn("grokbot.routine.age_seconds", program)
        self.assertIn("> 21600", program)
        self.assertIn("lasting='1h15m'", program)

    def test_notification_placeholder_is_example_com_only(self) -> None:
        for det in dash.detector_definitions():
            emails = [n.get("email") for n in det["notifications"]]
            self.assertEqual(emails, ["alerts@example.com"])
            for email in emails:
                self.assertTrue(str(email).endswith("@example.com"))


class DryRunTests(unittest.TestCase):
    def test_planned_requests_are_json_serializable_dicts(self) -> None:
        planned = dash.planned_requests()
        self.assertGreaterEqual(len(planned), 6)
        encoded = json.dumps(planned)
        decoded = json.loads(encoded)
        self.assertIsInstance(decoded, list)
        collections = {item["collection"] for item in decoded}
        self.assertEqual(collections, {"dashboardgroup", "chart", "dashboard", "detector"})
        detector_names = [item["body"]["name"] for item in decoded if item["collection"] == "detector"]
        self.assertEqual(
            detector_names,
            ["Emitter silent", "Box disk high", "Box memory high", "Stale sync"],
        )

    def test_dry_run_apply_does_not_need_credentials(self) -> None:
        report = dash.apply(dry_run=True, notify_email="alerts@example.com")
        self.assertTrue(report["dry_run"])
        self.assertTrue(report["objects"])


if __name__ == "__main__":
    unittest.main()
