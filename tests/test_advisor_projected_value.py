"""Projected win eligibility and receipts must describe the same win event.

Draft for the actor-specific projection API. No recorded discard is an oracle.
"""
from copy import deepcopy
import unittest
from unittest.mock import patch

import advisor
from test_advisor import state, tiles


class ProjectedValueTests(unittest.TestCase):
    def projection(self, snapshot, *, tsumo=False):
        hand = snapshot["hand"]
        args = (hand, snapshot, advisor.counts34(hand),
                not snapshot["melds"][snapshot["selfSeat"]])
        return advisor._future_value(*args, tsumo=True) if tsumo else advisor._future_value(*args)

    def assert_mass(self, result):
        self.assertAlmostEqual(result.win + result.deal + result.tsumo + result.other + result.draw, 1.)

    def test_closed_only_tsumo_route_does_not_license_projected_ron(self):
        s = state("123456p78s12s55z1z", players=3)
        original = deepcopy(s)
        ron = self.projection(s)
        self.assertEqual(ron[1], 0)
        tsumo = self.projection(s, tsumo=True)
        self.assertEqual(tsumo[1], 1)
        self.assertGreater(tsumo[0], 0)
        self.assertEqual(s, original)

    def test_dora_and_nuki_alone_do_not_create_ron_yaku(self):
        s = state("123456p78s12s55z1z", players=3)
        plain = self.projection(s, tsumo=True)[0]
        s["doras"] = ["4z"]  # Two white-dragon dora; neither is a yaku triplet.
        s["north"][0] = 1
        self.assertEqual(self.projection(s)[1], 0)
        self.assertEqual(self.projection(s, tsumo=True)[1], 1)
        self.assertGreater(self.projection(s, tsumo=True)[0], plain)

    def test_known_yakuhai_enables_ron_and_tsumo_adds_menzen_han(self):
        s = state("666z123p459p78s12s", players=3)
        ron, tsumo = self.projection(s), self.projection(s, tsumo=True)
        self.assertEqual(ron, (1500, 1.))
        self.assertEqual(tsumo, (2000, 1.))
        # The same projected triplet remains a yaku when the hand is open,
        # but an open self-draw cannot receive the extra menzen-tsumo han.
        s["hand"] = tiles("123p459p78s12s")
        s["melds"][0] = [{"type": 1, "tiles": tiles("666z")}]
        self.assertEqual(self.projection(s), (1500, 1.))
        self.assertEqual(self.projection(s, tsumo=True), (1000, 1.))

    def test_unknown_open_yaku_keeps_existing_prior_in_both_win_modes(self):
        s = state("459p78s12s55z1z", players=3)
        s["melds"][0] = [{"type": 0, "tiles": tiles("123p")}]
        self.assertEqual(self.projection(s)[1], .3)
        self.assertEqual(self.projection(s, tsumo=True)[1], .3)

    def test_projected_seven_pairs_keeps_ron_eligibility(self):
        s = state("11p22p44p66s88s55z1z", players=3)
        self.assertEqual(self.projection(s)[1], 1.)
        self.assertEqual(self.projection(s, tsumo=True)[1], 1.)

    def test_sanma_tsumo_uses_two_actual_payees_for_dealer_and_child(self):
        for seat, four_payment, three_payment in ((0, 1500, 1000), (1, 1100, 800)):
            with self.subTest(seat=seat):
                s = state("123456p78s12s55z1z", players=4)
                s["selfSeat"] = seat
                self.assertEqual(self.projection(s, tsumo=True), (four_payment, 1.))
                s["playerCount"] = 3
                self.assertEqual(self.projection(s, tsumo=True), (three_payment, 1.))

    def coarse(self, s, events, *, ron=(0., 0.)):
        remaining = advisor.unseen_counts(s)
        with patch.object(advisor, "_policy_risks", return_value=([], [], (0., 0.))), patch.object(
                advisor, "_policy_environment", return_value=(1., (0., 0.), (0., 0.))):
            # Start at the abstract ready stage to isolate eligibility from
            # unrelated progress assumptions. Own self-draw pays 1000 points.
            return advisor._coarse_policy(s["hand"], s, remaining, [], events,
                                           0, 6, 1000., 1., ron=ron)

    def test_opponent_events_cannot_create_a_tsumo_only_win(self):
        s = state("123456p78s12s55z1z", players=3)
        enemy_only = self.coarse(s, (1, 2, 1, 2))
        one_draw = self.coarse(s, (0,))
        with_enemies = self.coarse(s, (1, 2, 0, 1, 2))
        self.assertEqual(enemy_only.win, 0)
        self.assertEqual(enemy_only.income, 0)
        self.assertGreater(one_draw.win, 0)
        self.assertEqual(with_enemies, one_draw)
        self.assertAlmostEqual(one_draw.income / one_draw.win, 1000)
        for result in (enemy_only, one_draw, with_enemies):
            self.assert_mass(result)

    def test_coarse_ron_uses_its_own_projected_receipts(self):
        s = state("123456p78s12s55z1z", players=3)
        ron = self.coarse(s, (1,), ron=(1500., 1.))
        tsumo = self.coarse(s, (0,), ron=(1500., 1.))
        self.assertGreater(ron.win, 0)
        self.assertAlmostEqual(ron.income / ron.win, 1500)
        self.assertAlmostEqual(tsumo.income / tsumo.win, 1000)
        self.assert_mass(ron)
        self.assert_mass(tsumo)

    def test_legacy_coarse_call_keeps_uniform_projection_contract(self):
        s = state("123456p78s12s55z1z", players=3)
        remaining = advisor.unseen_counts(s)
        with patch.object(advisor, "_policy_risks", return_value=([], [], (0., 0.))), patch.object(
                advisor, "_policy_environment", return_value=(1., (0., 0.), (0., 0.))):
            legacy = advisor._coarse_policy(s["hand"], s, remaining, [], (1, 0), 0, 6, 1000., 1.)
            explicit = advisor._coarse_policy(s["hand"], s, remaining, [], (1, 0), 0, 6, 1000., 1., ron=(1000., 1.))
        self.assertEqual(legacy, explicit)
        self.assert_mass(legacy)

    def test_kokushi_actor_specific_payment_does_not_change_probability_tree(self):
        s = state("119m19p19s123456z", players=3)
        counts, remaining = advisor.counts34(s["hand"]), advisor.unseen_counts(s)
        ron_value = self.projection(s)[0]
        tsumo_value = self.projection(s, tsumo=True)[0]
        self.assertEqual(ron_value, 48000)
        self.assertEqual(tsumo_value, 32000)
        with patch.object(advisor, "_policy_risks", return_value=([], [], (0., 0.))), patch.object(
                advisor, "_policy_environment", return_value=(1., (0., 0.), (0., 0.))):
            for actor in (0, 1):
                with self.subTest(actor=actor):
                    legacy = advisor._kokushi_outcome(counts, remaining, [], s, None, (actor,), ron_value)
                    specific = advisor._kokushi_outcome(counts, remaining, [], s, None, (actor,),
                                                        ron_value, tsumo_value=tsumo_value)
                    self.assertGreater(specific.win, 0)
                    self.assertEqual(legacy.win, specific.win)
                    self.assertEqual(legacy.deal, specific.deal)
                    self.assertEqual(legacy.draw, specific.draw)
                    self.assertAlmostEqual(specific.income / specific.win, tsumo_value if actor == 0 else ron_value)
                    self.assert_mass(specific)


if __name__ == "__main__":
    unittest.main()
