"""Original score accounting preserves precision and action-specific resets."""
import json
from math import fsum, isfinite
from pathlib import Path
import unittest
from unittest.mock import patch

import advisor
from advisor_policy import Outcome
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
            if key in ("winIncome", "efficiencyReward"):
                self.assertGreater(value, 0)
            elif key not in ("roundingAdjustment", "riskPreferenceAdjustment", "exhaustiveDrawPayment"):
                self.assertLess(value, 0)
        if "terminalProbabilities" in candidate:
            probabilities = candidate["terminalProbabilities"].values()
            self.assertTrue(all(isfinite(p) and 0 <= p <= 1 for p in probabilities))
            self.assertAlmostEqual(fsum(probabilities), 1., places=12)
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
        continuation = Outcome(win=probability, income=probability * points,
                               deal=.111111, loss=123.456789, tsumo=.2, tsumo_loss=234.567891,
                               other=.1, other_loss=12.345678,
                               draw=1 - probability - .111111 - .2 - .1,
                               draw_income=567.891234)
        with patch.object(advisor, "_ready_policy", return_value=[continuation]), patch.object(
                advisor, "_danger", return_value=(danger, loss, [])):
            candidate = advisor._position(hand, s, advisor.unseen_counts(s), "1z")
        terms = self.assert_ledger(candidate)
        self.assertAlmostEqual(terms["winIncome"], probability * (1 - danger) * points, places=12)
        self.assertNotEqual(terms["winIncome"], candidate["winProbability"] * candidate["expectedWinPoints"])
        self.assertEqual(terms["currentDealInLoss"], -loss)
        self.assertEqual(terms["futureDiscardDealInLoss"], -(1 - danger) * continuation.loss)
        self.assertAlmostEqual(terms["riskPreferenceAdjustment"], -(advisor._risk_weight(s) - 1) *
                               (loss + (1 - danger) * continuation.loss), places=12)
        self.assertEqual(terms["opponentTsumoLoss"], -(1 - danger) * continuation.tsumo_loss)
        self.assertEqual(terms["otherRonLiabilityLoss"], -(1 - danger) * continuation.other_loss)
        self.assertEqual(terms["exhaustiveDrawPayment"], (1 - danger) * continuation.draw_income)
        self.assertNotEqual(terms["exhaustiveDrawPayment"], candidate["expectedDrawPayment"])
        self.assertNotIn("lateTenpaiReward", terms)

    def test_last_discard_uses_actual_tenpai_transfer_in_both_directions(self):
        s = state()
        s["left"] = 0
        remaining = advisor.unseen_counts(s)
        opponents = advisor._opponents(s, remaining)
        for enemy, probability in zip(opponents, (1., 1., 0.)):
            enemy["tenpai"] = probability
        with patch.object(advisor, "_opponents", return_value=opponents), patch.object(
                advisor, "_danger", return_value=(0., 0., [])):
            for discard, payment in (("1z", 1000.), ("1m", -1500.)):
                with self.subTest(discard=discard):
                    hand = s["hand"].copy()
                    hand.remove(discard)
                    candidate = advisor._position(hand, s, remaining, discard)
                    terms = self.assert_ledger(candidate)
                    self.assertEqual(candidate["terminalProbabilities"]["exhaustiveDraw"], 1.)
                    self.assertEqual(terms["exhaustiveDrawPayment"], payment)
                    self.assertEqual(candidate["expectedDrawPayment"], payment)
                    self.assertNotIn("lateTenpaiReward", terms)

    def test_riichi_appends_raw_costs_without_overwriting_current_risk(self):
        s = own_action("123m123p123s45s77z1z", 7, ["1z"])
        locked_loss = 123.456789
        continuation = Outcome(win=.25, income=1000., deal=.1, loss=locked_loss,
                               tsumo=.15, tsumo_loss=87.654321, other=.1, draw=.4,
                               draw_income=123.456789)
        danger = .123456
        with patch.object(advisor, "_ready_policy",
                          side_effect=lambda *args, **kwargs: [continuation] * (len(args[4]) + 1)), patch.object(
                advisor, "_danger", return_value=(danger, 987.654321, [])):
            candidate = get_action(s, "riichi")
        terms = self.assert_ledger(candidate)
        self.assertEqual(terms["futureForcedDealInLoss"], -(1 - danger) * locked_loss)
        self.assertEqual(terms["currentDealInLoss"], -987.654321)
        self.assertEqual(terms["opponentTsumoLoss"], -(1 - danger) * continuation.tsumo_loss)
        self.assertEqual(terms["exhaustiveDrawPayment"], (1 - danger) * continuation.draw_income)
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
        self.assertNotIn("exhaustiveDrawPayment", terms)
        self.assertNotIn("newDoraPenalty", terms)

    def test_abort_normalization_replaces_discard_and_replacement_accounts(self):
        s = own_action("19m19p19s124z245p67s", 10, [], players=3)
        s["operations"].append(11)
        s["operationDetails"].append({"type": 11, "combination": []})
        ordinary = {**s, "operations": [1, 11],
                    "operationDetails": [{"type": 11, "combination": []}]}
        before = advisor.advise(ordinary)
        self.assertEqual(before["status"], "ready")
        original = {c["actionId"]: c for c in before["candidates"]}
        advice = advisor.advise(s)
        self.assertEqual(advice["status"], "ready")
        self.assertTrue(any(c["action"] == "kita" for c in advice["candidates"]))
        for candidate in advice["candidates"]:
            terms = self.assert_ledger(candidate)
            if candidate["action"] == "abort":
                self.assertEqual(terms, {"roundingAdjustment": 0.})
            else:
                self.assertNotIn("efficiencyReward", terms)
                self.assertNotIn("openNoYakuPenalty", terms)
                self.assertNotIn("abortContinuationLoss", terms)
                self.assertIn("opponentTsumoLoss", terms)
                expected = {k: v for k, v in original[candidate["actionId"]]["scoreBreakdown"].items()
                            if k not in ("efficiencyReward", "openNoYakuPenalty", "roundingAdjustment")}
                self.assertEqual({k: v for k, v in terms.items() if k != "roundingAdjustment"}, expected)
                self.assertEqual(candidate["score"], round(fsum(expected.values()), 1))

    def test_abort_normalization_preserves_future_one_shanten_discard_loss(self):
        s = own_action("119m19p19s123456z2p", 10, [])
        advice = advisor.advise(s)
        self.assertEqual(advice["status"], "ready")
        continuations = [c for c in advice["candidates"] if c.get("futureDiscardDealInLoss", 0)]
        self.assertTrue(continuations)
        for candidate in continuations:
            terms = self.assert_ledger(candidate)
            self.assertEqual(round(-terms["futureDiscardDealInLoss"]), candidate["futureDiscardDealInLoss"])
            self.assertAlmostEqual(terms["riskPreferenceAdjustment"], (advisor._risk_weight(s) - 1) *
                                   (terms.get("currentDealInLoss", 0) + terms["futureDiscardDealInLoss"]), places=10)

    def test_replacement_conditions_future_discard_loss_on_robbery_survival_once(self):
        s = own_action("123p123s789s45p77z4z", 11, [], players=3)
        choice = advisor._action_choices(s)[0][0]
        weight = advisor._risk_weight(s)

        def followup(snapshot, remaining):
            future = 100 if snapshot["lastDraw"] == "1z" else 300
            candidate = {"tile": "1z", "shanten": 1, "ukeire": 4, "furiten": False,
                         "winProbability": .2, "expectedWinPoints": 1000,
                         "dealInProbability": .05, "expectedDealInLoss": 50,
                         "futureDiscardDealInProbability": future / 1000,
                         "futureDiscardDealInLoss": future,
                         "terminalProbabilities": {"selfWin": .2, "dealIn": .05 + future / 1000,
                                                   "opponentTsumo": 0., "otherRon": 0.,
                                                   "exhaustiveDraw": .75 - future / 1000},
                         "score": round(200 - weight * (50 + future), 1)}
            advisor._record_score(candidate, winIncome=200, currentDealInLoss=-50,
                                  futureDiscardDealInLoss=-future,
                                  riskPreferenceAdjustment=-(weight - 1) * (50 + future))
            return [candidate]

        with patch.object(advisor, "_draw_pool", return_value=[("1z", 2), ("2z", 1)]), patch.object(
                advisor, "_discards", side_effect=followup), patch.object(
                advisor, "_danger", return_value=(.2, 1600., [])):
            candidate = advisor._replacement(s, choice, advisor.unseen_counts(s))
        expected_loss = .8 * (2 * 100 + 300) / 3
        self.assertEqual(candidate["futureDiscardDealInProbability"], round(.8 * (2 * .1 + .3) / 3, 4))
        self.assertEqual(candidate["futureDiscardDealInLoss"], round(expected_loss))
        terms = self.assert_ledger(candidate)
        self.assertAlmostEqual(terms["futureDiscardDealInLoss"], -expected_loss)
        self.assertAlmostEqual(terms["winIncome"], .8 * 200)


if __name__ == "__main__":
    unittest.main()
