"""Riichi wins and forced-discard losses share mutually exclusive survival."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import advisor
from advisor_policy import Outcome
from test_advisor import state, tiles
from test_advisor_actions import get_action, own_action


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
        self.assertAlmostEqual(actual[0], expected[0], places=14)
        self.assertAlmostEqual(actual[1], expected[1], places=10)
        self.assertAlmostEqual(actual[0] * actual[1], expected[0] * expected[1], places=10)
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
        continuation = Outcome(win=.125, income=.125 * 7000, deal=.2, loss=1520,
                               tsumo=.15, tsumo_loss=120, other=.225, other_loss=30,
                               draw=.3, draw_income=450)
        with patch.object(advisor, "_ready_policy", return_value=[continuation]), patch.object(
                advisor, "_danger", return_value=(.2, 1600., [])):
            before = advisor._position(hand, committed, remaining, "1z")
            candidate = advisor._riichi(s, choice, remaining)
        terms = candidate["scoreBreakdown"]
        self.assertEqual(candidate["winProbability"], .1)
        self.assertEqual(candidate["expectedWinPoints"], 7000)
        self.assertEqual(candidate["futureForcedDealInProbability"], .16)
        self.assertEqual(terms["winIncome"], .8 * .125 * 7000)
        self.assertEqual(terms["currentDealInLoss"], -1600)
        self.assertEqual(terms["futureForcedDealInLoss"], -.8 * 1520)
        self.assertEqual(terms["opponentTsumoLoss"], -.8 * 120)
        self.assertEqual(terms["otherRonLiabilityLoss"], -.8 * 30)
        self.assertEqual(terms["exhaustiveDrawPayment"], .8 * 450)
        self.assertAlmostEqual(sum(candidate["terminalProbabilities"].values()), 1., places=14)
        self.assertEqual(candidate["expectedRiichiCost"], 700)
        expected = before["score"] - candidate["expectedRiichiCost"]
        self.assertAlmostEqual(candidate["score"], expected, places=10)
        self.assertEqual(s, original)


class ConfirmedRiichiTests(unittest.TestCase):
    def locked(self, hand="123m123p123s45s77z1z", players=4):
        s = state(hand, players)
        s["riichi"][:2] = [True, True]
        s["riichiStep"][:2] = [10, 20]
        s["rivers"][0] = [{"tile": "9m", "step": 10}]
        s["rivers"][1] = [{"tile": "9p", "step": 20}]
        s.update(left=16, lastDraw=s["hand"][-1], riichiSticks=2,
                 lastAction={"name": "ActionDealTile", "seat": 0,
                             "tile": s["hand"][-1], "step": 40})
        return s

    def test_confirmed_discard_uses_joint_outcomes_without_repaying_stick(self):
        s = self.locked()
        original = deepcopy(s)
        remaining = advisor.unseen_counts(s)
        c = get_action(s, "discard")
        danger, loss, _ = advisor._danger("1z", remaining, advisor._opponents(s, remaining))
        expected = advisor._locked_risk(s, remaining, {**c, "dealInProbability": danger})
        win, points, forced, forced_loss = expected
        self.assertEqual(c["winProbability"], round(win, 4))
        self.assertEqual(c["expectedWinPoints"], round(points))
        self.assertEqual(c["futureForcedDealInProbability"], round(forced, 4))
        self.assertEqual(c["futureForcedDealInLoss"], round(forced_loss))
        self.assertAlmostEqual(c["scoreBreakdown"]["winIncome"], win * points)
        self.assertEqual(c["scoreBreakdown"]["currentDealInLoss"], -loss)
        self.assertAlmostEqual(c["scoreBreakdown"]["futureForcedDealInLoss"], -forced_loss)
        self.assertNotIn("riichiCost", c["scoreBreakdown"])
        self.assertNotIn("expectedRiichiCost", c)
        self.assertEqual(s, original)

    def test_current_discard_and_two_future_draws_absorb_exactly_once(self):
        s = self.locked()
        remaining = advisor.unseen_counts(s)
        danger, loss = .123456, 987.654
        with patch.object(advisor, "_event_survival", return_value=1.), patch.object(
                advisor, "_danger", return_value=(danger, loss, [])), patch.object(
                advisor, "_opportunities", return_value=(0, 0)):
            c = get_action(s, "discard")
        waits = c["winningTiles"]
        hit = sum(w["count"] for w in waits if w["tsumoPoints"]) / sum(remaining)
        income = sum(w["count"] * w["tsumoPoints"] for w in waits) / sum(remaining)
        survived_draw = (1 - hit) * (1 - danger)
        live_draws = (1 - danger) * (1 + survived_draw)
        self.assertEqual(c["winProbability"], round(live_draws * hit, 4))
        self.assertEqual(c["futureForcedDealInProbability"], round(live_draws * (1 - hit) * danger, 4))
        terms = c["scoreBreakdown"]
        self.assertAlmostEqual(terms["winIncome"], live_draws * income)
        self.assertAlmostEqual(terms["futureForcedDealInLoss"], -live_draws * (1 - hit) * loss)
        self.assertEqual(terms["currentDealInLoss"], -loss)
        self.assertAlmostEqual(terms["riskPreferenceAdjustment"], (advisor._risk_weight(s) - 1) *
                               (terms["currentDealInLoss"] + terms["futureForcedDealInLoss"]))
        self.assertAlmostEqual(sum(terms.values()), c["score"])

    def test_known_passed_tile_is_safe_only_for_future_riichi_opponents(self):
        for current in ("5p", "0p"):
            for root in (True, False):
                with self.subTest(current=current, root=root):
                    s = self.locked("123m123p123s45s77z" + current)
                    if not root:
                        s["hand"].remove(current)
                        s["lastDraw"] = None
                        s["rivers"][3] = [{"tile": current, "step": 40}]
                        s["lastAction"] = {"name": "ActionDiscardTile", "seat": 3,
                                           "tile": current, "step": 40}
                    original = deepcopy(s)
                    remaining = advisor.unseen_counts(s)
                    enemies = advisor._opponents(s, remaining)
                    danger = advisor._danger(current, remaining, enemies)[0] if root else 0
                    after = deepcopy(enemies)
                    for enemy in after:
                        if enemy["riichi"]:
                            enemy["safe"].add(advisor.tile_index(current))
                    drawn_remaining = list(remaining)
                    drawn_remaining[advisor.tile_index("5p")] -= 1
                    future, loss, details = advisor._danger("5p", drawn_remaining, after)
                    self.assertGreater(future, 0)  # Non-riichi seat 2 remains dangerous.
                    self.assertEqual(next(d for d in details if d["seat"] == 1)["probability"], 0)
                    c = {"winningTiles": [], "dealInProbability": danger, "tile": current if root else None}
                    with patch.object(advisor, "_draw_pool", return_value=[("5p", 1)]):
                        outcome = advisor._locked_risk(s, remaining, c, opportunities=(0,))
                    self.assertAlmostEqual(outcome[2], (1 - danger) * future / sum(remaining))
                    self.assertAlmostEqual(outcome[3], (1 - danger) * loss / sum(remaining))
                    self.assertEqual(s, original)

    def optional(self, action):
        if action == "ankan":
            # The just-drawn fourth 1m only extends the existing triplet;
            # both paths retain the same 3s/6s waits and decomposition.
            s = self.locked("111m123p123s45s77z1m")
            kind, combination = 4, ["1m|1m|1m|1m"]
        else:
            s = self.locked("123p123s789s45p77z4z", 3)
            kind, combination = 11, []
        s.update(canAct=True, canDiscard=False, operations=[kind],
                 operationDetails=[{"type": kind, "combination": combination}])
        return s

    def test_legal_optional_skip_matches_forced_discard(self):
        for action in ("ankan", "kita"):
            with self.subTest(action=action):
                s = self.optional(action)
                before = deepcopy(s)
                a = advisor.advise(s)
                self.assertEqual({c["action"] for c in a["candidates"]}, {"pass", action})
                skip = next(c for c in a["candidates"] if c["action"] == "pass")
                discard_state = deepcopy(s)
                discard_state.update(canDiscard=True, operations=[1])
                discard = get_action(discard_state, "discard")
                for field in ("winProbability", "expectedWinPoints", "dealInProbability",
                              "futureForcedDealInProbability", "futureForcedDealInLoss", "score", "scoreBreakdown"):
                    self.assertEqual(skip[field], discard[field], field)
                self.assertGreater(skip["futureForcedDealInLoss"], 0)
                self.assertEqual(skip["followupDiscard"], s["lastDraw"])
                self.assertNotIn("expectedRiichiCost", skip)
                self.assertEqual(s, before)

    def test_legal_replacements_keep_child_absorption_and_robbery_survival(self):
        for action in ("ankan", "kita"):
            with self.subTest(action=action):
                s = self.optional(action)
                before = deepcopy(s)
                choice = advisor._action_choices(s)[0][0]
                children = {}
                original_discards = advisor._discards

                def capture(snapshot, remaining, **kwargs):
                    candidates = original_discards(snapshot, remaining, **kwargs)
                    self.assertEqual(len(candidates), 1)
                    children[snapshot["lastDraw"]] = candidates[0]
                    return candidates

                with patch.object(advisor, "_discards", side_effect=capture):
                    c = advisor._replacement(s, choice, advisor.unseen_counts(s))
                outcomes = c["replacementOutcomes"]
                total = sum(o["count"] for o in outcomes)
                rob = (sum(r["probability"] for r in c["opponentRisks"]) if action == "ankan" else
                       advisor._danger("4z", advisor.unseen_counts(s),
                                       advisor._opponents(s, advisor.unseen_counts(s)))[0])
                for field, digits in (("futureForcedDealInProbability", 4), ("futureForcedDealInLoss", 0)):
                    weighted = sum(o["count"] * children[o["draw"]][field]
                                   for o in outcomes if o["draw"] in children) / total
                    self.assertEqual(c[field], round((1 - rob) * weighted, digits))
                    self.assertGreater(c[field], 0)
                self.assertTrue(any(o["draw"] not in children for o in outcomes))
                for o in outcomes:
                    if o["draw"] in children:
                        self.assertEqual(o["followupDiscard"], o["draw"])
                        self.assertEqual(o["winProbability"], children[o["draw"]]["winProbability"])
                    else:
                        self.assertIsNone(o["followupDiscard"])
                        self.assertEqual(o["winProbability"], 1)
                self.assertNotIn("riichiCost", c["scoreBreakdown"])
                self.assertAlmostEqual(sum(c["scoreBreakdown"].values()), c["score"])
                self.assertEqual(s, before)

    def test_fourth_kan_absorbs_locked_children_after_current_discard(self):
        s = self.locked("222m123p45s77z2m")
        s["melds"][0] = [{"type": 3, "tiles": tiles("8888m")}]
        s["melds"][1] = [{"type": 3, "tiles": tiles(t)} for t in ("7777m", "7777p")]
        s.update(canAct=True, canDiscard=False, operations=[4],
                 operationDetails=[{"type": 4, "combination": ["2m|2m|2m|2m"]}])
        c = get_action(s, "ankan")
        self.assertTrue(c["abortAfterDiscard"])
        self.assertGreater(c["winProbability"], 0)
        self.assertGreater(c["dealInProbability"], 0)
        self.assertEqual(c["futureForcedDealInProbability"], 0)
        self.assertEqual(c["futureForcedDealInLoss"], 0)
        self.assertTrue(all(o["winProbability"] in (0, 1) for o in c["replacementOutcomes"]))
        self.assertNotIn("futureForcedDealInLoss", c["scoreBreakdown"])

    def test_locked_waiting_analysis_preserves_actual_next_draw_order(self):
        s = self.locked("123m123p123s45s77z")
        s.update(canDiscard=False, canAct=False, operations=[], lastDraw=None, left=1,
                 lastAction={"name": "ActionDiscardTile", "seat": 3, "tile": "1z", "step": 40})
        s["rivers"][3] = [{"tile": "1z", "step": 40}]
        c = get_action(s, "wait")
        self.assertGreater(c["winProbability"], 0)
        self.assertGreater(c["futureForcedDealInProbability"], 0)
        self.assertEqual(c["dealInProbability"], 0)
        # A last enemy draw still has its discard to come, even at left=0.
        s.update(left=0, lastAction={"name": "ActionDealTile", "seat": 1, "tile": None, "step": 40})
        c = get_action(s, "wait")
        self.assertGreater(c["winProbability"], 0)
        self.assertEqual(c["futureForcedDealInProbability"], 0)
        self.assertEqual(c["futureForcedDealInLoss"], 0)


if __name__ == "__main__":
    unittest.main()
