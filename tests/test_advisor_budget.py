"""Expanded searches must not publish partially refined candidate lists."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import advisor
from test_advisor import state


class SearchBudgetTests(unittest.TestCase):
    def test_cancellation_at_completion_cannot_publish_ready(self):
        obsolete = False

        def finish(snapshot):
            nonlocal obsolete
            obsolete = True
            return {"status": "ready", "candidates": [{"action": "discard"}]}

        with patch.object(advisor, "_advise", side_effect=finish):
            result = advisor.advise(state(), cancelled=lambda: obsolete)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["reason"], "search_cancelled")
        self.assertFalse(result["recoverable"])

    def test_cancellation_during_search_discards_all_partial_results(self):
        snapshot = state()
        original = deepcopy(snapshot)
        checks = 0

        def cancelled():
            nonlocal checks
            checks += 1
            return checks >= 8

        result = advisor.advise(snapshot, cancelled=cancelled)
        self.assertEqual(checks, 8)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["candidates"], [])
        self.assertIsNone(result["best"])
        self.assertEqual(result["reason"], "search_cancelled")
        self.assertFalse(result["recoverable"])
        self.assertEqual(snapshot, original)
        self.assertEqual(advisor.advise(snapshot)["status"], "ready")

    def test_deadline_during_scoring_discards_partial_results(self):
        now = 0.
        score = advisor._wait_values

        def expire(*args, **kwargs):
            nonlocal now
            value = score(*args, **kwargs)
            now = advisor.SEARCH_SECONDS + 1
            return value

        with patch.object(advisor.time, "monotonic", side_effect=lambda: now), \
                patch.object(advisor, "_wait_values", side_effect=expire):
            result = advisor.advise(state())
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("时间预算", result["message"])
        self.assertEqual(result["candidates"], [])
        self.assertIsNone(result["best"])
        self.assertEqual(result["reason"], "search_budget_exceeded")
        self.assertTrue(result["recoverable"])
        self.assertEqual(advisor.advise(state())["status"], "ready")

    def test_budget_at_completion_does_not_publish_the_late_result(self):
        now = 0.

        def finish(snapshot):
            nonlocal now
            now = advisor.SEARCH_SECONDS + 1
            return {"status": "ready", "best": {"action": "discard", "tile": "1z"},
                    "candidates": [{"action": "discard", "tile": "1z"}]}

        with patch.object(advisor.time, "monotonic", side_effect=lambda: now), \
                patch.object(advisor, "_advise", side_effect=finish):
            result = advisor.advise(state())
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "search_budget_exceeded")
        self.assertTrue(result["recoverable"])
        self.assertEqual(result["candidates"], [])
        self.assertIsNone(result["best"])

    def test_invalid_data_cannot_claim_recovery_by_using_the_budget_message(self):
        with patch.object(advisor, "unseen_counts", side_effect=ValueError("前瞻计算超过时间预算，等待下一次局面")):
            result = advisor.advise(state())
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNot(result.get("recoverable"), True)
        self.assertNotEqual(result.get("reason"), "search_budget_exceeded")
        incomplete = state()
        incomplete["historyComplete"] = False
        result = advisor.advise(incomplete)
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNot(result.get("recoverable"), True)

    def test_invalid_result_at_the_deadline_does_not_become_recoverable(self):
        now = 0.

        def invalid(*args):
            nonlocal now
            now = advisor.SEARCH_SECONDS + 1
            raise ValueError('invalid tile counts')

        with patch.object(advisor.time, "monotonic", side_effect=lambda: now), \
                patch.object(advisor, "unseen_counts", side_effect=invalid):
            result = advisor.advise(state())
        self.assertEqual(result["status"], "unavailable")
        self.assertIn('invalid tile counts', result["message"])
        self.assertIsNot(result.get("recoverable"), True)
        self.assertNotEqual(result.get("reason"), "search_budget_exceeded")


if __name__ == "__main__":
    unittest.main()
