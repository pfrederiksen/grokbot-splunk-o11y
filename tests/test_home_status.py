#!/usr/bin/env python3
"""Unit tests for Home Assistant status-age handling. No network."""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import emit  # noqa: E402


class HomeStatusTests(unittest.TestCase):
    def _write(self, payload: dict, age_seconds: float) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "status.json"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        mtime = time.time() - age_seconds
        os_utime = __import__("os").utime
        os_utime(tmp, (mtime, mtime))
        return tmp

    def test_missing_file_emits_nothing(self) -> None:
        missing = Path(tempfile.mkdtemp()) / "status.json"
        self.assertEqual(emit.collect_home_status(path=missing, timestamp_ms=1), [])

    def test_fresh_down_is_reported(self) -> None:
        path = self._write({"up": 0}, age_seconds=5 * 60)
        points = emit.collect_home_status(path=path, timestamp_ms=1)
        by_name = {p["metric"]: p["value"] for p in points}
        self.assertIn("grokbot.home.status.age_minutes", by_name)
        self.assertLess(by_name["grokbot.home.status.age_minutes"], 10)
        self.assertEqual(by_name["grokbot.home.ha.up"], 0.0)

    def test_stale_down_is_omitted(self) -> None:
        path = self._write({"up": 0}, age_seconds=45 * 60)
        points = emit.collect_home_status(path=path, timestamp_ms=1)
        metrics = {p["metric"]: p["value"] for p in points}
        self.assertGreater(metrics["grokbot.home.status.age_minutes"], 30)
        self.assertNotIn("grokbot.home.ha.up", metrics)

    def test_stale_up_is_still_reported(self) -> None:
        path = self._write({"up": 1}, age_seconds=45 * 60)
        points = emit.collect_home_status(path=path, timestamp_ms=1)
        metrics = {p["metric"]: p["value"] for p in points}
        self.assertEqual(metrics["grokbot.home.ha.up"], 1.0)
        self.assertGreater(metrics["grokbot.home.status.age_minutes"], 30)


if __name__ == "__main__":
    unittest.main()
