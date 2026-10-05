"""Terminal payer amounts, independent of uncalibrated ending frequencies."""
from copy import deepcopy
import unittest

from advisor import _opponents, unseen_counts
from advisor_settlement import opponent_payments
from test_advisor import state, tiles


def payment_enemy(s):
    return _opponents(s, unseen_counts(s))[0]


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
