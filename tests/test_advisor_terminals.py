"""Public terminal ledgers must describe the same action and score as the policy."""
from copy import deepcopy
from math import fsum, isfinite
import unittest

import advisor
from test_advisor import state, tiles
from test_advisor_actions import own_action, get_action


class TerminalIntegrationTests(unittest.TestCase):
    def assert_terminal_ledger(self, candidate):
        terminal = candidate["terminalProbabilities"]
        self.assertTrue({"selfWin", "dealIn", "opponentTsumo", "otherRon", "exhaustiveDraw"} <= terminal.keys())
        self.assertTrue(all(isfinite(p) and 0 <= p <= 1 for p in terminal.values()))
        self.assertAlmostEqual(fsum(terminal.values()), 1., places=10)
        self.assertAlmostEqual(terminal["selfWin"], candidate["winProbability"], delta=.000051)
        future = candidate.get("futureDiscardDealInProbability", 0) + candidate.get("futureForcedDealInProbability", 0)
        self.assertAlmostEqual(terminal["dealIn"], candidate["dealInProbability"] + future, delta=.00016)
        terms = candidate["scoreBreakdown"]
        self.assertAlmostEqual(fsum(terms.values()), candidate["score"], places=8)
        for field, term in (("expectedOpponentTsumoLoss", "opponentTsumoLoss"),
                            ("expectedOtherRonLiabilityLoss", "otherRonLiabilityLoss"),
                            ("expectedDrawPayment", "exhaustiveDrawPayment")):
            sign = 1 if field == "expectedDrawPayment" else -1
            self.assertAlmostEqual(sign * candidate[field], terms.get(term, 0), delta=.00051)
        self.assertGreaterEqual(candidate["futureFoldProbability"], 0)
        self.assertLessEqual(candidate["futureFoldProbability"], 1)
        return terminal

    def test_ordinary_discard_and_new_riichi_share_complete_terminal_ledger(self):
        s = own_action("123m123p123s45s77z1z", 7, ["1z"])
        s["left"] = 8
        s["riichi"][1] = True
        advice = advisor.advise(s)
        self.assertEqual(advice["status"], "ready")
        self.assertTrue(any(c["action"] == "riichi" for c in advice["candidates"]))
        for candidate in advice["candidates"]:
            with self.subTest(action=candidate["actionId"]):
                self.assert_terminal_ledger(candidate)

    def test_fourth_riichi_replaces_all_continuation_fields_with_abort(self):
        s = own_action("123m123p123s45s77z1z", 7, ["1z"])
        s["left"] = 8
        s["riichi"] = [False, True, True, True]
        candidate = get_action(s, "riichi")
        self.assertTrue(candidate["abortAfterRiichi"])
        terminal = self.assert_terminal_ledger(candidate)
        self.assertGreater(terminal["abortiveDraw"], 0)
        self.assertAlmostEqual(terminal["abortiveDraw"] + terminal["dealIn"], 1.)
        for outcome in ("selfWin", "opponentTsumo", "otherRon", "exhaustiveDraw"):
            self.assertEqual(terminal[outcome], 0)
        for field in ("futureForcedDealInProbability", "futureForcedDealInLoss", "expectedOpponentTsumoLoss",
                      "expectedOtherRonLiabilityLoss", "expectedDrawPayment", "futureFoldProbability"):
            self.assertEqual(candidate[field], 0)

    def test_replacement_aggregates_each_terminal_and_payment_once(self):
        s = own_action("123p123s789s45p77z4z", 11, [], players=3)
        s["left"] = 8
        s["riichi"][1] = True
        before = deepcopy(s)
        candidate = get_action(s, "kita")
        self.assertTrue(candidate["replacementDraw"])
        terminal = self.assert_terminal_ledger(candidate)
        self.assertGreater(terminal["opponentTsumo"], 0)
        self.assertGreater(candidate["expectedOpponentTsumoLoss"], 0)
        self.assertEqual(s, before)

    def test_fourth_kan_only_replacement_win_discard_ron_or_abort_survive(self):
        s = own_action("2222m123p123s12s55z", 4, ["2m|2m|2m|2m"])
        s["left"] = 8
        s["melds"][1] = [{"type": 3, "tiles": tiles(t)} for t in ("7777m", "7777p", "9999p")]
        candidate = get_action(s, "ankan")
        self.assertTrue(candidate["abortAfterDiscard"])
        terminal = self.assert_terminal_ledger(candidate)
        self.assertGreater(terminal["selfWin"], 0)
        self.assertGreater(terminal["abortiveDraw"], 0)
        for outcome in ("opponentTsumo", "otherRon", "exhaustiveDraw"):
            self.assertEqual(terminal[outcome], 0)
        for field in ("expectedOpponentTsumoLoss", "expectedOtherRonLiabilityLoss", "expectedDrawPayment",
                      "futureDiscardDealInLoss", "futureForcedDealInLoss", "futureFoldProbability"):
            self.assertEqual(candidate[field], 0)

    def test_nine_terminals_removes_shape_but_preserves_terminal_payments(self):
        s = own_action("19m19p19s123z245p67s", 10, [])
        s["left"] = 70
        s["lastStep"] = 0
        without_abort = deepcopy(s)
        without_abort["operations"] = [1]
        without_abort["operationDetails"] = []
        ordinary = advisor.advise(without_abort)
        offered = advisor.advise(s)
        self.assertEqual(ordinary["status"], "ready")
        self.assertEqual(offered["status"], "ready")
        baseline = {c["actionId"]: c for c in ordinary["candidates"]}
        for candidate in offered["candidates"]:
            with self.subTest(action=candidate["actionId"]):
                terminal = self.assert_terminal_ledger(candidate)
                if candidate["action"] == "abort":
                    self.assertEqual(terminal["abortiveDraw"], 1)
                    self.assertEqual(candidate["score"], 0)
                    continue
                before = baseline[candidate["actionId"]]
                self.assertEqual(terminal, before["terminalProbabilities"])
                for field in ("expectedOpponentTsumoLoss", "expectedOtherRonLiabilityLoss", "expectedDrawPayment"):
                    self.assertEqual(candidate[field], before[field])
                expected = fsum(value for term, value in before["scoreBreakdown"].items()
                                if term not in ("efficiencyReward", "roundingAdjustment"))
                self.assertAlmostEqual(candidate["score"], expected, delta=.051)


if __name__ == "__main__":
    unittest.main()
