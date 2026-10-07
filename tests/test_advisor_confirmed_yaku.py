"""Scored legal waits override speculative yaku confidence for call advice."""
import unittest

import advisor
from test_advisor import state, tiles
from test_advisor_actions import offered


def position(snapshot, discard):
    hand = snapshot["hand"].copy()
    hand.remove(discard)
    return advisor._position(hand, snapshot, advisor.unseen_counts(snapshot), discard)


class ConfirmedCallYakuTests(unittest.TestCase):
    def test_toitoi_pon_matches_the_realized_followup(self):
        # Minimal public position from serial 663/664: already two open pons,
        # then call 1s and discard 4s for a scored toitoi single wait on 5s.
        snapshot = offered("888s11s45s", 3, ["1s|1s"], "1s", source=2, players=3)
        snapshot["melds"][0] = [{"type": 1, "tiles": tiles(group)}
                                  for group in ("222p", "777s")]
        snapshot["doras"] = ["7s"]
        snapshot["north"][0] = 1
        snapshot["left"] = 8
        choice = advisor._action_choices(snapshot)[0][0]
        after = advisor._apply_choice(snapshot, choice)
        advice = advisor.advise(snapshot)
        self.assertEqual(advice["status"], "ready")
        hypothetical = next(c for c in advice["candidates"] if c["action"] == "pon")
        realized = position(after, "4s")
        self.assertEqual(hypothetical["followupDiscard"], "4s")
        self.assertEqual(hypothetical["shanten"], 0)
        self.assertTrue(any("Toitoi" in wait["yaku"] for wait in hypothetical["winningTiles"]))
        self.assertGreater(hypothetical["winProbability"], 0)
        self.assertEqual(hypothetical["yakuConfidence"], 1.)
        self.assertNotIn("openNoYakuPenalty", hypothetical["scoreBreakdown"])
        self.assertEqual(hypothetical["score"], realized["score"])
        self.assertEqual(hypothetical["policyComparison"], realized["policyComparison"])
        self.assertFalse(any("缺少可确认役" in reason for reason in hypothetical["reasons"]))

    def test_scored_no_yaku_wait_stays_unlicensed_despite_dora(self):
        snapshot = state("456p789s23s55z9m")
        snapshot["melds"][0] = [{"type": 0, "tiles": tiles("123m")}]
        snapshot["doras"] = ["2s"]
        candidate = position(snapshot, "9m")
        self.assertEqual(candidate["shanten"], 0)
        self.assertEqual(candidate["yakuConfidence"], 0.)
        self.assertEqual(candidate["winProbability"], 0.)
        self.assertTrue(candidate["winningTiles"])
        self.assertTrue(all(wait["ronPoints"] == wait["tsumoPoints"] == 0
                            for wait in candidate["winningTiles"]))
        self.assertNotIn("破坏门清", " ".join(candidate["reasons"]))

    def test_one_shanten_confirmed_yakuhai_keeps_its_license(self):
        snapshot = state("456p78s23s55z1z9m")
        snapshot["melds"][0] = [{"type": 1, "tiles": tiles("666z")}]
        candidate = position(snapshot, "9m")
        self.assertEqual(candidate["shanten"], 1)
        self.assertEqual(candidate["yakuConfidence"], 1.)
        self.assertNotIn("openNoYakuPenalty", candidate["scoreBreakdown"])

    def test_furiten_yaku_wait_retains_tsumo_license(self):
        snapshot = state("888s5s4s", players=3)
        snapshot["melds"][0] = [{"type": 1, "tiles": tiles(group)}
                                  for group in ("222p", "777s", "111s")]
        snapshot["rivers"][0] = [{"tile": "5s"}]
        candidate = position(snapshot, "4s")
        self.assertTrue(candidate["furiten"])
        self.assertEqual(candidate["yakuConfidence"], 1.)
        self.assertTrue(all(wait["ronPoints"] == 0 for wait in candidate["winningTiles"]))
        self.assertTrue(any(wait["tsumoPoints"] > 0 for wait in candidate["winningTiles"]))
        self.assertNotIn("openNoYakuPenalty", candidate["scoreBreakdown"])

    def test_confirmed_yaku_does_not_disappear_when_wall_is_exhausted(self):
        snapshot = state("456p78s23s55z1z9m")
        snapshot["melds"][0] = [{"type": 1, "tiles": tiles("666z")}]
        snapshot["left"] = 0
        candidate = position(snapshot, "9m")
        self.assertEqual(candidate["shanten"], 1)
        self.assertEqual(candidate["winProbability"], 0.)
        self.assertEqual(candidate["yakuConfidence"], 1.)
        self.assertFalse(any("缺少可确认役" in reason for reason in candidate["reasons"]))


if __name__ == "__main__":
    unittest.main()
