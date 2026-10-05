"""Current push/fold accounting, independent of historical recommendation labels.

policyComparison stores numeric attack utility; fold utility is None when
the current discard is not part of the minimum-current-loss defensive policy.
Current fold is the documented pure-noten approximation: it forgoes wins and
never claims an attack efficiency reward. These tests do not infer alternate
outcomes from the logged 18000-point loss. Synthetic weak/strong states assert
policy properties only after their structural premises are verified below.
"""
from copy import deepcopy
import json
from math import fsum, isfinite
from pathlib import Path
import unittest

import advisor
from test_advisor import state, tiles


FIXTURE = Path(__file__).resolve().parent / "advisor_policy_logged_cases.json"
if not FIXTURE.exists():
    FIXTURE = Path(__file__).resolve().parent / "fixtures/advisor_policy_logged_cases.json"


def weak_no_genbutsu_state():
    """Several shanten, two future draws, no held tile in a riichi river."""
    s = state("147m147p147s12345z")
    s.update(left=8, lastDraw="5z", riichiSticks=3,
             lastAction={"name": "ActionDealTile", "seat": 0, "tile": "5z", "step": 40})
    s["riichi"] = [False, True, True, True]
    s["riichiStep"] = [None, 10, 20, 30]
    s["scores"] = [25000, 24000, 24000, 24000]
    s["rivers"][1] = [{"tile": "2p", "step": 10}]
    s["rivers"][2] = [{"tile": "5p", "step": 20}]
    s["rivers"][3] = [{"tile": "8p", "step": 30}]
    return s


def valuable_ready_state():
    s = state("123m123p123s45s77z1z")
    s.update(left=28, lastDraw="1z", doras=["6z"], riichiSticks=1,
             lastAction={"name": "ActionDealTile", "seat": 0, "tile": "1z", "step": 40})
    s["riichi"][1] = True
    s["riichiStep"][1] = 20
    s["rivers"][1] = [{"tile": "9p", "step": 20}]
    s["scores"][1] -= 1000
    return s


def without_elapsed(advice):
    return {key: value for key, value in advice.items() if key != "elapsedMs"}


class CurrentPolicyTests(unittest.TestCase):
    def evaluate(self, snapshot):
        before = deepcopy(snapshot)
        self.assertGreaterEqual(min(advisor.unseen_counts(snapshot)), 0)
        advice = advisor.advise(snapshot)
        self.assertEqual(advice["status"], "ready", advice)
        self.assertEqual(snapshot, before)
        self.assertTrue(advice["candidates"])
        self.assertEqual(len({c["actionId"] for c in advice["candidates"]}), len(advice["candidates"]))
        json.dumps(advice, allow_nan=False)
        return advice

    def assert_consistent_policy(self, candidate):
        self.assertIn(candidate["currentStrategy"], ("attack", "fold", "locked"))
        terminal = candidate["terminalProbabilities"]
        self.assertTrue(all(isfinite(p) and 0 <= p <= 1 for p in terminal.values()))
        self.assertAlmostEqual(fsum(terminal.values()), 1., places=10)
        self.assertAlmostEqual(terminal["selfWin"], candidate["winProbability"], delta=.000051)
        future = candidate.get("futureDiscardDealInProbability", 0) + candidate.get("futureForcedDealInProbability", 0)
        self.assertAlmostEqual(terminal["dealIn"], candidate["dealInProbability"] + future, delta=.00016)
        terms = candidate["scoreBreakdown"]
        self.assertAlmostEqual(fsum(terms.values()), candidate["score"], places=8)
        self.assertNotIn("efficiencyReward", terms)
        self.assertGreaterEqual(candidate["futureFoldProbability"], 0)
        self.assertLessEqual(candidate["futureFoldProbability"], 1)
        for field, term, sign in (("expectedOpponentTsumoLoss", "opponentTsumoLoss", -1),
                                  ("expectedOtherRonLiabilityLoss", "otherRonLiabilityLoss", -1),
                                  ("expectedDrawPayment", "exhaustiveDrawPayment", 1)):
            self.assertAlmostEqual(sign * candidate[field], terms.get(term, 0), delta=.00051)
        selected = candidate["currentStrategy"]
        if selected != "locked":
            comparison = candidate["policyComparison"]
            self.assertTrue(isfinite(comparison["attack"]))
            if comparison["fold"] is None:
                self.assertEqual(selected, "attack")
            else:
                self.assertTrue(isfinite(comparison["fold"]))
                self.assertGreaterEqual(comparison[selected] + 1e-8,
                                        comparison["fold" if selected == "attack" else "attack"])
            self.assertAlmostEqual(candidate["score"], comparison[selected], delta=.051)
        if selected == "fold":
            self.assertEqual(candidate["winProbability"], 0)
            self.assertEqual(candidate["expectedWinPoints"], 0)
            self.assertEqual(terminal["selfWin"], 0)
            self.assertEqual(terms.get("winIncome", 0), 0)
            self.assertEqual(candidate["futureFoldProbability"], 0)
            self.assertLessEqual(candidate["expectedDrawPayment"], 0)
        if selected == "locked":
            self.assertEqual(candidate["futureFoldProbability"], 0)

    def test_recorded_decisions_keep_complete_strategy_ledgers(self):
        cases = json.loads(FIXTURE.read_text())["cases"]
        self.assertEqual(len(cases), 8)
        for case in cases:
            with self.subTest(case=case["id"]):
                advice = self.evaluate(deepcopy(case["state"]))
                self.assertEqual(len(advice["candidates"]), len(set(case["state"]["hand"])))
                for candidate in advice["candidates"]:
                    self.assert_consistent_policy(candidate)

    def test_weak_hand_can_fold_without_a_genbutsu(self):
        s = weak_no_genbutsu_state()
        advice = self.evaluate(s)
        own_draws = advisor._opportunities(s, after_discard=True).count(s["selfSeat"])
        self.assertTrue(all(c["shanten"] > own_draws for c in advice["candidates"]))
        self.assertTrue(all(c["dealInProbability"] > 0 for c in advice["candidates"]))
        best = advice["best"]
        self.assertEqual(best["currentStrategy"], "fold", best)
        self.assert_consistent_policy(best)
        # This is a net-outcome comparison: current loss alone cannot prove
        # dominance when retained physical safety stock changes future loss.
        self.assertGreaterEqual(best["policyComparison"]["fold"],
                                best["policyComparison"]["attack"])

    def test_valuable_live_tenpai_still_attacks(self):
        advice = self.evaluate(valuable_ready_state())
        best = advice["best"]
        self.assertEqual(best["shanten"], 0)
        self.assertEqual(best["currentStrategy"], "attack", best)
        self.assertGreater(best["winProbability"], 0)
        self.assertGreater(best["scoreBreakdown"].get("winIncome", 0), 0)
        if best["policyComparison"]["fold"] is not None:
            self.assertGreater(best["policyComparison"]["attack"], best["policyComparison"]["fold"])
        self.assert_consistent_policy(best)

    def test_new_snapshot_can_return_to_attack_and_is_not_cache_contaminated(self):
        strong = valuable_ready_state()
        expected = self.evaluate(deepcopy(strong))
        weak = self.evaluate(weak_no_genbutsu_state())
        self.assertEqual(weak["best"]["currentStrategy"], "fold")
        actual = self.evaluate(deepcopy(strong))
        self.assertEqual(actual["best"]["currentStrategy"], "attack")
        self.assertEqual(without_elapsed(actual), without_elapsed(expected))

    def test_cancellation_does_not_publish_a_partial_policy_or_poison_next_window(self):
        s = valuable_ready_state()
        expected = self.evaluate(deepcopy(s))
        cancelled = advisor.advise(weak_no_genbutsu_state(), cancelled=lambda: True)
        self.assertEqual(cancelled["status"], "unavailable")
        self.assertFalse(cancelled.get("candidates"))
        self.assertFalse(cancelled.get("best"))
        self.assertEqual(without_elapsed(self.evaluate(deepcopy(s))), without_elapsed(expected))

    def test_confirmed_riichi_keeps_locked_policy_and_forced_discard(self):
        s = valuable_ready_state()
        s["riichi"][0] = True
        s["riichiStep"][0] = 10
        s["riichiSticks"] += 1
        s["scores"][0] -= 1000
        s["rivers"][0] = [{"tile": "9m", "step": 10}]
        advice = self.evaluate(s)
        self.assertEqual(len(advice["candidates"]), 1)
        self.assertEqual(advice["best"]["tile"], s["lastDraw"])
        self.assertEqual(advice["best"]["currentStrategy"], "locked")
        self.assert_consistent_policy(advice["best"])

    def test_meaningful_yakuhai_and_honor_pairs_survive_tie_breaking(self):
        s = state("666z123p45s77p2p", 3)
        s["melds"][0] = [{"type": 0, "tiles": tiles("789s")}]
        advice = self.evaluate(s)
        best = advice["best"]
        self.assertEqual(best["shanten"], 0)
        self.assertNotEqual(best["tile"], "6z")
        self.assertTrue(any("Yakuhai (hatsu)" in w["yaku"] and w["ronPoints"] > 0
                            for w in best["winningTiles"]))
        s = state("11p22p44p66s88s66z1m9s", 3)
        advice = self.evaluate(s)
        self.assertEqual(advice["best"]["shanten"], 0)
        self.assertIn(advice["best"]["tile"], ("1m", "9s"))
        self.assertTrue(any("Chiitoitsu" in w["yaku"] for w in advice["best"]["winningTiles"]))

    def test_sanma_kokushi_keeps_real_orphan_waits(self):
        s = state("119m19p19s123456z2p", 3)
        advice = self.evaluate(s)
        c = next(c for c in advice["candidates"] if c["tile"] == "2p")
        self.assertEqual(c["shanten"], 0)
        waits = [w for w in c["winningTiles"] if w["count"] and w["ronPoints"]]
        self.assertEqual({w["tile"] for w in waits}, {"7z"})
        self.assertTrue(any("Kokushi Musou" in w["yaku"] for w in waits))
        self.assertEqual(advisor.unseen_counts(s)[1:8], (0,) * 7)
        self.assertNotEqual(advice["best"]["tile"], "6z")

    def test_server_legal_win_precedes_any_defensive_policy(self):
        self.assertEqual(self.evaluate(weak_no_genbutsu_state())["best"]["currentStrategy"], "fold")
        for operations, action in (([9], "ron"), ([1, 8], "tsumo")):
            s = weak_no_genbutsu_state()
            s["operations"] = operations
            result = advisor.advise(s)
            self.assertEqual(result["status"], "win")
            self.assertEqual(result["action"], action)


if __name__ == "__main__":
    unittest.main()
