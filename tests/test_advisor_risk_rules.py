"""Public rule exclusions and conditional discard payments, not calibration."""
from copy import deepcopy
import unittest

from advisor import _danger, _hand_value, _opponents, unseen_counts, tile_index
from test_advisor import state, tiles


def enemy_risk(s, tile):
    remaining = unseen_counts(s)
    enemy = next(e for e in _opponents(s, remaining) if e["seat"] == 1)
    return enemy, _danger(tile, remaining, [enemy])


def dragons(source=None):
    s = state("123m123p123s45s11z1p")
    s["melds"][1] = [{"type": 1, "tiles": tiles(t)} for t in ("555z", "666z", "777z")]
    if source is not None:
        s["melds"][1][-1]["froms"] = [1, 1, source]
    return s


class ShapeExclusionTests(unittest.TestCase):
    def test_exhausted_sanma_manzu_terminals_are_safe_only_without_kokushi(self):
        for tile in ("1m", "9m"):
            for kind in (1, 3):
                with self.subTest(tile=tile, meld=kind):
                    s = state("123p123s789s45p77z" + tile, 3)
                    s["rivers"][2] = [{"tile": tile}] * 3
                    s["melds"][1] = [{"type": kind, "tiles": tiles("555z" if kind == 1 else "5555z")}]
                    self.assertEqual(unseen_counts(s)[tile_index(tile)], 0)
                    self.assertEqual(enemy_risk(s, tile)[1][:2], (0., 0.))
                    s["melds"][1] = []
                    self.assertGreater(enemy_risk(s, tile)[1][0], 0.)

    def test_unseen_sanma_terminal_can_complete_pair_or_triplet(self):
        s = state("123p123s789s45p77z1m", 3)
        s["melds"][1] = [{"type": 1, "tiles": tiles("555z")}]
        enemy, danger = enemy_risk(s, "1m")
        self.assertAlmostEqual(danger[0], .065 * .75 * enemy["tenpai"])

    def test_four_player_terminals_and_exhausted_suited_tiles_can_complete_sequences(self):
        for tile, players in (("1m", 4), ("9m", 4), ("5p", 3), ("5p", 4)):
            with self.subTest(tile=tile, players=players):
                s = state("123p123s789s46p77z" + tile, players)
                s["rivers"][2] = [{"tile": tile}] * 3
                s["melds"][1] = [{"type": 1, "tiles": tiles("555z")}]
                self.assertEqual(unseen_counts(s)[tile_index(tile)], 0)
                self.assertGreater(enemy_risk(s, tile)[1][0], 0.)


class VisibleYakumanTests(unittest.TestCase):
    def test_daisangen_floor_respects_known_and_unknown_responsibility(self):
        for source, lower, upper in ((0, 32000, 32000), (2, 16000, 16000), (None, 16000, 32000)):
            with self.subTest(source=source):
                s = dragons(source)
                before = deepcopy(s)
                enemy, (probability, loss, details) = enemy_risk(s, "1p")
                self.assertEqual(enemy["loss"], lower)
                self.assertEqual(enemy["yakumanPayment"], {"yaku": ["Daisangen"], "lower": lower, "upper": upper})
                self.assertAlmostEqual(loss, probability * lower)
                self.assertEqual(details[0]["yakumanPayment"], enemy["yakumanPayment"])
                self.assertEqual(s, before)
                scoring = deepcopy(s)
                scoring["selfSeat"] = 1
                value = _hand_value(tiles("123m1p"), "1p", scoring, False)
                self.assertEqual(value["points"], 32000)
                self.assertIn("Daisangen", value["yaku"])

    def test_dealer_sanma_honba_and_existing_sticks(self):
        for players in (3, 4):
            s = dragons(0)
            s.update(playerCount=players, hand=tiles("123p123s789s45p11z1p"), riichiSticks=4)
            s["round"].update(ju=1, ben=2)
            enemy, _ = enemy_risk(s, "1p")
            self.assertEqual(enemy["loss"], 48000 + (players - 1) * 200)
            s["melds"][1][-1]["froms"] = [1, 1, 2]
            enemy, _ = enemy_risk(s, "1p")
            self.assertEqual(enemy["yakumanPayment"]["lower"], 24000)
            self.assertEqual(enemy["yakumanPayment"]["upper"], 24000 + (players - 1) * 200)

    def test_last_concealed_kan_has_no_responsible_feeder(self):
        s = dragons()
        s["melds"][1][-1].update(type=3, tiles=tiles("7777z"), froms=[])
        self.assertEqual(enemy_risk(s, "1p")[0]["loss"], 32000)

    def test_added_kan_retains_original_pon_source(self):
        s = dragons(2)
        s["melds"][1][-1].update(type=2, tiles=tiles("7777z"))
        self.assertEqual(enemy_risk(s, "1p")[0]["loss"], 16000)

    def test_daisuushii_is_double_and_four_kans_add_without_pao(self):
        s = state("123m123p123s45s66p1p")
        s["melds"][1] = [{"type": 1, "tiles": tiles(t)} for t in ("111z", "222z", "333z", "444z")]
        s["melds"][1][-1]["froms"] = [1, 1, 2]
        enemy, _ = enemy_risk(s, "1p")
        self.assertEqual(enemy["loss"], 32000)  # Half of double yakuman.
        self.assertEqual(enemy["yakumanPayment"]["yaku"], ["Daisuushii"])
        for meld in s["melds"][1]:
            meld["type"] = 2
            meld["tiles"].append(meld["tiles"][0])
        enemy, _ = enemy_risk(s, "1p")
        self.assertEqual(enemy["loss"], 64000)  # Half of two, plus one in full.
        self.assertEqual(enemy["yakumanPayment"]["yaku"], ["Daisuushii", "Suukantsu"])

    def test_two_dragons_do_not_prove_yakuman_and_genbutsu_remains_safe(self):
        s = dragons(0)
        s["melds"][1].pop()
        self.assertIsNone(enemy_risk(s, "1p")[0]["yakumanPayment"])
        s = dragons(0)
        s["rivers"][1] = [{"tile": "1p"}]
        self.assertEqual(enemy_risk(s, "1p")[1][:2], (0., 0.))


class RedDiscardPaymentTests(unittest.TestCase):
    def test_red_payment_uses_han_fu_and_caps_with_unchanged_shape_probability(self):
        # Existing ordinary-hand estimate, plus one known aka han on ron.
        cases = ((False, 0, 1000, 2000), (True, 0, 5200, 8000),
                 (True, 1, 8000, 8000), (True, 2, 8000, 12000),
                 (True, 3, 12000, 12000), (True, 4, 12000, 16000))
        for riichi, north, plain, red in cases:
            with self.subTest(riichi=riichi, north=north):
                s = state("123p123s789s45p77z1m", 3)
                s["riichi"][1] = riichi
                s["north"][1] = north
                if not riichi:
                    s["melds"][1] = [{"type": 1, "tiles": tiles("555z")}]
                _, normal = enemy_risk(s, "5p")
                _, aka = enemy_risk(s, "0p")
                self.assertEqual(normal[0], aka[0])
                self.assertEqual(normal[2][0]["lossPoints"], plain)
                self.assertEqual(aka[2][0]["lossPoints"], red)
                self.assertAlmostEqual(aka[1], aka[0] * red)

    def test_red_does_not_increase_true_yakuman_or_make_genbutsu_dangerous(self):
        s = dragons(2)
        self.assertEqual(enemy_risk(s, "0p")[1], enemy_risk(s, "5p")[1])
        s["rivers"][1] = [{"tile": "5p"}]
        self.assertEqual(enemy_risk(s, "0p")[1][:2], (0., 0.))

    def test_counted_yakuman_caps_the_extra_red_han(self):
        s = state("123p123s789s45p11z1m", 3)
        s["riichi"][1] = True
        s["melds"][1] = [{"type": 3, "tiles": tiles("5555z")}]
        s["doras"] = ["7z"] * 3
        enemy, _ = enemy_risk(s, "0p")
        self.assertIsNone(enemy["yakumanPayment"])
        self.assertEqual((enemy["loss"], enemy["redLoss"]), (32000, 32000))


if __name__ == "__main__":
    unittest.main()
