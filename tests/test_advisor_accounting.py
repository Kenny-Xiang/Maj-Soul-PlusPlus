"""Original score accounting preserves precision and action-specific resets."""
import json
from math import fsum, isfinite
from pathlib import Path
import unittest
from unittest.mock import patch

import advisor
from test_advisor import state, tiles
from test_advisor_actions import get_action, offered, own_action


class ScoreAccountingTests(unittest.TestCase):
    def assert_ledger(self, candidate):
        terms = candidate["scoreBreakdown"]
        self.assertIn("roundingAdjustment", terms)
        self.assertTrue(all(isfinite(value) for value in terms.values()))
        self.assertAlmostEqual(fsum(terms.values()), candidate["score"], places=8)
        # A single score rounds to 0.1; extensions and replacement means can
        # carry one prior rounding too. A missing semantic term is not rounding.
        self.assertLessEqual(abs(terms["roundingAdjustment"]), .101)
        for key, value in terms.items():
            if key in ("winIncome", "efficiencyReward", "lateTenpaiReward"):
                self.assertGreater(value, 0)
            elif key not in ("roundingAdjustment", "riskPreferenceAdjustment"):
                self.assertLess(value, 0)
        return terms

    def test_all_fixture_candidates_have_compact_reconcilable_accounts(self):
        cases = json.loads((Path(__file__).parent / "fixtures/advisor_cases.json").read_text())["cases"]
        for case in cases:
            with self.subTest(case=case["id"]):
                advice = advisor.advise(case["state"])
                self.assertEqual(advice["status"], case["expectedStatus"])
                for candidate in advice["candidates"]:
                    self.assert_ledger(candidate)

    def test_position_keeps_raw_values_separate_from_rounded_metrics(self):
        s = state()
        s["left"] = 7
        hand = s["hand"].copy()
        hand.remove("1z")
        probability, points, danger, loss = .123456, 1234.567, .023456, 234.56789
        with patch.object(advisor, "_win_model", return_value=(probability, points)), patch.object(
                advisor, "_danger", return_value=(danger, loss, [])):
            candidate = advisor._position(hand, s, advisor.unseen_counts(s), "1z")
        terms = self.assert_ledger(candidate)
        self.assertEqual(terms["winIncome"], probability * (1 - danger) * points)
        self.assertNotEqual(terms["winIncome"], candidate["winProbability"] * candidate["expectedWinPoints"])
        self.assertEqual(terms["currentDealInLoss"], -loss)
        self.assertEqual(terms["riskPreferenceAdjustment"], -(advisor._risk_weight(s) - 1) * loss)
        self.assertEqual(terms["lateTenpaiReward"], 1125)

    def test_riichi_appends_raw_costs_without_overwriting_current_risk(self):
        s = own_action("123m123p123s45s77z1z", 7, ["1z"])
        locked_loss = 123.456789
        with patch.object(advisor, "_locked_risk", return_value=locked_loss):
            candidate = get_action(s, "riichi")
        terms = self.assert_ledger(candidate)
        self.assertEqual(terms["futureForcedDealInLoss"], -locked_loss)
        self.assertEqual(terms["riichiCost"], -1000 * (1 - candidate["dealInProbability"] - candidate["winProbability"]))
        self.assertAlmostEqual(terms["riskPreferenceAdjustment"],
                               (advisor._risk_weight(s) - 1) *
                               (terms["currentDealInLoss"] + terms["futureForcedDealInLoss"]))

    def test_four_riichi_discards_prior_shape_and_future_income(self):
        s = own_action("123m123p123s45s77z1z", 7, ["1z"])
        s["riichi"] = [False, True, True, True]
        for seat in (1, 2, 3):
            s["rivers"][seat] = [{"tile": "1z"}]
        candidate = get_action(s, "riichi")
        self.assertTrue(candidate["abortAfterRiichi"])
        self.assertEqual(self.assert_ledger(candidate), {"riichiCost": -1000., "roundingAdjustment": 0.})

    def test_call_no_yaku_penalty_is_separate(self):
        s = offered("123m456p789s55z23s", 2, ["2s|3s"], "1s")
        candidate = get_action(s, "chi")
        self.assertEqual(self.assert_ledger(candidate)["openNoYakuPenalty"], -500)

    def test_four_kan_only_direct_replacement_wins_keep_shape_reward(self):
        # A simple kan cannot be robbed for kokushi, making the physical draw
        # weights independently sufficient to check the surviving +420 reward.
        s = own_action("2222m123p123s12s55z", 4, ["2m|2m|2m|2m"])
        s["melds"][1] = [{"type": 3, "tiles": tiles(t)} for t in ("7777m", "7777p", "9999p")]
        candidate = get_action(s, "ankan")
        terms = self.assert_ledger(candidate)
        self.assertTrue(candidate["abortAfterDiscard"])
        self.assertEqual(candidate["robKanProbability"], 0)
        outcomes = candidate["replacementOutcomes"]
        winning = sum(o["count"] for o in outcomes if o["winProbability"] == 1)
        self.assertGreater(winning, 0)
        self.assertLess(winning, sum(o["count"] for o in outcomes))
        self.assertAlmostEqual(terms["efficiencyReward"], 420 * winning / sum(o["count"] for o in outcomes))
        self.assertNotIn("lateTenpaiReward", terms)
        self.assertNotIn("newDoraPenalty", terms)

    def test_abort_normalization_replaces_discard_and_replacement_accounts(self):
        s = own_action("19m19p19s124z245p67s", 10, [], players=3)
        s["operations"].append(11)
        s["operationDetails"].append({"type": 11, "combination": []})
        advice = advisor.advise(s)
        self.assertEqual(advice["status"], "ready")
        self.assertTrue(any(c["action"] == "kita" for c in advice["candidates"]))
        for candidate in advice["candidates"]:
            terms = self.assert_ledger(candidate)
            if candidate["action"] == "abort":
                self.assertEqual(terms, {"roundingAdjustment": 0.})
            else:
                self.assertNotIn("efficiencyReward", terms)
                self.assertNotIn("lateTenpaiReward", terms)
                self.assertIn("abortContinuationLoss", terms)
                self.assertAlmostEqual(terms.get("winIncome", 0),
                                       candidate["winProbability"] * candidate["expectedWinPoints"])
                self.assertEqual(terms.get("currentDealInLoss", 0), -candidate["expectedDealInLoss"])


if __name__ == "__main__":
    unittest.main()
