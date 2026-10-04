"""Riichi wins and forced-discard losses share mutually exclusive survival."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import advisor
from test_advisor import state, tiles
from test_advisor_actions import own_action


class LockedRiskTests(unittest.TestCase):
    def setUp(self):
        self.state = state()
        self.state["left"] = 8
        self.remaining = (10,) + (0,) * 33
        self.candidate = {"winningTiles": [], "dealInProbability": 0.}

    def outcomes(self, chance=.1, loss=800., events=None, survival=1.):
        events = advisor._opportunities(self.state, after_discard=True) if events is None else events
        with patch.object(advisor, "_event_survival", return_value=survival), patch.object(
                advisor, "_danger", return_value=(chance, loss, [])), patch.object(
                advisor, "_opportunities", return_value=events):
            return advisor._locked_risk(self.state, self.remaining, self.candidate)

    def test_two_forced_discards_absorb_earlier_deal_in(self):
        probability, points, deal_in, loss = self.outcomes()
        self.assertEqual((probability, points), (0., 0.))
        self.assertAlmostEqual(deal_in, 1 - .9 ** 2)
        self.assertAlmostEqual(loss, 8000 * (1 - .9 ** 2))

    def test_zero_risk_zero_opportunities_and_empty_pool(self):
        self.assertEqual(self.outcomes(chance=0., loss=0.), (0., 0., 0., 0.))
        self.assertEqual(self.outcomes(events=()), (0., 0., 0., 0.))
        self.remaining = (0,) * 34
        self.assertEqual(self.outcomes(), (0., 0., 0., 0.))

    def test_certain_deal_in_terminates_after_first_forced_discard(self):
        probability, points, deal_in, loss = self.outcomes(chance=1., loss=8000.)
        self.assertEqual((probability, points, deal_in, loss), (0., 0., 1., 8000.))

    def test_certain_forced_deal_in_excludes_a_later_ron(self):
        self.candidate["winningTiles"] = [
            {"tile": "1m", "count": 10, "tsumoPoints": 0, "ronPoints": 8000}]
        self.assertEqual(self.outcomes(chance=1., loss=8000., events=(0, 1)),
                         (0., 0., 1., 8000.))

    def test_last_unknown_honor_is_safe_after_drawing_it_against_open_hand(self):
        s = state()
        s["rivers"][2] = [{"tile": "1z"}] * 2
        s["melds"][1] = [{"type": 1, "tiles": tiles("555z")}]
        before = deepcopy(s)
        remaining = advisor.unseen_counts(s)
        self.assertEqual(remaining[advisor.tile_index("1z")], 1)
        enemy = advisor._opponents(s, remaining)[:1]
        self.assertGreater(advisor._danger("1z", remaining, enemy)[0], 0.)
        # Isolate the final unseen honor's physical draw. Once it is in our
        # hand, the open opponent cannot hold a pair or win kokushi on it.
        with patch.object(advisor, "_opponents", return_value=enemy), patch.object(
                advisor, "_draw_pool", return_value=[("1z", 1)]), patch.object(
                advisor, "_opportunities", return_value=(0,)), patch.object(
                advisor, "_event_survival", return_value=1.):
            self.assertEqual(advisor._locked_risk(s, remaining, self.candidate), (0., 0., 0., 0.))
        self.assertEqual(s, before)
        self.assertEqual(remaining, advisor.unseen_counts(s))

    def test_declaration_deal_in_excludes_all_later_outcomes(self):
        for danger in (.2, 1.):
            with self.subTest(danger=danger):
                self.candidate["dealInProbability"] = danger
                _, _, deal_in, loss = self.outcomes()
                self.assertAlmostEqual(deal_in, .19 * (1 - danger))
                self.assertAlmostEqual(loss, 1520 * (1 - danger))

    def test_winning_draw_is_not_discarded_and_later_wins_share_survival(self):
        self.remaining = (2, 8) + (0,) * 32
        self.candidate["winningTiles"] = [
            {"tile": "1m", "count": 2, "tsumoPoints": 4000, "ronPoints": 0}]
        probability, points, deal_in, loss = self.outcomes(events=(0, 0))
        # First draw: win .2, deal in .8*.1, survive .8*.9. The second
        # draw branches only from that survivor, never from a terminal state.
        self.assertAlmostEqual(probability, .2 + .72 * .2)
        self.assertAlmostEqual(points, 4000)
        self.assertAlmostEqual(deal_in, .08 + .72 * .08)
        self.assertAlmostEqual(loss, (.08 + .72 * .08) * 8000)
        self.assertAlmostEqual(probability + deal_in + .72 ** 2, 1.)

    def test_other_endings_apply_once_after_explicit_win_and_deal_in(self):
        _, _, deal_in, loss = self.outcomes(events=(0, 0), survival=.8)
        self.assertAlmostEqual(deal_in, .1 + .9 * .8 * .1)
        self.assertAlmostEqual(loss, 8000 * (.1 + .9 * .8 * .1))
        # Other endings are a conditional residual hazard, never a second
        # deduction of the explicitly modelled forced-discard probability.
        other = .9 * .2 + .9 * .8 * .9 * .2
        self.assertAlmostEqual(deal_in + other + (.9 * .8) ** 2, 1.)

    def test_ron_before_forced_draw_and_value_weights_remain_coupled(self):
        self.remaining = (2, 8) + (0,) * 32
        self.candidate["winningTiles"] = [
            {"tile": "1m", "count": 2, "tsumoPoints": 4000, "ronPoints": 8000}]
        probability, points, deal_in, loss = self.outcomes(events=(0, 1, 0))
        own_first = .2
        ron = .72 * .09
        own_last = .72 * .91 * .2
        self.assertAlmostEqual(probability, own_first + ron + own_last)
        self.assertAlmostEqual(probability * points, (own_first + own_last) * 4000 + ron * 8000)
        self.assertAlmostEqual(deal_in, .08 + .72 * .91 * .08)
        self.assertAlmostEqual(loss, deal_in * 8000)

    def test_zero_risk_preserves_existing_ready_hand_win_model(self):
        self.remaining = (2, 8) + (0,) * 32
        self.candidate["winningTiles"] = [
            {"tile": "1m", "count": 2, "tsumoPoints": 4000, "ronPoints": 8000}]
        events = (1, 2, 3, 0) * 2
        opponents = advisor._opponents(self.state, self.remaining)
        with patch.object(advisor, "_event_survival", return_value=.9):
            expected = advisor._win_model(0, 2, 10, 2, opponents, self.candidate["winningTiles"],
                                          opportunities=events, own_seat=0)
        actual = self.outcomes(chance=0., loss=0., events=events, survival=.9)
        self.assertEqual(actual[:2], expected)
        self.assertEqual(actual[2:], (0., 0.))

    def test_common_horizon_includes_forced_draws_beyond_twelve(self):
        _, _, deal_in, loss = self.outcomes(events=(0,) * 13)
        self.assertAlmostEqual(deal_in, 1 - .9 ** 13)
        self.assertAlmostEqual(loss, 8000 * (1 - .9 ** 13))

    def test_riichi_replaces_future_income_and_charges_loss_once(self):
        s = own_action("123m123p123s45s77z1z", 7, ["1z"])
        original = deepcopy(s)
        remaining = advisor.unseen_counts(s)
        choice = advisor._action_choices(s)[0][0]
        committed = deepcopy(s)
        committed["riichi"][0] = True
        hand = s["hand"].copy()
        hand.remove("1z")
        before = advisor._position(hand, committed, remaining, "1z")
        with patch.object(advisor, "_locked_risk", return_value=(.125, 7000., .2, 1520.)):
            candidate = advisor._riichi(s, choice, remaining)
        terms = candidate["scoreBreakdown"]
        self.assertEqual(candidate["winProbability"], .125)
        self.assertEqual(candidate["expectedWinPoints"], 7000)
        self.assertEqual(candidate["futureForcedDealInProbability"], .2)
        self.assertEqual(terms["winIncome"], .125 * 7000)
        self.assertEqual(terms["futureForcedDealInLoss"], -1520)
        expected = (before["score"] - before["scoreBreakdown"]["winIncome"] + .125 * 7000 -
                    candidate["expectedRiichiCost"] - advisor._risk_weight(s) * 1520)
        self.assertAlmostEqual(candidate["score"], expected, delta=.55)
        self.assertEqual(s, original)


if __name__ == "__main__":
    unittest.main()
