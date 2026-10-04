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
        self.assertEqual(advisor.advise(state())["status"], "ready")


if __name__ == "__main__":
    unittest.main()
