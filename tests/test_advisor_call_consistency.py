"""Call previews share the same terminal utility as their actual discard window."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import advisor


def call_state():
    path = Path(__file__).parent / "fixtures/advisor_call_consistency_cases.json"
    return json.loads(path.read_text())["cases"][0]["state"]


def realized_call(snapshot):
    choice = advisor._action_choices(snapshot)[0][0]
    after = advisor._apply_choice(snapshot, choice)
    after.update(canAct=True, canDiscard=True, operations=[1], operationDetails=[],
                 lastStep=snapshot["lastStep"] + 1)
    after["lastAction"] = {"name": "ActionChiPengGang", "seat": after["selfSeat"],
                           "step": after["lastStep"]}
    return after


class CallConsistencyTests(unittest.TestCase):
    def test_unconfirmed_yaku_pon_preserves_its_realized_followup(self):
        snapshot = call_state()
        preview = advisor.advise(snapshot)
        actual = advisor.advise(realized_call(snapshot))
        self.assertEqual(preview["status"], "ready")
        self.assertEqual(actual["status"], "ready")
        called = next(c for c in preview["candidates"] if c["action"] == "pon")
        self.assertEqual(actual["best"]["tile"], "1m")
        self.assertEqual(actual["best"]["shanten"], 2)
        self.assertEqual(called["followupDiscard"], actual["best"]["tile"])
        self.assertEqual(called["scoreBreakdown"], actual["best"]["scoreBreakdown"])

    def test_every_projected_call_discard_matches_its_realized_evaluation(self):
        captured = {}
        discards = advisor._discards

        def capture(*args, **kwargs):
            candidates = discards(*args, **kwargs)
            captured.update((c["tile"], deepcopy(c)) for c in candidates)
            return candidates

        snapshot = call_state()
        with patch.object(advisor, "_discards", side_effect=capture):
            preview = advisor.advise(snapshot)
        self.assertEqual(preview["status"], "ready")
        actual = advisor.advise(realized_call(snapshot))
        self.assertEqual(actual["status"], "ready")
        self.assertEqual(set(captured), {c["tile"] for c in actual["candidates"]})
        for candidate in actual["candidates"]:
            with self.subTest(tile=candidate["tile"]):
                projected = captured[candidate["tile"]]
                self.assertEqual(projected["scoreBreakdown"], candidate["scoreBreakdown"])
                self.assertEqual(projected["policyComparison"], candidate["policyComparison"])
                self.assertEqual(projected["terminalProbabilities"], candidate["terminalProbabilities"])

    def test_worse_draw_payments_cannot_increase_the_value_of_a_call(self):
        snapshot = call_state()
        before = advisor.advise(snapshot)
        payments = advisor._draw_payments

        def worse_payments(opponents, players):
            # Change only terminal fees: current danger and every available
            # policy stay fixed, while both noten and tenpai receipts decrease.
            later = [{**enemy, "tenpai": min(1., enemy["tenpai"] + .1)}
                     for enemy in opponents]
            old, new = payments(opponents, players), payments(later, players)
            self.assertTrue(all(n <= o for n, o in zip(new, old)))
            return new

        with patch.object(advisor, "_draw_payments", side_effect=worse_payments):
            after = advisor.advise(snapshot)
        self.assertEqual(before["status"], "ready")
        self.assertEqual(after["status"], "ready")
        previous = {c["actionId"]: c["score"] for c in before["candidates"]}
        for candidate in after["candidates"]:
            with self.subTest(action=candidate["actionId"]):
                self.assertLessEqual(candidate["score"], previous[candidate["actionId"]])


if __name__ == "__main__":
    unittest.main()
