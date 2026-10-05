"""Remaining own draws limit shape rewards without forcing every late fold."""
from collections import Counter
from copy import deepcopy
import random
import unittest

import advisor
from test_advisor import state, tiles


def late_unready_state():
    s = state("2m235678p1167s677z")
    s.update(left=1, lastDraw="7p", doras=["7s"], lastStep=137,
             lastAction={"name": "ActionDealTile", "seat": 0, "step": 137})
    rivers = [
        "3m2m3p9m1z2s5z1p5z1z3s4z8s6p1p4s6m",
        "7p7m5p8s4s5z1m2m1p7z8p1m3z4p1z4s6m",
        "8m5m7p2z9m5m1s3m9p5s3z9m4p5z9p3m2p",
        "4m4p8m6m9s5s1p6s3m8s4m6s2z9m2s4s6z",
    ]
    s["rivers"] = [[{"tile": tile} for tile in tiles(river)] for river in rivers]
    return s


def quiet_state(hand, river_length):
    """A physical four-player deal with one shared safe tile and no calls."""
    s = state(hand)
    pool = [tile for tile in advisor.TILES for _ in range(4)]
    for suit in "mps":
        pool.remove("5" + suit)
        pool.append("0" + suit)
    for tile in s["hand"]:
        pool.remove(tile)
    for seat in (1, 2, 3):
        pool.remove("1s")
        s["rivers"][seat] = [{"tile": "1s"}]
    random.Random(0).shuffle(pool)
    for river in s["rivers"]:
        river.extend({"tile": pool.pop()} for _ in range(river_length - len(river)))
    step = 8 * river_length + 1
    s.update(left=69 - 4 * river_length, doras=[pool.pop()], lastDraw=s["hand"][-1], lastStep=step,
             lastAction={"name": "ActionDealTile", "seat": 0, "step": step})
    return s


class PhaseRewardTests(unittest.TestCase):
    def assert_physical(self, s):
        public = s["hand"] + s["doras"] + [d["tile"] for river in s["rivers"] for d in river]
        self.assertTrue(all(count <= 4 for count in advisor.counts34(public)))
        exact = Counter(public)
        for suit in "mps":
            self.assertLessEqual(exact["5" + suit], 3)
            self.assertLessEqual(exact["0" + suit], 1)
        self.assertEqual(len(s["hand"]) + sum(map(len, s["rivers"])) + 39 + 14 + s["left"], 136)
        self.assertEqual(sum(s["scores"]) + 1000 * s["riichiSticks"], 100000)

    def test_no_remaining_own_draw_prefers_safety_over_unreachable_progress(self):
        s = late_unready_state()
        self.assert_physical(s)
        before = deepcopy(s)
        self.assertEqual(advisor._opportunities(s, after_discard=True), (1,))
        advice = advisor.advise(s)
        self.assertEqual(advice["status"], "ready")
        self.assertEqual(s, before)
        self.assertTrue(all(c["shanten"] >= 2 for c in advice["candidates"]))
        for candidate in advice["candidates"]:
            self.assertEqual(candidate["winProbability"], 0)
            self.assertEqual(candidate["scoreBreakdown"].get("efficiencyReward", 0), 0)
        self.assertEqual(advice["best"]["expectedDealInLoss"],
                         min(c["expectedDealInLoss"] for c in advice["candidates"]))

    def test_one_draw_cannot_reward_unreachable_two_shanten_progress(self):
        s = late_unready_state()
        s["left"] = 5
        s["rivers"] = [river[:-1] for river in s["rivers"]]
        s["lastStep"] = s["lastAction"]["step"] = 129
        self.assert_physical(s)
        hand = s["hand"].copy()
        hand.remove("2m")
        self.assertEqual(advisor._opportunities(s, after_discard=True).count(0), 1)
        candidate = advisor._position(hand, s, advisor.unseen_counts(s), "2m")
        self.assertEqual(candidate["shanten"], 2)
        self.assertEqual(candidate["scoreBreakdown"].get("efficiencyReward", 0), 0)

    def test_two_draws_partially_reward_reachable_two_shanten_progress(self):
        s = late_unready_state()
        s["left"] = 9
        s["rivers"] = [river[:-2] for river in s["rivers"]]
        s["lastStep"] = s["lastAction"]["step"] = 121
        self.assert_physical(s)
        hand = s["hand"].copy()
        hand.remove("2m")
        self.assertEqual(advisor._opportunities(s, after_discard=True).count(0), 2)
        candidate = advisor._position(hand, s, advisor.unseen_counts(s), "2m")
        self.assertEqual(candidate["shanten"], 2)
        reward = candidate["scoreBreakdown"].get("efficiencyReward", 0)
        self.assertGreater(reward, 0)
        self.assertLess(reward, 70 * (6 - candidate["shanten"]) + 2 * candidate["ukeire"])
        # A candidate-specific factor turns the common 420-point offset into
        # an extra reason to push the two-shanten discard over a safer option.
        advice = advisor.advise(s)
        ratios = [c["scoreBreakdown"].get("efficiencyReward", 0) /
                  (70 * (6 - c["shanten"]) + 2 * c["ukeire"]) for c in advice["candidates"]]
        self.assertTrue(all(abs(r - ratios[0]) < 1e-12 for r in ratios))
        # Shared efficiency scaling remains, while actual future risk and
        # draw settlement can now make this same discard competitive.
        self.assertLessEqual(advice["best"]["expectedDealInLoss"], candidate["expectedDealInLoss"])

    def test_early_shape_space_remains_but_early_riichi_still_matters(self):
        s = quiet_state("147m147p147s12345z", 5)
        self.assert_physical(s)
        quiet = advisor.advise(s)
        self.assertEqual(quiet["status"], "ready")
        for candidate in quiet["candidates"]:
            self.assertEqual(candidate["scoreBreakdown"]["efficiencyReward"],
                             70 * (6 - candidate["shanten"]) + 2 * candidate["ukeire"])
        s["riichi"][1] = True
        s["scores"][1] -= 1000
        s["riichiSticks"] = 1
        self.assert_physical(s)
        threatened = advisor.advise(s)
        self.assertEqual(threatened["status"], "ready")
        self.assertNotEqual(quiet["best"]["tile"], threatened["best"]["tile"])
        risk = next(r for r in threatened["best"]["opponentRisks"] if r["seat"] == 1)
        self.assertEqual(risk["probability"], 0)

    def test_late_valuable_live_tenpai_can_still_accept_risk(self):
        s = quiet_state("123m123p123s45s77z1z", 15)
        self.assert_physical(s)
        s["riichi"][1] = True
        s["scores"][1] -= 1000
        s["riichiSticks"] = 1
        self.assert_physical(s)
        advice = advisor.advise(s)
        self.assertEqual(advice["status"], "ready")
        best = advice["best"]
        self.assertEqual(best["tile"], "1z")
        self.assertEqual(best["shanten"], 0)
        self.assertGreater(best["expectedWinPoints"], 4000)
        self.assertGreaterEqual(sum(w["count"] for w in best["winningTiles"]), 4)
        self.assertGreater(best["winProbability"], 0)
        self.assertGreater(best["dealInProbability"], 0)
        self.assertGreater(best["scoreBreakdown"].get("exhaustiveDrawPayment", 0), 0)
        self.assertNotIn("lateTenpaiReward", best["scoreBreakdown"])


if __name__ == "__main__":
    unittest.main()
