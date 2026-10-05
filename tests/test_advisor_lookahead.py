"""Complete one-shanten branches preserve rules, time, and weighted value."""
from copy import deepcopy
from contextlib import contextmanager
from itertools import permutations
import unittest
from unittest.mock import patch

import advisor
from test_advisor import state, tiles
from test_advisor_actions import offered


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


@contextmanager
def isolated_push(ready_choices, survival=1., miss_risk=0., miss_loss=0.):
    """Isolate probability bookkeeping; separate policy tests cover retreat.

    Force the supplied push strategy by making the artificial fold expensive.
    Production's rational choice to fold must not mask an absorption error.
    """
    def risks(hand, state, remaining, opponents):
        return ([(advisor.TILES[i], n, miss_risk, miss_loss)
                 for i, n in enumerate(remaining) if n], [], (miss_risk, miss_loss))

    def no_fold(events, *args):
        return [[advisor.Outcome(draw=1., draw_income=-1e9)] for _ in range(len(events) + 1)]

    with patch.object(advisor, "_policy_environment", return_value=(survival, (0., 0.), (0., 0.))), \
            patch.object(advisor, "_policy_risks", side_effect=risks), \
            patch.object(advisor, "fold_table", side_effect=no_fold), \
            patch.object(advisor, "_ready_choices", side_effect=ready_choices):
        yield


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

        def ready_win(branch, opponents, opportunities, snapshot):
            table = [advisor.Outcome(win=1., income=1000.) if snapshot["selfSeat"] in opportunities[i:]
                     else advisor.Outcome(draw=1.) for i in range(len(opportunities) + 1)]
            return [(option, table) for option in branch["options"]]

        orders = list(permutations(range(4)))
        expected = sum(any(tile < 2 for tile in order[:2]) for order in orders) / len(orders)
        with isolated_push(ready_win):
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
    def test_passed_evidence_keeps_the_opponent_riichi_timing_boundary(self):
        s = offered("123m234p678s55z5p1z", 2, ["3p|4p"], "5p")
        s["riichi"][1] = True
        s["riichiStep"][1] = 20
        s["rivers"][1] = [{"tile": "9p", "step": 20}]
        s["rivers"][2] = [{"tile": "6p", "step": 10}, {"tile": "7p", "step": 30}]
        before = deepcopy(s)
        remaining = advisor.unseen_counts(s)
        current = advisor._opponents(s, remaining)[0]
        future = advisor._opponents(s, remaining, after_current=True)[0]
        self.assertNotIn(advisor.tile_index("5p"), current["safe"])
        self.assertIn(advisor.tile_index("5p"), future["safe"])
        for enemy in (current, future):
            self.assertNotIn(advisor.tile_index("6p"), enemy["safe"])
            self.assertIn(advisor.tile_index("7p"), enemy["safe"])
        self.assertEqual(s, before)
        s["riichiStep"][1] = None
        unknown_step = advisor._opponents(s, remaining, after_current=True)[0]
        self.assertNotIn(advisor.tile_index("5p"), unknown_step["safe"])
        self.assertNotIn(advisor.tile_index("7p"), unknown_step["safe"])

    def test_passed_current_discard_matches_the_expanded_next_draw(self):
        s = offered("123m234p678s55z5p1z", 2, ["3p|4p"], "5p")
        s["riichi"][1] = True
        s["riichiStep"][1] = 20
        s["rivers"][1] = [{"tile": "9p", "step": 20}]
        before = deepcopy(s)
        branches, remaining = branches_for(s)
        branch = next(b for b in branches if b["draw"] == "1z")

        expanded = deepcopy(s)
        expanded["hand"].append("1z")
        expanded.update(lastDraw="1z", lastStep=41, left=47,
                        canAct=True, canDiscard=True, operations=[1],
                        operationDetails=[{"type": 1, "combination": []}], forbiddenDiscards=[],
                        lastAction={"name": "ActionDealTile", "seat": 0, "tile": "1z", "step": 41})
        unseen = advisor.unseen_counts(expanded)
        self.assertEqual(unseen, branch["remaining"])
        opponents = advisor._opponents(expanded, unseen)
        events = advisor._opportunities(expanded, after_discard=True)
        self.assertEqual(advisor._opportunities(s)[1:], events)
        actual = advisor.advise(expanded)
        self.assertEqual(actual["status"], "ready")
        for option in branch["options"]:
            with self.subTest(discard=option["discard"]):
                danger, loss, _ = advisor._danger(option["discard"], unseen, opponents)
                self.assertAlmostEqual(option["dealInProbability"], danger)
                self.assertAlmostEqual(option["expectedDealInLoss"], loss)
                outcome = advisor._ready_discard(
                    {**branch, "options": [option]}, sum(unseen), opponents, events, expanded)
                candidate = next(c for c in actual["candidates"] if c["tile"] == option["discard"])
                self.assertEqual(outcome["score"], candidate["score"])
                self.assertEqual(round(outcome["winProbability"], 4), candidate["winProbability"])
                self.assertEqual(round(outcome["expectedWinPoints"]), candidate["expectedWinPoints"])
        chosen = advisor._ready_discard(branch, sum(unseen), opponents, events, expanded)
        self.assertEqual(chosen["discard"], actual["best"]["tile"])

        # Current-window risk stays strict; only reaching the next draw proves passage.
        current = advisor._danger("5p", remaining, advisor._opponents(s, remaining))
        self.assertAlmostEqual(current[0], .1036)
        self.assertAlmostEqual(current[1], 525.2)
        self.assertEqual(s, before)

    def test_passed_current_five_is_safe_only_for_previously_locked_opponents(self):
        for offered_tile, held in (("5p", "5p"), ("0p", "5p"), ("5p", "0p")):
            for locked in ((), (1,), (1, 2), (1, 2, 3)):
                with self.subTest(offered=offered_tile, held=held, locked=locked):
                    s = offered("123m234p678s55z" + held + "1z", 2, ["3p|4p"], offered_tile)
                    for seat in locked:
                        s["riichi"][seat] = True
                        s["riichiStep"][seat] = 20
                        s["rivers"][seat].insert(0, {"tile": "9p", "step": 20})
                    before = deepcopy(s)
                    branches, _ = branches_for(s)
                    branch = next(b for b in branches if b["draw"] == "1z")
                    option = option_for(branches, "1z", held)
                    opponents = advisor._opponents(s, branch["remaining"])
                    unlocked = [o for o in opponents if not o["riichi"]]
                    danger, loss, _ = advisor._danger(held, branch["remaining"], unlocked)
                    self.assertAlmostEqual(option["dealInProbability"], danger)
                    self.assertAlmostEqual(option["expectedDealInLoss"], loss)
                    if any(o["seat"] != 3 for o in unlocked):
                        self.assertGreater(danger, 0)
                        self.assertGreater(loss, 0)
                    else:
                        self.assertEqual((danger, loss), (0., 0.))
                    self.assertEqual(s, before)

    def test_survived_root_discard_matches_expanded_window_without_waiving_root_risk(self):
        s = state()
        s["riichi"][1] = True
        s["riichiStep"][1] = 20
        s["rivers"][1] = [{"tile": "9m", "step": 20}]
        before = deepcopy(s)
        branches, remaining = branches_for(s, "7z")
        branch = next(b for b in branches if b["draw"] == "3s")
        option = option_for(branches, "3s", "7z")
        self.assertAlmostEqual(option["dealInProbability"], .00519324)
        self.assertAlmostEqual(option["expectedDealInLoss"], 6.76)

        expanded = deepcopy(s)
        expanded["hand"].remove("7z")
        expanded["hand"].append("3s")
        expanded["rivers"][0].append({"tile": "7z", "step": 41})
        expanded.update(lastDraw="3s", lastStep=49, left=44,
                        lastAction={"name": "ActionDealTile", "seat": 0, "step": 49})
        unseen = advisor.unseen_counts(expanded)
        self.assertEqual(unseen, branch["remaining"])
        opponents = advisor._opponents(expanded, unseen)
        self.assertEqual(advisor._danger("7z", unseen, opponents[:1])[:2], (0., 0.))
        events = advisor._opportunities(expanded, after_discard=True)
        actual = advisor.advise(expanded)
        self.assertEqual(actual["status"], "ready")
        for option in branch["options"]:
            with self.subTest(discard=option["discard"]):
                outcome = advisor._ready_discard(
                    {**branch, "options": [option]}, sum(unseen), opponents, events, expanded)
                candidate = next(c for c in actual["candidates"] if c["tile"] == option["discard"])
                self.assertEqual(outcome["score"], candidate["score"])
                self.assertEqual(round(outcome["winProbability"], 4), candidate["winProbability"])
                self.assertEqual(round(outcome["dealInProbability"], 4), candidate["dealInProbability"])
                self.assertEqual(round(outcome["expectedDealInLoss"]), candidate["expectedDealInLoss"])
        chosen = advisor._ready_discard(branch, sum(unseen), opponents, events, expanded)
        self.assertEqual(chosen["discard"], actual["best"]["tile"])

        root_danger, root_loss, _ = advisor._danger("7z", remaining, advisor._opponents(s, remaining))
        root = next(c for c in advisor.advise(s)["candidates"] if c["tile"] == "7z")
        self.assertAlmostEqual(root_danger, .0698556794)
        self.assertAlmostEqual(root_loss, 344.76)
        self.assertEqual(root["dealInProbability"], round(root_danger, 4))
        self.assertEqual(root["expectedDealInLoss"], round(root_loss))
        self.assertAlmostEqual(root["scoreBreakdown"]["currentDealInLoss"], -root_loss)
        self.assertEqual(s, before)

    def test_survived_root_five_is_safe_only_for_locked_opponents(self):
        for suit in "mps":
            for pair, discard, followup in (("55", "5", "5"), ("05", "0", "5"), ("05", "5", "0")):
                for locked in ((), (1,), (1, 2), (1, 2, 3)):
                    with self.subTest(suit=suit, discard=discard, followup=followup, locked=locked):
                        s = state("123m123p123s45s" + pair + suit + "1z")
                        for seat in locked:
                            s["riichi"][seat] = True
                            s["riichiStep"][seat] = 20
                            s["rivers"][seat] = [{"tile": "9m", "step": 20}]
                        branches, _ = branches_for(s, discard + suit)
                        branch = next(b for b in branches if b["draw"] == "3s")
                        option = option_for(branches, "3s", followup + suit)
                        opponents = advisor._opponents(s, branch["remaining"])
                        unlocked = [o for o in opponents if not o["riichi"]]
                        danger, loss, _ = advisor._danger(followup + suit, branch["remaining"], unlocked)
                        self.assertAlmostEqual(option["dealInProbability"], danger)
                        self.assertAlmostEqual(option["expectedDealInLoss"], loss)
                        if unlocked:
                            self.assertGreater(danger, 0)
                            self.assertGreater(loss, 0)
                        else:
                            self.assertEqual((danger, loss), (0., 0.))

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
        expanded["rivers"][0].append({"tile": "8p", "step": 41})
        expanded.update(lastDraw="4s", lastStep=49, left=12)
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
                    def ready(branch, enemies, opportunities, snapshot):
                        table = [advisor.Outcome(win=child_probability, income=child_probability * 1000.,
                                                 draw=1 - child_probability)] * (len(opportunities) + 1)
                        return [(o, table) for o in branch["options"]]

                    with isolated_push(ready):
                        win, value, terminal, loss = advisor._one_shanten_model(
                            branches, 2, opponents, events, state())
                    self.assertAlmostEqual(win, (1 - danger) * child_probability)
                    self.assertEqual(value, 1000 if win else 0)
                    self.assertAlmostEqual(terminal, danger)
                    self.assertAlmostEqual(loss, danger * 8000)
                    unresolved = (1 - danger) * (1 - child_probability)
                    self.assertAlmostEqual(win + terminal + unresolved, 1.)
        with isolated_push(ready):
            self.assertEqual(advisor._one_shanten_model(branches, 2, opponents, (), state()), (0., 0., 0., 0.))

    def test_competition_and_miss_risk_scale_arrival_and_ready_risk_is_paid_once(self):
        option = {"discard": "7z", "furiten": False, "dealInProbability": .25,
                  "expectedDealInLoss": 2000.,
                  "waits": [{"tile": "1m", "count": 1, "ronPoints": 0, "tsumoPoints": 1000}]}
        branches = [{"draw": "1m", "count": 1, "remaining": (0, 2) + (0,) * 32,
                     "options": [option]}]
        def ready(branch, enemies, opportunities, snapshot):
            table = [advisor.Outcome(win=.5, income=500., draw=.5)] * (len(opportunities) + 1)
            return [(o, table) for o in branch["options"]]

        for miss_risk in (0., .1):
            with self.subTest(miss_risk=miss_risk), isolated_push(
                    ready, survival=.8, miss_risk=miss_risk, miss_loss=miss_risk * 4000):
                outcome = advisor._one_shanten_outcome(branches, 3, [], (0, 0), state())
            # Arrival at a discard precedes that event's residual competition.
            # A prior miss must survive both its discard and competition first.
            arrival = 1 / 3 + (2 / 3) * (1 - miss_risk) * .8 * (1 / 2)
            miss_mass = 2 / 3 + (2 / 3) * (1 - miss_risk) * .8 * (1 / 2)
            win, value, terminal, loss = outcome.metrics()
            self.assertAlmostEqual(win, arrival * .75 * .8 * .5)
            self.assertAlmostEqual(value, 1000)
            self.assertAlmostEqual(terminal, arrival * .25 + miss_mass * miss_risk)
            self.assertAlmostEqual(loss, arrival * 2000 + miss_mass * miss_risk * 4000)
            self.assertAlmostEqual(outcome.win + outcome.deal + outcome.tsumo + outcome.other + outcome.draw, 1.)

    def test_root_discard_conditions_future_probability_and_charges_loss_once(self):
        s = state()
        hand = s["hand"].copy()
        hand.remove("1m")
        with patch.object(advisor, "_one_shanten_outcome", return_value=advisor.Outcome(
                win=.3, income=600., deal=.2, loss=1600., draw=.5)), patch.object(
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
