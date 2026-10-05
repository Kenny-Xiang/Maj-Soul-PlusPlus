"""Terminal payer amounts, independent of uncalibrated ending frequencies."""
from copy import deepcopy
import unittest

from advisor import (HandCalculator, _config, _opponents, _policy_environment,
                     _position, _scoring_tiles, unseen_counts)
from advisor_settlement import opponent_payments
from test_advisor import state, tiles


def payment_enemy(s):
    return _opponents(s, unseen_counts(s))[0]


def four_pon_state(players=4):
    s = state("123p456p789s45s11z9p", players)
    groups = ("222p", "444p", "666s", "888s") if players == 3 else ("222m", "444p", "666s", "888m")
    s["melds"][1] = [{"type": 1, "tiles": tiles(group)} for group in groups]
    s["lastDraw"] = "9p"
    return s


def yakuman_state(source=0, players=4, winds=False, kans=False):
    s = state("123p456p789s22m5s6s7s", players)
    if players == 3:
        s["hand"] = tiles("123p456p789s22p5s6s7s")
    groups = ("111z", "222z", "333z", "444z") if winds else ("555z", "666z", "777z")
    s["melds"][1] = [{"type": 2 if kans else 1, "tiles": tiles(group + (group[0] + "z" if kans else ""))}
                      for group in groups]
    if source is not None:
        s["melds"][1][-1]["froms"] = [1, 1, source]
    return s


class OpponentPaymentTests(unittest.TestCase):
    def test_four_public_pons_preserve_toitoi_and_tsumo_fu_for_every_payer(self):
        for players in (3, 4):
            for dealer, payment in ((0, 1300), (1, 1300), (2, 700)):
                for honba in (0, 2):
                    with self.subTest(players=players, dealer=dealer, honba=honba):
                        s = four_pon_state(players)
                        s["round"].update(ju=dealer, ben=honba)
                        s["riichiSticks"] = 9
                        enemy = payment_enemy(s)
                        before, config = deepcopy(s), vars(enemy["config"]).copy()
                        # The hidden singleton is unknown to the estimator.
                        # A feasible 9p tanki supplies an independent exact score.
                        scoring = {**s, "selfSeat": 1}
                        ids, winning, melds, _ = _scoring_tiles(["9p", "9p"], s["melds"][1])
                        value = HandCalculator.estimate_hand_value(
                            ids, winning, melds=melds, config=_config(scoring, True))
                        self.assertIsNone(value.error)
                        self.assertEqual((value.han, value.fu), (2, 40))
                        cost = "main" if dealer == 0 else "additional"
                        self.assertEqual(value.cost[cost], payment)
                        self.assertEqual(opponent_payments(s, enemy), (payment + honba * 100, 0))
                        self.assertEqual(s, before)
                        self.assertEqual(vars(enemy["config"]), config)

    def test_public_toitoi_adds_to_yakuhai_and_preserves_visible_bonuses(self):
        for doras, north, expected in (([], 0, 2600), (["7z"], 0, 6000),
                                        ([], 1, 4000), (["3z"], 1, 4000)):
            with self.subTest(doras=doras, north=north):
                s = four_pon_state(3)
                s["melds"][1][-1]["tiles"] = tiles("555z")
                s["doras"], s["north"][1] = doras, north
                self.assertEqual(opponent_payments(s, payment_enemy(s)), (expected, 0))
        s = four_pon_state(3)
        s["melds"][1][-1]["tiles"] = tiles("055p")
        self.assertEqual(opponent_payments(s, payment_enemy(s)), (2600, 0))

    def test_tsumo_replaces_closed_ron_fu_and_keeps_the_riichi_prior(self):
        for riichi, expected in ((False, 500), (True, 2000)):
            with self.subTest(riichi=riichi):
                s = state("123p456p789s22p5s6s7s")
                s["riichi"][1] = riichi
                # Riichi's existing three-han estimate already exceeds its
                # known riichi + menzen-tsumo floor; do not add a fourth han.
                self.assertEqual(opponent_payments(s, payment_enemy(s)), (expected, 0))
        s["riichi"][1] = False
        s["melds"][1] = [{"type": 3, "tiles": tiles("5555z")}]
        # Public dragon kan + menzen tsumo: at least two han and 60 fu.
        self.assertEqual(opponent_payments(s, payment_enemy(s)), (2000, 0))

    def test_four_sequences_do_not_invent_tanyao_or_a_flush_for_the_unknown_pair(self):
        s = state("123s456s789s11z9m9p1p")
        s["melds"][1] = [{"type": 0, "tiles": tiles(group)}
                          for group in ("234p", "234p", "678p", "678p")]
        self.assertEqual(opponent_payments(s, payment_enemy(s)), (500, 0))

    def test_double_riichi_preserves_its_extra_known_han_with_a_value_kan(self):
        for double, han, expected in ((False, 3, 3900), (True, 4, 4000)):
            with self.subTest(double_riichi=double):
                s = state("123p456p789s22p5s6s7s")
                s["riichi"][1] = True
                s["doubleRiichi"] = [False, double, False, False]
                s["melds"][1] = [{"type": 3, "tiles": tiles("5555z")}]
                ids, winning, melds, _ = _scoring_tiles(tiles("123m456p789s99p"), s["melds"][1])
                value = HandCalculator.estimate_hand_value(
                    ids, winning, melds=melds, config=_config(s, True, seat=1))
                self.assertIsNone(value.error)
                self.assertEqual((value.han, value.fu), (han, 60))
                self.assertEqual(value.cost["main"], expected)
                self.assertEqual(opponent_payments(s, payment_enemy(s)), (expected, 0))

    def test_four_honor_groups_keep_a_honitsu_floor_without_guessing_the_pair(self):
        s = state("123p456p789s22p5s6s7s")
        s["round"]["chang"] = 1
        s["melds"][1] = [{"type": 1, "tiles": tiles(group)}
                          for group in ("111z", "222z", "333z", "555z")]
        enemy = payment_enemy(s)
        # Every suited pair guarantees honitsu; an honor pair makes the
        # whole hand yakuman. Neither concealed pair is given to the model.
        for pair in ("5m", "5p", "5s", "6z"):
            with self.subTest(pair=pair):
                ids, winning, melds, _ = _scoring_tiles([pair, pair], s["melds"][1])
                value = HandCalculator.estimate_hand_value(
                    ids, winning, melds=melds, config=_config(s, True, seat=1))
                self.assertIsNone(value.error)
                if pair == "6z":
                    self.assertEqual(value.cost["main"], 16000)
                else:
                    self.assertEqual((value.han, value.fu), (7, 40))
                    self.assertEqual(value.cost["main"], 6000)
        self.assertIsNone(enemy["yakumanPayment"])
        self.assertEqual(opponent_payments(s, enemy), (6000, 0))

    def test_public_payment_reaches_policy_environment_and_terminal_loss(self):
        s = four_pon_state()
        s["left"] = 3
        before = deepcopy(s)
        remaining = unseen_counts(s)
        opponents = _opponents(s, remaining)
        expected = (1300 + 500 * sum(o["tenpai"] for o in opponents[1:])) / sum(o["tenpai"] for o in opponents)
        self.assertAlmostEqual(_policy_environment(s, opponents)[1][0], expected)
        hand = s["hand"].copy()
        hand.remove("9p")
        candidate = _position(hand, s, remaining, "9p")
        loss = candidate["terminalProbabilities"]["opponentTsumo"] * expected
        self.assertGreater(loss, 0)
        self.assertAlmostEqual(candidate["expectedOpponentTsumoLoss"], loss, delta=.00051)
        self.assertAlmostEqual(candidate["scoreBreakdown"]["opponentTsumoLoss"], -loss)
        self.assertEqual(s, before)

    def test_ordinary_tsumo_respects_our_dealer_seat_honba_and_excludes_sticks(self):
        for players in (3, 4):
            for dealer, expected in ((0, 4200), (1, 4200), (2, 2200)):
                with self.subTest(players=players, dealer=dealer):
                    s = state("123p456p789s22p5s6s7s", players)
                    s["round"].update(ju=dealer, ben=2)
                    s["riichiSticks"] = 9
                    enemy = payment_enemy(s)
                    enemy.update(han=5, fu=30)
                    before = deepcopy(s)
                    config = vars(enemy["config"]).copy()
                    self.assertEqual(opponent_payments(s, enemy), (expected, 0))
                    self.assertEqual(s, before)
                    self.assertEqual(vars(enemy["config"]), config)

    def test_own_responsibility_costs_on_both_tsumo_and_other_ron(self):
        for players, tsumo in ((3, 24000), (4, 32000)):
            s = yakuman_state(players=players)
            self.assertEqual(opponent_payments(s, payment_enemy(s)), (tsumo, 16000))
            s["round"]["ju"] = 1
            self.assertEqual(opponent_payments(s, payment_enemy(s)), (tsumo * 1.5 if players == 4 else 32000, 24000))

    def test_other_feeder_and_missing_source_have_zero_component_lower_bound(self):
        for source in (2, None):
            s = yakuman_state(source=source)
            self.assertEqual(opponent_payments(s, payment_enemy(s)), (0, 0))

    def test_final_concealed_kan_has_no_responsible_feeder(self):
        s = yakuman_state()
        s["melds"][1][-1].update(type=3, tiles=tiles("7777z"), froms=[])
        s["round"]["ben"] = 2
        self.assertEqual(opponent_payments(s, payment_enemy(s)), (16200, 0))

    def test_added_kan_keeps_original_pon_responsibility(self):
        s = yakuman_state()
        s["melds"][1][-1].update(type=2, tiles=tiles("7777z"))
        self.assertEqual(opponent_payments(s, payment_enemy(s)), (32000, 16000))

    def test_double_winds_and_four_kans_settle_components_separately(self):
        s = yakuman_state(winds=True, kans=True)
        self.assertEqual(opponent_payments(s, payment_enemy(s)), (80000, 32000))
        s["melds"][1][-1]["froms"] = [1, 1, 2]
        self.assertEqual(opponent_payments(s, payment_enemy(s)), (16000, 0))
        # Four concealed kans have no feeder and pay each public component
        # normally, with honba applied once rather than once per yakuman.
        for meld in s["melds"][1]:
            meld.update(type=3, froms=[])
        s["round"]["ben"] = 2
        self.assertEqual(opponent_payments(s, payment_enemy(s)), (48200, 0))

    def test_liability_honba_is_explicitly_a_floor_until_rule_contract_is_known(self):
        s = yakuman_state()
        s["round"]["ben"] = 3
        s["riichiSticks"] = 6
        self.assertEqual(opponent_payments(s, payment_enemy(s)), (32000, 16000))


if __name__ == "__main__":
    unittest.main()
