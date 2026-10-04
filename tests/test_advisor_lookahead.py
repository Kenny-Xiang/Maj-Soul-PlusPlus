"""Complete one-shanten branches preserve rules, time, and weighted value."""
from copy import deepcopy
from itertools import permutations
import unittest
from unittest.mock import patch

import advisor
from test_advisor import state, tiles


def branches_for(snapshot, discard=None):
    hand = snapshot["hand"].copy()
    if discard is not None:
        hand.remove(discard)
    counts = advisor.counts34(hand)
    remaining = advisor.unseen_counts(snapshot)
    special = not snapshot["melds"][snapshot["selfSeat"]]
    improvements = advisor._improvements(counts, remaining, special)
    branches = advisor._one_shanten_branches(
        hand, counts, improvements, remaining, snapshot, discard, special)
    return branches, remaining


def option_for(branches, draw, discard):
    branch = next(b for b in branches if b["draw"] == draw)
    return next(o for o in branch["options"] if o["discard"] == discard)


class OneShantenBranchTests(unittest.TestCase):
    def test_direct_no_yaku_routes_remain_tsumo_only(self):
        s = state("123456m78p12s55z1z")
        branches, remaining = branches_for(s)
        self.assertEqual({b["draw"] for b in branches}, {"6p", "9p", "3s"})
        for draw in ("6p", "9p", "3s"):
            with self.subTest(draw=draw):
                waits = option_for(branches, draw, "1z")["waits"]
                self.assertTrue(waits)
                self.assertTrue(all(w["ronPoints"] == 0 for w in waits))
                self.assertTrue(all(w["tsumoPoints"] > 0 for w in waits))
        opponents = advisor._opponents(s, remaining)
        for events in ((), (1, 2, 3), (0,), (0, 1, 2, 3), (1, 2, 3, 0)):
            with self.subTest(events=events):
                self.assertEqual(advisor._one_shanten_model(
                    branches, sum(remaining), opponents, events, s)[:2], (0, 0))
        probability, points, _, _ = advisor._one_shanten_model(
            branches, sum(remaining), opponents, (0, 1, 2, 3, 0), s)
        self.assertGreater(probability, 0)
        self.assertGreater(points, 0)

    def test_root_discard_and_exhausted_river_waits_still_cause_furiten(self):
        s = state("123456m78p12s55z1z6p")
        branches, _ = branches_for(s, "6p")
        option = option_for(branches, "3s", "1z")
        self.assertTrue(option["furiten"])
        self.assertEqual({w["tile"] for w in option["waits"]}, {"6p", "9p"})
        self.assertTrue(all(w["ronPoints"] == 0 for w in option["waits"]))

        s = state("123456m78p12s55z1z")
        s["rivers"][0] = [{"tile": "3s"}]
        s["rivers"][1] = [{"tile": "3s"}] * 3
        branches, _ = branches_for(s)
        option = option_for(branches, "6p", "1z")
        self.assertTrue(option["furiten"])
        self.assertEqual(next(w["count"] for w in option["waits"] if w["tile"] == "3s"), 0)
        self.assertTrue(all(w["ronPoints"] == 0 for w in option["waits"]))

    def test_future_normal_draw_clears_temporary_furiten_and_old_kuikae(self):
        s = state("123m123p678s55z5p1z")
        s.update(lastDraw=None, furiten=True, forbiddenDiscards=["1z"])
        before = deepcopy(s)
        branches, _ = branches_for(s)
        option = option_for(branches, "5p", "1z")
        self.assertFalse(option["furiten"])
        self.assertTrue(any(w["ronPoints"] > 0 for w in option["waits"]))
        self.assertEqual(s, before)

    def test_kokushi_branch_distinguishes_thirteen_sided_double_yakuman(self):
        s = state("119m19p19s123456z2p")
        branches, _ = branches_for(s, "1m")
        thirteen = option_for(branches, "7z", "2p")
        self.assertEqual({advisor.tile_index(w["tile"]) for w in thirteen["waits"]},
                         set(advisor.ORPHANS))
        self.assertTrue(thirteen["furiten"])
        self.assertTrue(all(w["ronPoints"] == 0 for w in thirteen["waits"]))
        self.assertTrue(all(w["tsumoPoints"] == 96000 for w in thirteen["waits"]))

        ordinary = option_for(branches, "1m", "2p")
        self.assertFalse(ordinary["furiten"])
        self.assertEqual([w["tile"] for w in ordinary["waits"]], ["7z"])
        self.assertEqual(ordinary["waits"][0]["ronPoints"], 48000)
        self.assertEqual(ordinary["waits"][0]["tsumoPoints"], 48000)

    def test_red_draws_are_distinct_and_cannot_create_another_red_copy(self):
        s = state("123m123p678s55z5p1z7z")
        before = deepcopy(s)
        branches, remaining = branches_for(s, "7z")
        red = next(b for b in branches if b["draw"] == "0p")
        normal = next(b for b in branches if b["draw"] == "5p")
        self.assertEqual((red["count"], normal["count"]), (1, 2))
        for branch in (red, normal):
            self.assertEqual(sum(branch["remaining"]), sum(remaining) - 1)
            self.assertEqual(branch["remaining"][advisor.tile_index("5p")], 2)
        red_wait = next(w for w in option_for(branches, "0p", "1z")["waits"] if w["tile"] == "5p")
        normal_wait = next(w for w in option_for(branches, "5p", "1z")["waits"] if w["tile"] == "5p")
        self.assertEqual(red_wait["redCount"], 0)
        self.assertEqual(normal_wait["redCount"], 1)
        self.assertGreater(red_wait["normalTsumoPoints"], normal_wait["normalTsumoPoints"])
        self.assertEqual(s, before)

        s = state("123m123p678s55z5p1z0p")
        branches, _ = branches_for(s, "0p")
        self.assertNotIn("0p", {b["draw"] for b in branches})
        wait = next(w for w in option_for(branches, "5z", "1z")["waits"] if w["tile"] == "5p")
        self.assertEqual(wait["redCount"], 0)

    def test_every_future_wait_is_an_original_effective_family(self):
        # Swapping the two winning additions leaves the same final hand.
        # Thus a non-effective tsumogiri cannot introduce branch wait furiten.
        cases = [("123456m78p12s55z1z", None),
                 ("11m22m33p44p66s5p12z", None),
                 ("119m19p19s12345z2p", None),
                 ("123p678s55z5p1z", {"type": 1, "tiles": tiles("111m")})]
        for hand, meld in cases:
            with self.subTest(hand=hand):
                s = state(hand)
                if meld:
                    s["melds"][0] = [meld]
                special = meld is None
                self.assertEqual(advisor.shanten(advisor.counts34(s["hand"]), special), 1)
                branches, remaining = branches_for(s)
                effective = {advisor.tile_index(b["draw"]) for b in branches}
                self.assertTrue(branches)
                for branch in branches:
                    for option in branch["options"]:
                        for wait in option["waits"]:
                            family = advisor.tile_index(wait["tile"])
                            if remaining[family]:
                                self.assertIn(family, effective)
                            self.assertNotEqual(family, advisor.tile_index(option["discard"]))


class OneShantenProbabilityTests(unittest.TestCase):
    def setUp(self):
        self.opponents = [{"seat": i, "tenpai": 0.} for i in (1, 2, 3)]

    def test_branch_value_uses_winning_mass_and_equal_values_remain_equal(self):
        # Each draw can wait on the other family, with different win values.
        pool = [1, 3, 4, 4, 4, 4] + [0] * 28
        branches = []
        for index, count, wait_index, value in ((0, 1, 1, 1000), (1, 3, 0, 8000)):
            remaining = pool.copy()
            remaining[index] -= 1
            branches.append({"draw": advisor.TILES[index], "count": count,
                             "remaining": tuple(remaining), "options": [{
                                 "discard": "7z", "furiten": False, "dealInProbability": 0.,
                                 "expectedDealInLoss": 0., "waits": [{
                                     "tile": advisor.TILES[wait_index], "count": remaining[wait_index],
                                     "ronPoints": value, "tsumoPoints": value}]}]})
        probability, value, _, _ = advisor._one_shanten_model(branches, sum(pool), self.opponents, (0, 1), state())
        weights = [b["count"] * b["options"][0]["waits"][0]["count"] for b in branches]
        expected = sum(w * b["options"][0]["waits"][0]["ronPoints"]
                       for w, b in zip(weights, branches)) / sum(weights)
        self.assertGreater(probability, 0)
        self.assertLessEqual(probability, 1)
        self.assertAlmostEqual(value, expected)
        for branch in branches:
            branch["options"][0]["waits"][0].update(ronPoints=12000, tsumoPoints=12000)
        _, value, _, _ = advisor._one_shanten_model(branches, sum(pool), self.opponents, (0, 1), state())
        self.assertAlmostEqual(value, 12000)

    def test_miss_mass_matches_without_replacement_first_arrivals(self):
        # Isolate first arrival: a ready position wins on its next own draw.
        # Enumerating physical urn orders independently supplies the reference.
        branches = [{"draw": "1m", "count": 2, "remaining": (1, 2) + (0,) * 32,
                     "options": [{"discard": "7z", "furiten": False,
                                  "dealInProbability": 0., "expectedDealInLoss": 0.,
                                  "waits": [{"tile": "1m", "count": 1,
                                             "ronPoints": 0, "tsumoPoints": 1000}]}]}]

        def ready_win(*args, opportunities=(), own_seat=0, **kwargs):
            return (1., 1000.) if own_seat in opportunities else (0., 0.)

        orders = list(permutations(range(4)))
        expected = sum(any(tile < 2 for tile in order[:2]) for order in orders) / len(orders)
        with patch.object(advisor, "_event_survival", return_value=1.), patch.object(
                advisor, "_win_model", side_effect=ready_win):
            probability, value, _, _ = advisor._one_shanten_model(branches, 4, self.opponents, (0, 0, 0), state())
        self.assertAlmostEqual(probability, expected)
        self.assertAlmostEqual(value, 1000)

    def test_enumeration_order_does_not_change_probability_or_value(self):
        s = state("123m123p678s55z5p1z7z")
        branches, remaining = branches_for(s, "7z")
        events = (1, 2, 3, 0) * 4
        expected = advisor._one_shanten_model(branches, sum(remaining), self.opponents, events, s)
        reversed_branches = deepcopy(branches[::-1])
        for branch in reversed_branches:
            branch["options"].reverse()
            for option in branch["options"]:
                option["waits"].reverse()
        actual = advisor._one_shanten_model(reversed_branches, sum(remaining), self.opponents, events, s)
        for first, second in zip(expected, actual):
            self.assertAlmostEqual(first, second)

        s["hand"].reverse()
        permuted, _ = branches_for(s, "7z")
        actual = advisor._one_shanten_model(permuted, sum(remaining), self.opponents, events, s)
        for first, second in zip(expected, actual):
            self.assertAlmostEqual(first, second)

    def test_every_one_shanten_discard_uses_full_branch_precision(self):
        s = state()
        result = advisor.advise(s)
        self.assertEqual(result["status"], "ready")
        candidates = [c for c in result["candidates"] if c["action"] == "discard" and c["shanten"] == 1]
        self.assertGreater(len(candidates), 3)
        remaining = advisor.unseen_counts(s)
        opponents = advisor._opponents(s, remaining)
        events = advisor._opportunities(s, after_discard=True)
        for candidate in candidates:
            with self.subTest(discard=candidate["tile"]):
                branches, _ = branches_for(s, candidate["tile"])
                probability, value, _, _ = advisor._one_shanten_model(branches, sum(remaining), opponents, events, s)
                danger = advisor._danger(candidate["tile"], remaining, opponents)[0]
                self.assertEqual(candidate["winProbability"], round(probability * (1 - danger), 4))
                self.assertEqual(candidate["expectedWinPoints"], round(value))


class OneShantenRiskTests(unittest.TestCase):
    def test_followup_agrees_with_expanded_window_under_riichi_pressure(self):
        s = state("2345667m34568p44s")
        s["riichi"][1] = True
        s["riichiStep"][1] = 20
        s["rivers"][1] = [{"tile": "3p", "step": 20}]
        branches, _ = branches_for(s, "8p")
        branch = next(b for b in branches if b["draw"] == "4s")
        expanded = deepcopy(s)
        expanded["hand"].remove("8p")
        expanded["hand"].append("4s")
        expanded["rivers"][0].append({"tile": "8p"})
        expanded.update(lastDraw="4s", left=12)
        remaining = advisor.unseen_counts(expanded)
        self.assertEqual(remaining, branch["remaining"])
        opponents = advisor._opponents(expanded, remaining)
        events = advisor._opportunities(expanded, after_discard=True)
        self.assertEqual(events, (1, 2, 3, 0) * 3)
        actual = advisor.advise(expanded)
        self.assertEqual(actual["best"]["tile"], "3p")
        expected = advisor._ready_discard(branch, sum(remaining), opponents, events, expanded)
        self.assertEqual(expected["discard"], actual["best"]["tile"])
        gross_income = {}
        for option in branch["options"]:
            with self.subTest(discard=option["discard"]):
                outcome = advisor._ready_discard(
                    {**branch, "options": [option]}, sum(remaining), opponents, events, expanded)
                candidate = next(c for c in actual["candidates"] if c["tile"] == option["discard"])
                self.assertEqual(outcome["score"], candidate["score"])
                self.assertEqual(round(outcome["winProbability"], 4), candidate["winProbability"])
                self.assertEqual(round(outcome["expectedDealInLoss"]), candidate["expectedDealInLoss"])
                gross_income[option["discard"]] = (outcome["winProbability"] * outcome["expectedWinPoints"] /
                                                    (1 - option["dealInProbability"]))
        # This is the previous income-only policy's contrary choice.
        self.assertEqual(max(gross_income, key=gross_income.get), "6m")

    def test_future_discard_is_one_absorbing_event_even_without_later_draws(self):
        opponents = [{"seat": i, "tenpai": 0.} for i in (1, 2, 3)]
        for danger in (0., .25, 1.):
            for events, child_probability in (((0,), 0.), ((0, 1), 1.)):
                with self.subTest(danger=danger, events=events):
                    option = {"discard": "7z", "furiten": False, "dealInProbability": danger,
                              "expectedDealInLoss": danger * 8000,
                              "waits": [{"tile": "1m", "count": 1, "ronPoints": 1000, "tsumoPoints": 1000}]}
                    branches = [{"draw": "1m", "count": 2, "remaining": (1,) + (0,) * 33,
                                 "options": [option]}]
                    with patch.object(advisor, "_event_survival", return_value=1.), patch.object(
                            advisor, "_win_model", return_value=(child_probability, 1000.)):
                        win, value, terminal, loss = advisor._one_shanten_model(
                            branches, 2, opponents, events, state())
                    self.assertAlmostEqual(win, (1 - danger) * child_probability)
                    self.assertEqual(value, 1000 if win else 0)
                    self.assertAlmostEqual(terminal, danger)
                    self.assertAlmostEqual(loss, danger * 8000)
                    unresolved = (1 - danger) * (1 - child_probability)
                    self.assertAlmostEqual(win + terminal + unresolved, 1.)
        self.assertEqual(advisor._one_shanten_model(branches, 2, opponents, (), state()), (0., 0., 0., 0.))

    def test_competition_only_scales_arrival_and_risk_does_not_repeat_after_misses(self):
        option = {"discard": "7z", "furiten": False, "dealInProbability": .25,
                  "expectedDealInLoss": 2000.,
                  "waits": [{"tile": "1m", "count": 1, "ronPoints": 0, "tsumoPoints": 1000}]}
        branches = [{"draw": "1m", "count": 1, "remaining": (0, 2) + (0,) * 32,
                     "options": [option]}]
        with patch.object(advisor, "_event_survival", return_value=.8), patch.object(
                advisor, "_win_model", return_value=(.5, 1000.)):
            win, value, terminal, loss = advisor._one_shanten_model(branches, 3, [], (0, 0), state())
        # First arrival is 1/3 * .8; after one miss it is 2/3 * .8 * 1/2 * .8.
        arrival = .8 / 3 + .8 ** 2 / 3
        self.assertAlmostEqual(win, arrival * .75 * .5)
        self.assertAlmostEqual(value, 1000)
        self.assertAlmostEqual(terminal, arrival * .25)
        self.assertAlmostEqual(loss, arrival * 2000)

    def test_root_discard_conditions_future_probability_and_charges_loss_once(self):
        s = state()
        hand = s["hand"].copy()
        hand.remove("1m")
        with patch.object(advisor, "_one_shanten_model", return_value=(.3, 2000., .2, 1600.)), patch.object(
                advisor, "_danger", return_value=(.1, 500., [])):
            candidate = advisor._position(hand, s, advisor.unseen_counts(s), "1m")
        self.assertEqual(candidate["shanten"], 1)
        self.assertEqual(candidate["winProbability"], .27)
        self.assertEqual(candidate["futureDiscardDealInProbability"], .18)
        self.assertEqual(candidate["futureDiscardDealInLoss"], 1440)
        terms = candidate["scoreBreakdown"]
        self.assertEqual(terms["currentDealInLoss"], -500)
        self.assertEqual(terms["futureDiscardDealInLoss"], -1440)
        self.assertAlmostEqual(terms["winIncome"], 540)
        self.assertAlmostEqual(terms["riskPreferenceAdjustment"], -(advisor._risk_weight(s) - 1) * 1940)
        self.assertEqual(candidate["score"], round(540 - advisor._risk_weight(s) * 1940 +
                                                  70 * 5 + 2 * candidate["ukeire"], 1))


if __name__ == "__main__":
    unittest.main()
