"""Full precision selection and explicit current-fold eligibility regressions."""
from copy import deepcopy
from contextlib import nullcontext
from itertools import permutations
from math import fsum
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import advisor as selection
from advisor import counts34
from test_advisor import state, tiles
from test_advisor_actions import offered, own_action


def candidate(code, raw=100., **metadata):
    return {"actionId": code, "_rawScore": raw, "score": round(raw, 1), **metadata}


def fold_state(legal):
    snapshot = state()
    snapshot["hand"] = list(legal)
    return snapshot


def shape_pair():
    # Stable historical line 766: the exact 14 tiles and publicly unseen pool.
    hand = tiles("11m22367p306789s6z")
    counts = counts34(hand)
    remaining = [4 - count for count in counts]
    remaining[1:8] = [0] * 7
    remaining[14] -= 1  # Six-pin dora indicator.
    remaining[29] -= 3  # Three public west discards.
    remaining[30] -= 2  # Two extracted north tiles.
    pair = []
    for discard in ("3s", "6z"):
        after = hand.copy()
        after.remove(discard)
        pair.append(candidate("discard:" + discard, _tieHand=tuple(after),
                              _tieRemaining=tuple(remaining), _tieSpecial=True))
    return pair


class SelectionTests(unittest.TestCase):
    def test_display_tie_does_not_override_raw_monetary_score(self):
        low = candidate("discard:a", 100.01, _tieLoss=0)
        high = candidate("discard:z", 100.04, _tieLoss=500)
        self.assertEqual(low["score"], high["score"])
        self.assertIs(selection._rank_candidates([low, high])[0], high)

    def test_float_noise_reaches_semantic_tie_break(self):
        low_loss = candidate("discard:z", 100., _tieLoss=1.)
        high_loss = candidate("discard:a", 100. + 1e-11, _tieLoss=2.)
        for order in permutations([low_loss, high_loss]):
            self.assertIs(selection._rank_candidates(order)[0], low_loss)

    def test_anchor_groups_are_independent_of_input_order(self):
        candidates = [candidate("a", 100. + 1.8e-9, _tieLoss=4.),
                      candidate("b", 100. + .9e-9, _tieLoss=3.),
                      candidate("c", 100., _tieLoss=0.)]
        for order in permutations(candidates):
            self.assertEqual([c["actionId"] for c in selection._rank_candidates(order)], ["b", "a", "c"])

    def test_best_only_preserves_complete_top_epsilon_group(self):
        candidates = [candidate("a", 100. + 1.8e-9, _tieLoss=4.),
                      candidate("b", 100. + .9e-9, _tieLoss=3.),
                      candidate("c", 100., _tieLoss=0.)]
        for order in permutations(candidates):
            full = selection._rank_candidates(order)
            best = selection._rank_candidates(order, best_only=True)
            self.assertEqual(best, full[:1])
            self.assertEqual(best[0]["actionId"], "b")

    def test_best_only_does_not_search_shapes_in_already_losing_groups(self):
        for field, winning, losing in (("_rawScore", 100., 90.), ("_tieLoss", 0., 1.),
                                       ("_tieCurrentLoss", 0., 1.), ("_tieSafeStock", 2., 1.),
                                       ("_tieWin", .2, .1), ("_tieRon", 8., 4.),
                                       ("_tieEfficiency", 450., 400.), ("_tieUkeire", 12., 8.)):
            with self.subTest(field=field):
                winner = {**candidate("winner"), field: winning}
                losers = [{**candidate(code), field: losing} for code in ("a", "b")]
                with patch.object(selection, "_same_shanten_improvement",
                                  side_effect=AssertionError("irrelevant losing-group shape")):
                    self.assertEqual(selection._rank_candidates([*losers, winner], best_only=True), [winner])

    def test_best_only_still_compares_shapes_of_all_semantically_tied_finalists(self):
        first, second = candidate("a"), candidate("z")
        calls = []

        def shape(item, cache):
            calls.append(item["actionId"])
            return 1. if item is first else 2.

        with patch.object(selection, "_same_shanten_improvement", side_effect=shape):
            full = selection._rank_candidates([first, second])
            calls.clear()
            best = selection._rank_candidates([first, second], best_only=True)
        self.assertEqual(best, full[:1])
        self.assertEqual(best, [second])
        self.assertEqual(set(calls), {"a", "z"})

    def test_semantic_metrics_have_the_same_float_tolerance(self):
        safe = candidate("z", _tieLoss=100. + 1e-11, _tieSafeStock=2)
        unsafe = candidate("a", _tieLoss=100., _tieSafeStock=1)
        self.assertIs(selection._rank_candidates([unsafe, safe])[0], safe)

    def test_safe_stock_counts_physical_tiles_before_attack_efficiency(self):
        safe = candidate("z", _tieSafeStock=2, _tieEfficiency=0)
        efficient = candidate("a", _tieSafeStock=1, _tieEfficiency=500)
        self.assertIs(selection._rank_candidates([efficient, safe])[0], safe)

    def test_legal_ron_quality_precedes_shape_preference(self):
        legal = candidate("z", _tieWin=.2, _tieRon=6, _tieEfficiency=0)
        blocked = candidate("a", _tieWin=.2, _tieRon=0, _tieEfficiency=500)
        self.assertIs(selection._rank_candidates([blocked, legal])[0], legal)

    def test_replacement_tie_metrics_do_not_use_rounded_display_ukeire(self):
        first = candidate("a", ukeire=4.0, _tieUkeire=4.01)
        second = candidate("z", ukeire=4.0, _tieUkeire=4.04)
        self.assertIs(selection._rank_candidates([first, second])[0], second)

    def test_shape_search_only_runs_when_all_earlier_metrics_tie(self):
        candidates = [candidate("a", 100.), candidate("z", 100.001)]
        with patch.object(selection, "_same_shanten_improvement", side_effect=AssertionError("unexpected shape search")):
            self.assertEqual(selection._rank_candidates(candidates)[0]["actionId"], "z")

    def test_historical_shape_gain_breaks_true_tie(self):
        first, second = shape_pair()
        cache = {}
        first_value = selection._same_shanten_improvement(first, cache)
        second_value = selection._same_shanten_improvement(second, cache)
        self.assertAlmostEqual(first_value * sum(first["_tieRemaining"]), 38)
        self.assertAlmostEqual(second_value * sum(second["_tieRemaining"]), 46)
        for order in permutations([first, second]):
            self.assertIs(selection._rank_candidates(order, cache)[0], second)

    def test_root_ready_and_call_followups_share_the_same_semantic_selection(self):
        pair = shape_pair()
        for representation in ("discard", "ready", "pon"):
            choices = []
            for original in pair:
                tile = original["actionId"].split(":")[1]
                choice = dict(original)
                if representation == "ready":
                    choice.pop("actionId")
                    choice["discard"] = tile
                elif representation == "pon":
                    choice["actionId"] = "pon:5p:" + tile
                    choice["followupDiscard"] = tile
                choices.append(choice)
            selected = selection._rank_candidates(choices)[0]
            self.assertEqual(selected["_tieHand"], pair[1]["_tieHand"])

    def test_equivalent_suit_exchange_preserves_shape_choice(self):
        original = shape_pair()
        # Swapping p/s is legal in sanma; the removed manzu families stay fixed.
        exchanged = []
        for old in original:
            new = dict(old)
            new["_tieHand"] = tuple(tile.translate(str.maketrans("ps", "sp")) for tile in old["_tieHand"])
            rem = old["_tieRemaining"]
            new["_tieRemaining"] = rem[:9] + rem[18:27] + rem[9:18] + rem[27:]
            exchanged.append(new)
        for first, second in zip(original, exchanged):
            self.assertEqual(selection._same_shanten_improvement(first, {}), selection._same_shanten_improvement(second, {}))
        self.assertEqual(selection._rank_candidates(original)[0]["actionId"], selection._rank_candidates(exchanged)[0]["actionId"])

    def test_remaining_tiles_and_special_route_are_part_of_cache_key(self):
        first = shape_pair()[0]
        cache = {}
        selection._same_shanten_improvement(first, cache)
        rem = list(first["_tieRemaining"])
        rem[0] -= 1
        selection._same_shanten_improvement({**first, "_tieRemaining": tuple(rem)}, cache)
        selection._same_shanten_improvement({**first, "_tieSpecial": False}, cache)
        self.assertEqual(len(cache), 3)

    def test_honor_exchange_reuses_shape_cache_only_with_paired_physical_counts(self):
        original = shape_pair()[0]
        # North has zero held/two unseen; green has one held/three unseen.
        # Both roles and remaining counts must travel together under exchange.
        remaining = list(original["_tieRemaining"])
        remaining[30], remaining[32] = remaining[32], remaining[30]
        exchanged = {**original, "_tieRemaining": tuple(remaining),
                     "_tieHand": tuple({"4z": "6z", "6z": "4z"}.get(tile, tile)
                                       for tile in original["_tieHand"])}
        cache = {}
        expected = selection._same_shanten_improvement(original, cache)
        actual = selection._same_shanten_improvement(exchanged, cache)
        self.assertEqual(actual, expected)
        self.assertEqual(actual, selection._same_shanten_improvement(exchanged, {}))
        self.assertEqual(len(cache), 1)
        # Swapping only unseen counts is a different, still physically valid
        # position. It must not borrow the cached value of the paired exchange.
        unpaired = {**original, "_tieRemaining": tuple(remaining)}
        unpaired_value = selection._same_shanten_improvement(unpaired, cache)
        self.assertEqual(unpaired_value, selection._same_shanten_improvement(unpaired, {}))
        self.assertEqual(len(cache), 2)

    def test_cancellation_does_not_store_partial_shape_result(self):
        cache = {}
        with patch.object(selection, "_check_search", side_effect=RuntimeError("cancelled")):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                selection._same_shanten_improvement(shape_pair()[0], cache)
        self.assertEqual(cache, {})

    def test_replacement_shape_is_weighted_from_actual_children(self):
        first, second = shape_pair()
        mixed = candidate("kita", _tieChildren=((2, first), (1, second)))
        cache = {}
        expected = fsum([2 * selection._same_shanten_improvement(first, cache),
                         selection._same_shanten_improvement(second, cache)]) / 3
        self.assertEqual(selection._same_shanten_improvement(mixed, cache), expected)

    def test_locked_and_terminal_candidates_do_not_invent_discard_freedom(self):
        first = {**shape_pair()[0], "_tieLocked": True}
        self.assertEqual(selection._same_shanten_improvement(first, {}), 0)
        self.assertEqual(selection._same_shanten_improvement(candidate("abort"), {}), 0)

    def test_encoding_is_only_the_last_complete_tie_fallback(self):
        first, second = candidate("z"), candidate("a")
        self.assertEqual([c["actionId"] for c in selection._rank_candidates([first, second])], ["a", "z"])


class FoldEligibilityTests(unittest.TestCase):
    def setUp(self):
        mocked = patch.object(selection, "_danger", side_effect=lambda tile, remaining, opponents: opponents[tile])
        mocked.start()
        self.addCleanup(mocked.stop)

    def test_ready_only_options_cannot_hide_a_safer_nonready_discard(self):
        full_window = fold_state(["1z", "2p", "6s"])
        risks = {"1z": (.01, 80., []), "2p": (.04, 320., []), "6s": (.05, 400., [])}
        eligible = selection._current_fold_eligibility(full_window, (), risks)
        ready_options = [{"discard": "2p"}, {"discard": "6s"}]
        self.assertEqual(eligible, {"1z": True, "2p": False, "6s": False})
        self.assertFalse(any(eligible[option["discard"]] for option in ready_options))

    def test_greedy_guard_uses_expected_loss_instead_of_raw_hit_probability(self):
        risks = {"1z": (.01, 200., []), "2p": (.02, 100., [])}
        eligible = selection._current_fold_eligibility(fold_state(["1z", "2p"]), (), risks)
        self.assertEqual(eligible, {"1z": False, "2p": True})

    def test_tied_minimum_loss_is_epsilon_aware_and_order_independent(self):
        risks = {"1z": (.01, 100., []), "2p": (.02, 100. + 1e-11, []),
                 "6s": (.02, 100.01, [])}
        expected = {"1z": True, "2p": True, "6s": False}
        for order in permutations(risks):
            self.assertEqual(selection._current_fold_eligibility(fold_state(order), (), risks), expected)

    def test_forbidden_discards_do_not_enter_the_minimum(self):
        risks = {"1z": (0., 0., []), "2p": (.02, 100., []), "6s": (.03, 200., [])}
        snapshot = fold_state(["1z", "2p", "6s"])
        snapshot["forbiddenDiscards"] = ["1z"]
        self.assertEqual(selection._current_fold_eligibility(snapshot, (), risks),
                         {"2p": True, "6s": False})

    def test_no_candidate_probe_is_marked_safe_before_its_current_risk_is_charged(self):
        full_window = fold_state(["1z", "2p"])
        remaining = (3,) * 34
        opponents = [{"safe": {27}}]
        calls = []

        def danger(tile, unseen, evidence):
            self.assertIs(unseen, remaining)
            self.assertIs(evidence, opponents)
            self.assertEqual(evidence[0]["safe"], {27})
            calls.append(tile)
            return (0., 0., []) if tile == "1z" else (.1, 800., [])

        with patch.object(selection, "_danger", side_effect=danger):
            eligible = selection._current_fold_eligibility(full_window, remaining, opponents)
        self.assertEqual(calls, ["1z", "2p"])
        self.assertEqual(eligible, {"1z": True, "2p": False})


class StrategyMetadataTests(unittest.TestCase):
    def test_reachable_no_yaku_call_fold_does_not_pay_attack_route_penalty(self):
        snapshot = offered("147m456p789s15z23s", 2, ["2s|3s"], "1s")
        snapshot["left"] = 4
        snapshot["riichi"] = [False, True, True, True]
        snapshot["riichiStep"] = [None, 10, 10, 10]
        for seat in (1, 2, 3):
            snapshot["rivers"][seat].insert(0, {"tile": "1m", "step": 20})
        original = deepcopy(snapshot)
        advice = selection.advise(snapshot)
        self.assertEqual(advice["status"], "ready")
        called = next(c for c in advice["candidates"] if c["action"] == "chi")
        self.assertEqual(called["winProbability"], 0)
        self.assertNotIn("openNoYakuPenalty", called["scoreBreakdown"])
        self.assertEqual(called["currentStrategy"], "fold")
        self.assertEqual(called["followupDiscard"], "1m")
        self.assertEqual(called["score"], round(called["policyComparison"]["fold"], 1))
        self.assertEqual(snapshot, original)

    def test_open_call_attack_cost_is_compared_before_choosing_current_policy(self):
        snapshot = state()
        # These are reachable terminal masses and plausible payments: before
        # the call-specific attack cost, attack is -1900 and pure fold -2100.
        attack = selection.Outcome(win=.1, income=1000., deal=.3, loss=2000.,
                                   draw=.6, draw_income=-600.)
        fold = selection.Outcome(draw=1., draw_income=-2100.)
        self.assertEqual(selection._select_current_policy(attack, fold, 0., 0., snapshot)[2], "attack")
        _, selected, mode, comparison = selection._select_current_policy(
            attack, fold, 0., 0., snapshot, attack_penalty=500.)
        self.assertEqual(mode, "fold")
        self.assertAlmostEqual(comparison["attack"], -2400.)
        self.assertAlmostEqual(comparison["fold"], -2100.)
        self.assertEqual(selected.win, 0)
        self.assertEqual(selected.income, 0)

    def test_current_root_fold_has_no_attack_tie_reward_or_future_fold_label(self):
        snapshot = state()
        hand = snapshot["hand"].copy()
        hand.remove("1z")
        attack = selection.Outcome(win=.1, income=100., deal=.2, loss=2000., draw=.7)
        fold = selection.Outcome(draw=1., draw_income=-1000.)
        with patch.object(selection, "_ready_policy", return_value=[attack]), patch.object(
                selection, "_fold_policy", return_value=[[fold]]), patch.object(
                selection, "_danger", return_value=(0., 0., [])), patch.object(
                selection, "_policy_risks", return_value=([], [(0., 0.)], (0., 0.))):
            result = selection._position(hand, snapshot, selection.unseen_counts(snapshot), "1z")
        self.assertEqual(result["currentStrategy"], "fold")
        self.assertEqual(result["_tieEfficiency"], 0)
        self.assertEqual(result["futureFoldProbability"], 0)
        self.assertEqual(result["winProbability"], 0)
        self.assertNotIn("winIncome", result["scoreBreakdown"])
        self.assertNotIn("efficiencyReward", result["scoreBreakdown"])
        self.assertAlmostEqual(sum(result["terminalProbabilities"].values()), 1)

    def test_current_ready_branch_fold_uses_the_same_zero_attack_tie_reward(self):
        snapshot = state()
        hand = snapshot["hand"].copy()
        hand.remove("1z")
        option = {"discard": "1z", "hand": tuple(hand), "dealInProbability": 0.,
                  "expectedDealInLoss": 0., "waits": [{"count": 4, "ronPoints": 1000.}],
                  "_tieHand": tuple(hand), "_tieRemaining": selection.unseen_counts(snapshot),
                  "_tieSpecial": True, "_stock": [(0., 0.)]}
        attack = selection.Outcome(win=.1, income=100., deal=.2, loss=2000., draw=.7)
        fold = selection.Outcome(draw=1., draw_income=-1000.)
        result = selection._ready_result(option, attack, snapshot, fold)
        self.assertEqual(result["currentStrategy"], "fold")
        self.assertEqual(result["_tieEfficiency"], 0)
        self.assertEqual(result["outcome"].win, 0)
        self.assertEqual(result["outcome"].income, 0)

    def test_locked_hand_cannot_count_held_safe_tiles_as_usable_defense(self):
        args = (tiles("123m123p123s45s77z"), (3,) * 34, True,
                selection.Outcome(draw=1.), 0., [(0., 0.), (0., 0.), (.1, 800.)], [], 420., 4)
        unlocked = selection._selection_metadata(*args)
        locked = selection._selection_metadata(*args, locked=True)
        self.assertEqual(unlocked["_tieSafeStock"], 2)
        self.assertEqual(locked["_tieSafeStock"], 0)

    def test_abortive_ending_clears_nonexistent_future_shape_and_stock(self):
        result = {**shape_pair()[0], "dealInProbability": .1235, "expectedDealInLoss": 988,
                  "_currentDanger": .123456, "_currentLoss": 987.654,
                  "_tieSafeStock": 4, "_tieRon": 8, "_tieUkeire": 12,
                  "_tieEfficiency": 444, "_tieChildren": [(1, shape_pair()[1])],
                  "policyComparison": {"attack": 100., "fold": 50.}}
        selection._abort_terminals(result)
        self.assertEqual(result["currentStrategy"], "end-hand")
        for field in ("_tieSafeStock", "_tieRon", "_tieUkeire", "_tieEfficiency", "_tieWin"):
            self.assertEqual(result[field], 0)
        for field in ("_tieHand", "_tieChildren", "policyComparison"):
            self.assertNotIn(field, result)
        self.assertEqual(result["terminalProbabilities"]["dealIn"], .123456)
        self.assertAlmostEqual(sum(result["terminalProbabilities"].values()), 1)

    def test_replacement_child_current_fold_is_future_fold_at_root(self):
        snapshot = own_action("123p123s789s45p77z4z", 11, [], players=3)
        choice = selection._action_choices(snapshot)[0][0]
        risk_weight = selection._risk_weight(snapshot)

        def followup(drawn, remaining, **kwargs):
            folding = drawn["lastDraw"] == "1z"
            win = 0. if folding else .2
            result = {"tile": "1z", "actionId": "discard:1z", "shanten": 1, "ukeire": 4,
                      "furiten": False, "winProbability": win, "expectedWinPoints": 1000 if win else 0,
                      "dealInProbability": .1, "expectedDealInLoss": 800,
                      "_currentDanger": .1, "_currentLoss": 800., "_tieWin": win,
                      "currentStrategy": "fold" if folding else "attack",
                      "futureFoldProbability": 0. if folding else .25,
                      "terminalProbabilities": {"selfWin": win, "dealIn": .1,
                                                "opponentTsumo": 0., "otherRon": 0.,
                                                "exhaustiveDraw": .9 - win}, "score": 0.}
            selection._record_score(result, winIncome=win * 1000., currentDealInLoss=-800.,
                                    riskPreferenceAdjustment=-(risk_weight - 1) * 800.)
            return [result]

        with patch.object(selection, "_draw_pool", return_value=[("1z", 2), ("2z", 1)]), patch.object(
                selection, "_discards", side_effect=followup), patch.object(
                selection, "_danger", return_value=(.2, 1600., [])):
            result = selection._replacement(snapshot, choice, selection.unseen_counts(snapshot))
        self.assertEqual(result["currentStrategy"], "replacement")
        self.assertEqual(result["futureFoldProbability"], round(.8 * (2 + .25) / 3, 4))
        self.assertEqual([c["currentStrategy"] for c in result["replacementOutcomes"]], ["fold", "attack"])
        self.assertAlmostEqual(sum(result["terminalProbabilities"].values()), 1)


def exchange_pin_sou(value):
    """Transform every tile-bearing field, including red tiles and call offers."""
    if isinstance(value, str):
        return re.sub(r"([0-9])([ps])", lambda match: match[1] + {"p": "s", "s": "p"}[match[2]], value)
    if isinstance(value, list):
        return [exchange_pin_sou(item) for item in value]
    if isinstance(value, dict):
        return {key: exchange_pin_sou(item) for key, item in value.items()}
    return value


class SelectionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cases = json.loads((Path(__file__).parent / "fixtures/advisor_cases.json").read_text())["cases"]
        cls.cases = {case["id"]: case["state"] for case in cases}

    def assert_same_candidate_accounts(self, expected, actual):
        self.assertEqual(actual["actionId"], expected["actionId"])
        self.assertEqual(actual.get("currentStrategy"), expected.get("currentStrategy"))
        self.assertEqual(actual.get("followupDiscard"), expected.get("followupDiscard"))
        self.assertEqual(actual["score"], expected["score"])
        self.assertEqual(actual["winProbability"], expected["winProbability"])
        for field in ("scoreBreakdown", "terminalProbabilities"):
            self.assertEqual(set(actual[field]), set(expected[field]))
            for key, value in expected[field].items():
                self.assertAlmostEqual(actual[field][key], value, places=8)

    def test_real_candidate_and_hand_reordering_preserves_choice_and_accounts(self):
        legal_discards = selection._legal_discards
        for case in ("ordinary-efficiency", "broad-one-shanten", "opponent-riichi-defense", "pon-yakuhai"):
            with self.subTest(case=case):
                snapshot = deepcopy(self.cases[case])
                original = deepcopy(snapshot)
                expected = selection.advise(snapshot)
                self.assertEqual(expected["status"], "ready")
                self.assertEqual(snapshot, original)
                expected_candidates = {c["actionId"]: c for c in expected["candidates"]}
                for variant in ("hand", "candidates"):
                    with self.subTest(variant=variant):
                        changed = deepcopy(snapshot)
                        if variant == "hand":
                            changed["hand"].reverse()
                        context = (patch.object(selection, "_legal_discards", side_effect=lambda s: legal_discards(s)[::-1])
                                   if variant == "candidates" else nullcontext())
                        with context:
                            actual = selection.advise(changed)
                        self.assertEqual(actual["status"], "ready")
                        self.assertEqual(actual["best"]["actionId"], expected["best"]["actionId"])
                        self.assertEqual({c["actionId"] for c in actual["candidates"]}, set(expected_candidates))
                        for candidate in actual["candidates"]:
                            self.assert_same_candidate_accounts(expected_candidates[candidate["actionId"]], candidate)

    def test_equivalent_real_suit_exchange_preserves_monetary_accounts_and_choice(self):
        for case in ("ordinary-efficiency", "broad-one-shanten", "opponent-riichi-defense", "pon-yakuhai"):
            with self.subTest(case=case):
                snapshot = deepcopy(self.cases[case])
                expected = exchange_pin_sou(selection.advise(snapshot))
                actual = selection.advise(exchange_pin_sou(snapshot))
                self.assertEqual(expected["status"], "ready")
                self.assertEqual(actual["status"], "ready")
                expected_candidates = {c["actionId"]: c for c in expected["candidates"]}
                self.assertEqual({c["actionId"] for c in actual["candidates"]}, set(expected_candidates))
                for candidate in actual["candidates"]:
                    self.assert_same_candidate_accounts(expected_candidates[candidate["actionId"]], candidate)
                self.assertEqual(actual["best"]["actionId"], expected["best"]["actionId"])


if __name__ == "__main__":
    unittest.main()
