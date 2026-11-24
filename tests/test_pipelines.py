#!/usr/bin/env python3
"""Unit tests for pipeline budget calculation and NYSE session handling. No network."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import emit  # noqa: E402

PT = ZoneInfo("America/Los_Angeles")


def pt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=PT)


class BudgetTests(unittest.TestCase):
    def test_fixed_budget_when_no_slots(self) -> None:
        now = pt(2026, 11, 24, 12, 0)
        self.assertEqual(emit.pipeline_budget_hours(now, None, 9.0), 9.0)
        self.assertEqual(emit.pipeline_budget_hours(now, None, 8 * 24.0), 192.0)

    def test_daily_slots_include_allowance(self) -> None:
        # Sample email schedule: every 2 hours at :04 from 6:04 through 22:04, 1.5h allowance.
        slots = emit.daily_slots([(hour, 4) for hour in range(6, 23, 2)])
        now = pt(2026, 11, 24, 10, 4)
        # now - 1.5h = 08:34, so the latest finished slot is 08:04.
        # budget = (10:04 - 08:04) + 1.5h = 3.5h
        budget = emit.pipeline_budget_hours(now, slots, 1.5)
        self.assertAlmostEqual(budget, 3.5, places=5)

    def test_ratio_is_overdue_when_age_exceeds_budget(self) -> None:
        now = pt(2026, 11, 24, 12, 0)
        last = pt(2026, 11, 24, 6, 0)
        age_h = emit.age_seconds(last, now=now) / 3600.0
        budget = emit.pipeline_budget_hours(now, None, 5.0)
        self.assertAlmostEqual(age_h, 6.0, places=5)
        self.assertEqual(budget, 5.0)
        self.assertGreaterEqual(age_h / budget, 1.0)

    def test_collect_pipelines_skips_missing_sources(self) -> None:
        now = pt(2026, 11, 24, 12, 0)
        points = emit.collect_pipelines(
            now=now,
            timestamp_ms=1,
            specs={"golf": (lambda: None, None, 192.0)},
        )
        metrics = {p["metric"]: p["value"] for p in points}
        self.assertEqual(metrics["grokbot.pipeline.overdue_count"], 0.0)
        self.assertEqual(metrics["grokbot.pipeline.warn_count"], 0.0)
        self.assertNotIn("grokbot.pipeline.age_hours", metrics)

    def test_collect_pipelines_counts_warn_and_overdue(self) -> None:
        now = pt(2026, 11, 24, 12, 0)

        def stale():
            return pt(2026, 11, 24, 6, 0)  # 6h old vs 5h fixed budget → overdue

        def watch():
            return pt(2026, 11, 24, 8, 0)  # 4h old vs 5h fixed budget → 0.8 warn

        def fresh():
            return pt(2026, 11, 24, 11, 0)  # 1h old vs 5h → fine

        points = emit.collect_pipelines(
            now=now,
            timestamp_ms=1,
            specs={
                "backup": (stale, None, 5.0),
                "ebay": (watch, None, 5.0),
                "golf": (fresh, None, 5.0),
            },
        )
        counts = {p["metric"]: p["value"] for p in points if "pipeline" not in p["dimensions"]}
        self.assertEqual(counts["grokbot.pipeline.overdue_count"], 1.0)
        self.assertEqual(counts["grokbot.pipeline.warn_count"], 1.0)
        self.assertEqual(counts["grokbot.routine.failing_count"], 1.0)
        by_pipe = {}
        for point in points:
            pipe = point["dimensions"].get("pipeline")
            if pipe:
                by_pipe.setdefault(pipe, {})[point["metric"]] = point["value"]
        self.assertGreaterEqual(by_pipe["backup"]["grokbot.pipeline.age_ratio"], 1.0)
        self.assertGreaterEqual(by_pipe["ebay"]["grokbot.pipeline.age_ratio"], 0.75)
        self.assertLess(by_pipe["ebay"]["grokbot.pipeline.age_ratio"], 1.0)
        self.assertLess(by_pipe["golf"]["grokbot.pipeline.age_ratio"], 0.75)


class NyseCalendarTests(unittest.TestCase):
    def test_weekend_has_no_rth_slots(self) -> None:
        saturday = pt(2026, 11, 28, 10, 0)
        sunday = pt(2026, 11, 29, 10, 0)
        self.assertEqual(emit.rth_slots(saturday), [])
        self.assertEqual(emit.rth_slots(sunday), [])

    def test_thanksgiving_2026_is_closed(self) -> None:
        day = pt(2026, 11, 26, 9, 0)
        self.assertIn(day.date().isoformat(), emit.MARKET_CLOSED)
        self.assertEqual(emit.rth_slots(day), [])

    def test_early_close_ends_at_10_pt(self) -> None:
        # Friday after Thanksgiving 2026 is an early close.
        day = pt(2026, 11, 27, 0, 0)
        self.assertIn(day.date().isoformat(), emit.MARKET_EARLY)
        slots = emit.rth_slots(day)
        self.assertTrue(slots)
        self.assertEqual(slots[0], (6, 30))
        self.assertEqual(slots[-1], (9, 45))
        self.assertNotIn((10, 0), slots)
        self.assertNotIn((10, 15), slots)

    def test_regular_session_ends_at_13_pt(self) -> None:
        day = pt(2026, 11, 24, 0, 0)  # Tuesday
        slots = emit.rth_slots(day)
        self.assertEqual(slots[0], (6, 30))
        self.assertEqual(slots[-1], (12, 45))
        self.assertNotIn((13, 0), slots)
        self.assertIn((12, 30), slots)

    def test_trader_budget_looks_back_across_a_holiday(self) -> None:
        # Monday 30 Nov 2026 07:00 PT: Thursday 26th is closed, Friday 27th is an early close.
        # Allowance is 1h, so latest_slot is asked for 06:00 Monday — no Monday slots yet,
        # so the lookback should land on Friday's last 09:45 PT slot.
        now = pt(2026, 11, 30, 7, 0)
        budget = emit.pipeline_budget_hours(now, emit.rth_slots, 1.0)
        last = emit.latest_slot(now - __import__("datetime").timedelta(hours=1), emit.rth_slots)
        self.assertIsNotNone(last)
        assert last is not None
        self.assertEqual(last, pt(2026, 11, 27, 9, 45))
        expected = (now - last).total_seconds() / 3600.0 + 1.0
        self.assertAlmostEqual(budget, expected, places=5)


if __name__ == "__main__":
    unittest.main()
