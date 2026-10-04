"""Public threat evidence and physical exclusions, not fitted probabilities."""
from copy import deepcopy
import unittest

from advisor import TILES, _danger, _opponents, _hand_value, unseen_counts
from test_advisor import state, tiles
from test_advisor_risk_rules import enemy_risk


def public_hand(groups, kinds=None):
    # These unit probes extract public features, not a replayable full history.
    s = state("123m123p123s45s11z9p")
    s["historyComplete"] = False
    kinds = kinds or [1] * len(groups)
    s["melds"][1] = [{"type": kind, "tiles": tiles(group)}
                     for kind, group in zip(kinds, groups)]
    return s


class PublicThreatTests(unittest.TestCase):
    def test_closed_kan_advances_structure_without_becoming_open(self):
        bare = public_hand([])
        closed = public_hand(["5555z"], [3])
        enemy = enemy_risk(closed, "9p")[0]
        self.assertGreater(enemy["tenpai"], enemy_risk(bare, "9p")[0]["tenpai"])
        self.assertEqual(enemy["openMeldCount"], 0)
        self.assertFalse(enemy["canKokushi"])

    def test_yaku_evidence_changes_legal_hit_not_structure(self):
        known = public_hand(["555z"])
        unknown = public_hand(["999m"])
        e1, d1 = enemy_risk(known, "5p")
        e2, d2 = enemy_risk(unknown, "5p")
        self.assertEqual(e1["tenpai"], e2["tenpai"])
        self.assertGreater(d1[0], d2[0])
        self.assertGreater(d2[0], 0)
        self.assertAlmostEqual(d1[0], d1[2][0]["tenpaiProbability"] *
                               d1[2][0]["conditionalRonProbability"], places=4)

    def test_visible_bonus_and_dealer_change_payment_not_tenpai(self):
        s = public_hand(["555z"])
        enemy, ordinary = enemy_risk(s, "9p")
        s["doras"] = ["7z"]
        bonus, danger = enemy_risk(s, "9p")
        self.assertEqual(bonus["tenpai"], enemy["tenpai"])
        self.assertEqual(danger[0], ordinary[0])
        self.assertGreater(danger[1], ordinary[1])
        s["round"]["ju"] = 1
        dealer, dealer_risk = enemy_risk(s, "9p")
        self.assertEqual(dealer["tenpai"], enemy["tenpai"])
        self.assertGreater(dealer_risk[1], danger[1])

    def test_discard_dora_is_in_payment_and_red_retains_same_probability(self):
        s = public_hand(["555z"])
        s["doras"] = ["4p"]
        normal = enemy_risk(s, "5p")[1]
        red = enemy_risk(s, "0p")[1]
        self.assertEqual(normal[2][0]["lossPoints"], 2000)
        self.assertEqual(red[2][0]["lossPoints"], 3900)
        self.assertEqual(normal[0], red[0])

    def test_public_kan_fu_is_a_payment_floor(self):
        pon = public_hand(["555z"])
        kan = public_hand(["5555z"], [2])
        self.assertGreater(enemy_risk(kan, "9p")[1][2][0]["lossPoints"],
                           enemy_risk(pon, "9p")[1][2][0]["lossPoints"])

    def test_flush_is_a_mixture_with_nonzero_off_suit_risk(self):
        s = public_hand(["456p", "789p"], [0, 0])
        before = deepcopy(s)
        same = enemy_risk(s, "5p")[1]
        other = enemy_risk(s, "5m")[1]
        self.assertGreater(same[0], other[0])
        self.assertGreater(other[0], 0)
        self.assertGreater(same[2][0]["lossPoints"], other[2][0]["lossPoints"])
        s["melds"][1].append({"type": 3, "tiles": tiles("9999m")})
        self.assertIsNone(enemy_risk(s, "5p")[0]["flushSuit"])
        self.assertEqual(before["melds"][1], s["melds"][1][:-1])

    def test_four_melds_require_a_possible_tanki_and_ignore_suji(self):
        s = public_hand(["555z", "333p", "666s", "999m"])
        s["rivers"][1] = [{"tile": t} for t in ("2z", "3z")]
        enemy, before = enemy_risk(s, "5p")
        self.assertEqual(enemy["tenpai"], 1)
        self.assertEqual(enemy_risk(s, "3p")[1][:2], (0., 0.))
        s["rivers"][1] = [{"tile": t} for t in ("2p", "8p")]
        self.assertEqual(enemy_risk(s, "5p")[1][0], before[0])
        s["hand"][-1] = "5p"
        s["rivers"][2] = [{"tile": "5p"}] * 3
        self.assertEqual(enemy_risk(s, "5p")[1][:2], (0., 0.))

    def test_four_meld_tanki_probabilities_are_mutually_exclusive(self):
        s = public_hand(["555z", "333p", "666s", "999m"])
        remaining = unseen_counts(s)
        enemy = _opponents(s, remaining)[:1]
        self.assertLessEqual(sum(_danger(t, remaining, enemy)[0] for t in TILES), 1)

    def test_tanki_proves_both_dora_copies_and_single_suit_with_honors(self):
        s = public_hand(["123m", "222z", "333z", "555z"], [0, 1, 1, 1])
        s["doras"] = ["4m"]
        enemy, danger = enemy_risk(s, "5m")
        self.assertEqual(enemy["flushSuit"], 0)
        scoring = {**s, "selfSeat": 1}
        exact = _hand_value(["5m"], "5m", scoring, False)
        self.assertEqual(danger[2][0]["lossPoints"], exact["points"])
        self.assertIn("Honitsu", exact["yaku"])

    def test_tanki_yakuhai_pair_fu_and_sanma_north_payment(self):
        s = public_hand(["555z", "999m", "123p", "456s"], [1, 1, 0, 0])
        self.assertEqual(enemy_risk(s, "2z")[1][2][0]["lossPoints"], 1300)
        s = public_hand(["222p", "777p"])
        s.update(playerCount=3, hand=tiles("123s456s789s11z9m1p9p"))
        enemy, normal = enemy_risk(s, "5p")
        s["north"][1] = 2
        extracted, north = enemy_risk(s, "5p")
        self.assertEqual(extracted["tenpai"], enemy["tenpai"])
        self.assertEqual(extracted["flushSuit"], enemy["flushSuit"])
        self.assertEqual(normal[0], north[0])
        self.assertGreater(north[1], normal[1])

    def test_three_melds_are_not_certain_and_four_without_known_yaku_not_safe(self):
        s = public_hand(["123m", "456p", "789s"], [0, 0, 0])
        self.assertLess(enemy_risk(s, "2z")[0]["tenpai"], 1)
        s["melds"][1].append({"type": 0, "tiles": tiles("456m")})
        s["left"] = 0  # An event yaku may still make this tanki a legal ron.
        self.assertGreater(enemy_risk(s, "2z")[1][0], 0)

    def test_multiple_opponents_preserve_probability_and_payment_accounting(self):
        s = public_hand(["555z"])
        s["melds"][2] = [{"type": 1, "tiles": tiles("666z")}]
        remaining = unseen_counts(s)
        enemies = _opponents(s, remaining)
        total = _danger("5p", remaining, enemies)
        individual = [_danger("5p", remaining, [e]) for e in enemies]
        survival = 1
        for danger in individual:
            survival *= 1 - danger[0]
        self.assertAlmostEqual(total[0], 1 - survival)
        self.assertAlmostEqual(total[1], sum(d[1] for d in individual))
        s["rivers"][1] = [{"tile": "5p"}]
        self.assertEqual(enemy_risk(s, "0p")[1][:2], (0., 0.))


if __name__ == "__main__":
    unittest.main()
