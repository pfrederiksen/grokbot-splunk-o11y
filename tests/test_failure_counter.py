#!/usr/bin/env python3
"""Unit tests for the consecutive-failure counter. No network, no filesystem."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import emit  # noqa: E402


class FailureCounterTests(unittest.TestCase):
    def test_zero_failures_does_not_alert(self) -> None:
        state = emit.empty_state()
        self.assertFalse(emit.should_alert(state))
        self.assertEqual(state["consecutive_failures"], 0)

    def test_one_failure_does_not_alert(self) -> None:
        state = emit.record_result(emit.empty_state(), False, "http_500", now_epoch=10)
        self.assertEqual(state["consecutive_failures"], 1)
        self.assertEqual(state["last_error"], "http_500")
        self.assertEqual(state["last_run_epoch"], 10)
        self.assertIsNone(state["last_success_epoch"])
        self.assertFalse(emit.should_alert(state, threshold=2))

    def test_two_consecutive_failures_alert(self) -> None:
        state = emit.empty_state()
        state = emit.record_result(state, False, "url_error", now_epoch=10)
        state = emit.record_result(state, False, "url_error", now_epoch=20)
        self.assertEqual(state["consecutive_failures"], 2)
        self.assertTrue(emit.should_alert(state, threshold=2))

    def test_success_resets_counter(self) -> None:
        state = emit.empty_state()
        state = emit.record_result(state, False, "http_503", now_epoch=10)
        state = emit.record_result(state, False, "http_503", now_epoch=20)
        self.assertTrue(emit.should_alert(state))
        state = emit.record_result(state, True, now_epoch=30)
        self.assertEqual(state["consecutive_failures"], 0)
        self.assertEqual(state["last_error"], "")
        self.assertEqual(state["last_success_epoch"], 30)
        self.assertFalse(emit.should_alert(state))

    def test_threshold_parameter(self) -> None:
        state = emit.record_result(emit.empty_state(), False, "x", now_epoch=1)
        self.assertTrue(emit.should_alert(state, threshold=1))
        self.assertFalse(emit.should_alert(state, threshold=3))
        state = emit.record_result(state, False, "x", now_epoch=2)
        state = emit.record_result(state, False, "x", now_epoch=3)
        self.assertTrue(emit.should_alert(state, threshold=3))

    def test_error_token_is_truncated_and_never_requires_a_secret(self) -> None:
        state = emit.record_result(emit.empty_state(), False, "e" * 200, now_epoch=1)
        self.assertEqual(len(state["last_error"]), 80)


if __name__ == "__main__":
    unittest.main()
