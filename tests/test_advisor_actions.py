"""Server-authorized actions, physical tile accounting, and comparable values."""
from copy import deepcopy
import unittest

from advisor import (advise, unseen_counts, _action_choices,
                     _apply_choice, _position, _riichi, _draw_pool,
                     _danger, _opponents, _discards, _rank_candidates)
from test_advisor import state, tiles


def offered(hand, kind, combination, called, source=3, players=4):
    s = state(hand, players)
    s.update(canDiscard=False, canAct=True, operations=[kind], lastDraw=None,
             operationDetails=[{"type": kind, "combination": combination}],
             lastAction={"name": "ActionDiscardTile", "seat": source, "tile": called, "step": 40})
    s["rivers"][source] = [{"tile": called, "step": 40}]
    return s


def own_action(hand, kind, combination, players=4):
    s = state(hand, players)
    s.update(canAct=True, operations=[1, kind], operationDetails=[{"type": kind, "combination": combination}])
    s["lastDraw"] = s["hand"][-1]
    return s


def get_action(s, action):
    a = advise(s)
    if a["status"] not in ("ready", "analysis"):
        raise AssertionError(a)
    return next(c for c in a["candidates"] if c["action"] == action)


class CallAdviceTests(unittest.TestCase):
    def test_yakuhai_pon_beats_pass_and_names_followup(self):
        s = offered("55z123m456p23s99p1z", 3, ["5z|5z"], "5z")
        a = advise(s)
        self.assertEqual(a["best"]["action"], "pon")
        # Follow-up uses the same terminal-value comparison as a real window;
        # a shape reward must not force the discard with the lowest shanten.
        after = _apply_choice(s, _action_choices(s)[0][0])
        followup = _rank_candidates(_discards(after, unseen_counts(after)))[0]
        self.assertEqual(a["best"]["followupDiscard"], followup["tile"])
        self.assertEqual(a["best"]["score"], followup["score"])
        self.assertGreater(a["best"]["winProbability"], get_action(s, "pass")["winProbability"])
        self.assertGreater(a["best"]["expectedWinPoints"], 0)

    def test_no_yaku_chi_is_rejected_in_favor_of_pass(self):
        s = offered("123m456p789s55z23s", 2, ["2s|3s"], "1s")
        a = advise(s)
        self.assertEqual(a["best"]["action"], "pass")
        chi = get_action(s, "chi")
        self.assertEqual(chi["winProbability"], 0)
        self.assertEqual(chi["expectedWinPoints"], 0)
        self.assertIn("无役", " ".join(chi["reasons"]))

    def test_chi_excludes_same_tile_and_suji_swap_discard(self):
        s = offered("3456m123p789s112z", 2, ["4m|5m"], "3m")
        choice = _action_choices(s)[0][0]
        after = _apply_choice(s, choice)
        self.assertEqual(set(after["forbiddenDiscards"]), {"3m", "6m"})
        self.assertNotIn(get_action(s, "chi")["followupDiscard"], ("3m", "6m"))

    def test_wrong_source_nonsequence_and_stale_called_tile_are_ignored(self):
        for change in ("wrong_seat", "wrong_sequence", "stale", "already_called"):
            s = offered("3456m123p789s112z", 2, ["4m|5m"], "3m")
            if change == "wrong_seat":
                s["lastAction"]["seat"] = 1
            elif change == "wrong_sequence":
                s["operationDetails"][0]["combination"] = ["4m|6m"]
            elif change == "stale":
                s["lastAction"]["step"] = 39
            else:
                s["rivers"][3][-1]["called"] = True
            a = advise(s)
            self.assertEqual([c["action"] for c in a["candidates"]], ["pass"], change)
            self.assertTrue(a["warnings"], change)

    def test_two_red_pon_combinations_are_distinct_and_conserve_tiles(self):
        s = offered("055p123m456s77z12s", 3, ["0p|5p", "5p|5p"], "5p")
        choices, warnings = _action_choices(s)
        self.assertFalse(warnings)
        self.assertEqual(len(choices), 2)
        self.assertNotEqual(choices[0]["actionId"], choices[1]["actionId"])
        for choice in choices:
            after = _apply_choice(s, choice)
            self.assertEqual(unseen_counts(after), unseen_counts(s))
            self.assertTrue(after["rivers"][3][-1]["called"])
        self.assertEqual(len([c for c in advise(s)["candidates"] if c["action"] == "pon"]), 2)

    def test_call_does_not_mutate_source_snapshot(self):
        s = offered("55z123m456p23s99p1z", 3, ["5z|5z"], "5z")
        original = deepcopy(s)
        advise(s)
        self.assertEqual(s, original)

    def test_pass_preserves_current_furiten_without_fictitious_discard(self):
        s = offered("123m123p123s45s77z", 2, ["4s|5s"], "3s")
        s["rivers"][0] = [{"tile": "9m"}]
        passed = get_action(s, "pass")
        self.assertFalse(passed["furiten"])
        self.assertEqual(passed["ukeire"], 6)
        self.assertIsNone(passed["tile"])
        self.assertEqual(passed["dealInProbability"], 0)

    def test_sanma_never_chi_even_if_bad_operation_claims_it(self):
        s = offered("3456p123s789s112z", 2, ["4p|5p"], "3p", source=2, players=3)
        a = advise(s)
        self.assertEqual(a["best"]["action"], "pass")
        self.assertFalse(any(c["action"] == "chi" for c in a["candidates"]))


class RiichiAdviceTests(unittest.TestCase):
    def test_good_riichi_beats_same_tile_dama(self):
        s = own_action("123m123p123s45s77z1z", 7, ["1z"])
        a = advise(s)
        self.assertEqual(a["best"]["action"], "riichi")
        dama = next(c for c in a["candidates"] if c["action"] == "discard" and c["tile"] == "1z")
        self.assertGreater(a["best"]["expectedWinPoints"], dama["expectedWinPoints"])
        self.assertGreater(a["best"]["futureForcedDealInLoss"], 0)

    def test_low_remaining_draws_furiten_prefers_dama(self):
        s = own_action("123m123p123s45s77z1z", 7, ["1z"])
        s["left"] = 4
        s["rivers"][0] = [{"tile": "3s"}]
        a = advise(s)
        self.assertEqual(a["best"]["action"], "discard")
        self.assertTrue(get_action(s, "riichi")["furiten"])

    def test_new_riichi_recomputes_furiten_after_changing_waits(self):
        s = own_action("11223344556679m", 7, ["7m"])
        s["rivers"][0] = [{"tile": "1m"}]
        s["furiten"] = True
        c = get_action(s, "riichi")
        self.assertFalse(c["furiten"])
        self.assertEqual([w["tile"] for w in c["winningTiles"]], ["9m"])
        self.assertGreater(c["winningTiles"][0]["ronPoints"], 0)
        self.assertGreater(c["winProbability"], 0)
        s["furiten"] = False
        self.assertEqual(c, get_action(s, "riichi"))

    def test_confirmed_riichi_preserves_server_furiten_after_draw(self):
        s = state()
        s["riichi"][0] = True
        s["furiten"] = True
        c = get_action(s, "discard")
        self.assertTrue(c["furiten"])
        self.assertTrue(all(w["ronPoints"] == 0 for w in c["winningTiles"]))
        self.assertTrue(any(w["tsumoPoints"] > 0 for w in c["winningTiles"]))

    def test_deposit_only_lost_on_nonwinning_survival_not_a_free_prize(self):
        s = own_action("123m123p123s45s77z1z", 7, ["1z"])
        s["riichiSticks"] = 2
        remaining = unseen_counts(s)
        choice = _action_choices(s)[0][0]
        committed = deepcopy(s)
        committed["riichi"][0] = True
        hand = s["hand"].copy()
        hand.remove("1z")
        without_cost = _position(hand, committed, remaining, "1z")
        c = _riichi(s, choice, remaining)
        self.assertEqual(c["winProbability"], without_cost["winProbability"])
        self.assertEqual(c["futureForcedDealInLoss"], without_cost["futureForcedDealInLoss"])
        expected_cost = 1000 * (1 - c["dealInProbability"] - c["winProbability"])
        self.assertAlmostEqual(c["expectedRiichiCost"], expected_cost, delta=.5)
        expected_score = without_cost["score"] - expected_cost
        self.assertAlmostEqual(c["score"], expected_score, delta=1.5)
        self.assertEqual(s["riichiSticks"], 2)

    def test_declaration_ron_does_not_pay_riichi_stick(self):
        s = own_action("123m123p123s45s77z1z", 7, ["1z"])
        s["riichi"][1] = True
        c = get_action(s, "riichi")
        self.assertGreater(c["dealInProbability"], 0)
        self.assertLess(c["expectedRiichiCost"], round(1000 * (1 - c["winProbability"])))

    def test_only_verified_server_riichi_discards_and_red_family(self):
        s = own_action("123m123p123s45s77z1z", 7, ["9m"])
        self.assertFalse(any(c["action"] == "riichi" for c in advise(s)["candidates"]))
        s = own_action("123m123p123s55p77z1z", 7, ["0p"])
        choices, warnings = _action_choices(s)
        self.assertEqual([c["tile"] for c in choices], ["5p"])
        self.assertFalse(warnings)
        s["operationDetails"][0]["combination"] = ["5p"]
        s["hand"][9] = "0p"
        self.assertEqual([c["tile"] for c in _action_choices(s)[0]], ["0p", "5p"])

    def test_riichi_red_family_is_bidirectional_and_does_not_allow_adjacent_tiles(self):
        # Official LiqiSelect and Action_LiQi compare MJPai.Distance, whose
        # numValue includes suit/index but ignores the physical red-five flag.
        for combination in ("0p", "5p"):
            with self.subTest(combination=combination):
                s = own_action("123m123p123s05p77z4p", 7, [combination])
                choices, warnings = _action_choices(s)
                self.assertFalse(warnings)
                self.assertEqual({c["tile"] for c in choices}, {"0p", "5p"})
        s = own_action("123m123p123s0p77z46p", 7, ["5p"])
        self.assertEqual([c["tile"] for c in _action_choices(s)[0]], ["0p"])
        self.assertEqual(get_action(s, "riichi")["tile"], "0p")
        s["forbiddenDiscards"] = ["5p"]
        self.assertEqual(_action_choices(s)[0], [])

    def test_no_riichi_without_points_or_from_open_hand(self):
        s = own_action("123m123p123s45s77z1z", 7, ["1z"])
        s["scores"][0] = 900
        self.assertFalse(any(c["action"] == "riichi" for c in advise(s)["candidates"]))
        s = own_action("123p123s45s77z1z", 7, ["1z"])
        s["melds"][0] = [{"type": 0, "tiles": tiles("123m")}]
        self.assertFalse(any(c["action"] == "riichi" for c in advise(s)["candidates"]))

    def test_double_riichi_and_locked_discard_remain_authoritative(self):
        s = own_action("123m123p123s45s77z1z", 7, ["1z"])
        normal = get_action(s, "riichi")
        s["canDoubleRiichi"] = True
        double = get_action(s, "riichi")
        self.assertTrue(double["doubleRiichi"])
        self.assertGreater(double["expectedWinPoints"], normal["expectedWinPoints"])
        s["riichi"][0] = True
        self.assertEqual([(c["action"], c["tile"]) for c in advise(s)["candidates"]], [("discard", "1z")])


class ReplacementAdviceTests(unittest.TestCase):
    def assert_replacement(self, s, action):
        original = deepcopy(s)
        c = get_action(s, action)
        self.assertEqual(s, original)
        self.assertTrue(c["replacementDraw"])
        self.assertNotIn("followupDiscard", c)
        self.assertEqual(sum(o["count"] for o in c["replacementOutcomes"]), sum(unseen_counts(s)))
        self.assertTrue(all(o["count"] > 0 for o in c["replacementOutcomes"]))
        self.assertTrue(0 <= c["winProbability"] <= 1)
        self.assertTrue(0 <= c["dealInProbability"] <= 1)
        return c

    def test_ankan_preserves_menzen_and_physical_counts(self):
        s = own_action("1111m234p456s77z12s", 4, ["1m|1m|1m|1m"])
        choice = _action_choices(s)[0][0]
        after = _apply_choice(s, choice)
        self.assertEqual(after["melds"][0][0]["type"], 3)
        self.assertEqual(unseen_counts(s), unseen_counts(after))
        c = self.assert_replacement(s, "ankan")
        self.assertGreater(c["newDoraRiskPenalty"], 0)
        self.assertGreater(c["robKanProbability"], 0)  # Kokushi exception for terminal kan.
        self.assertNotIn("1m", {o["draw"] for o in c["replacementOutcomes"]})

    def test_daiminkan_consumes_only_own_three_and_has_no_fake_followup(self):
        s = offered("111m234p456s77z12s", 5, ["1m|1m|1m"], "1m")
        c = self.assert_replacement(s, "daiminkan")
        self.assertEqual(len(c["consumed"]), 3)
        self.assertEqual(c["calledTile"], "1m")
        self.assertEqual(c["robKanProbability"], 0)
        choice = _action_choices(s)[0][0]
        self.assertEqual(unseen_counts(_apply_choice(s, choice)), unseen_counts(s))

    def test_added_kan_subtracts_existing_pon_and_keeps_red(self):
        s = own_action("0p123m456s77z12s", 6, ["0p|5p|5p|5p"])
        s["melds"][0] = [{"type": 1, "tiles": tiles("555p")}]
        choice = _action_choices(s)[0][0]
        self.assertEqual(choice["consumed"], ["0p"])
        after = _apply_choice(s, choice)
        self.assertEqual(after["melds"][0][0]["tiles"], tiles("5550p"))
        self.assertEqual(unseen_counts(after), unseen_counts(s))
        c = self.assert_replacement(s, "shouminkan")
        self.assertGreater(c["robKanProbability"], 0)

    def test_added_kan_without_matching_pon_is_not_invented(self):
        s = own_action("1111m234p456s77z12s", 6, ["1m|1m|1m|1m"])
        a = advise(s)
        self.assertFalse(any(c["action"] == "shouminkan" for c in a["candidates"]))
        self.assertTrue(a["warnings"])

    def test_kita_sanma_counts_bonus_and_never_draws_removed_tiles(self):
        s = own_action("123p123s789s45p77z4z", 11, [], players=3)
        choice = _action_choices(s)[0][0]
        after = _apply_choice(s, choice)
        self.assertEqual(after["north"][0], 1)
        self.assertEqual(unseen_counts(after), unseen_counts(s))
        c = self.assert_replacement(s, "kita")
        self.assertEqual(c["newDoraRiskPenalty"], 0)
        self.assertTrue(all(not (o["draw"].endswith("m") and o["draw"][0] not in "19") for o in c["replacementOutcomes"]))
        self.assertEqual(advise(s)["best"]["action"], "kita")
        s["playerCount"] = 4
        self.assertFalse(any(c["action"] == "kita" for c in advise(s)["candidates"]))

    def test_red_replacement_mass_is_split_without_creating_extra_copy(self):
        s = own_action("1111m234p456s77z12s", 4, ["1m|1m|1m|1m"])
        pool = dict(_draw_pool(s, unseen_counts(s)))
        self.assertEqual(pool["0p"], 1)
        self.assertEqual(pool["5p"], 3)
        self.assertEqual(sum(pool.values()), sum(unseen_counts(s)))
        s["rivers"][2] = [{"tile": "0p"}]
        pool = dict(_draw_pool(s, unseen_counts(s)))
        self.assertNotIn("0p", pool)
        self.assertEqual(pool["5p"], 3)

    def test_no_replacement_with_zero_wall_and_no_negative_unknown_counts(self):
        s = own_action("1111m234p456s77z12s", 4, ["1m|1m|1m|1m"])
        s["left"] = 0
        a = advise(s)
        self.assertFalse(any(c["action"] == "ankan" for c in a["candidates"]))
        s["rivers"][2] = [{"tile": "1m"}]
        self.assertEqual(advise(s)["status"], "unavailable")

    def test_riichi_ankan_uses_offered_choice_and_locks_each_replacement_discard(self):
        s = own_action("1111m234p456s77z12s", 4, ["1m|1m|1m|1m"])
        s["riichi"][0] = True
        s["lastDraw"] = "1m"
        c = self.assert_replacement(s, "ankan")
        self.assertTrue(all(o["followupDiscard"] in (None, o["draw"]) for o in c["replacementOutcomes"]))

    def test_representative_replacement_latency_under_one_second(self):
        s = own_action("0555p234m456s77z12s", 4, ["0p|5p|5p|5p"])
        a = advise(s)
        self.assertEqual(a["status"], "ready")
        self.assertTrue(any(c["action"] == "ankan" for c in a["candidates"]))
        self.assertLess(a["elapsedMs"], 1000)


class WindowAndIntegrityTests(unittest.TestCase):
    def test_idle_thirteen_tiles_get_analysis_and_recompute_after_change(self):
        s = state("123m123p123s45s77z")
        s.update(canDiscard=False, canAct=False, operations=[], lastDraw=None)
        before = advise(s)
        self.assertEqual(before["status"], "analysis")
        self.assertEqual(before["best"]["action"], "wait")
        self.assertEqual(before["best"]["shanten"], 0)
        s["hand"][-1] = "1z"
        after = advise(s)
        self.assertGreater(after["best"]["shanten"], before["best"]["shanten"])

    def test_integrity_gate_and_authoritative_win_before_optional_actions(self):
        s = offered("55z123m456p23s99p1z", 3, ["5z|5z"], "5z")
        s["operations"].append(9)
        self.assertEqual(advise(s)["action"], "ron")
        s["historyComplete"] = False
        self.assertEqual(advise(s)["status"], "unavailable")

    def test_malformed_optional_choice_preserves_discard_recommendation(self):
        s = own_action("123m123p123s45s77z1z", 7, ["bad"])
        s["operations"].append(99)
        a = advise(s)
        self.assertEqual(a["status"], "ready")
        self.assertTrue(all(c["action"] == "discard" for c in a["candidates"]))
        self.assertEqual(len(a["warnings"]), 2)

    def test_nine_terminals_abort_requires_server_operation(self):
        s = own_action("19m19p19s1234567z2p", 10, [])
        c = get_action(s, "abort")
        self.assertEqual(c["score"], 0)
        self.assertEqual(c["winProbability"], 0)
        self.assertIsNone(c["tile"])
        s["operations"] = [1]
        self.assertFalse(any(c["action"] == "abort" for c in advise(s)["candidates"]))


class ActionBoundaryRuleTests(unittest.TestCase):
    def test_added_kan_supplies_ron_eligibility_only_for_robbery(self):
        for tile, pon, points in (("0p", "555p", 2000), ("5p", "055p", 1000)):
            with self.subTest(tile=tile):
                s = own_action(tile + "123m456s77z12s", 6, ["0p|5p|5p|5p"])
                s["melds"][0] = [{"type": 1, "tiles": tiles(pon)}]
                s["melds"][1] = [{"type": 0, "tiles": tiles("123m")}]
                s["left"] = 4
                original = deepcopy(s)
                advice = advise(s)
                added = next(c for c in advice["candidates"] if c["action"] == "shouminkan")
                discarded = next(c for c in advice["candidates"]
                                 if c["action"] == "discard" and c["tile"] == tile)
                robbery = next(r for r in added["opponentRisks"] if r["seat"] == 1)
                ordinary = next(r for r in discarded["opponentRisks"] if r["seat"] == 1)
                self.assertEqual(ordinary["yakuConfidence"], .6)
                self.assertEqual(ordinary["probability"], .0108)
                self.assertEqual(robbery["yakuConfidence"], 1)
                self.assertEqual(robbery["probability"], .018)
                self.assertEqual(added["robKanProbability"], .0258)
                self.assertEqual(robbery["lossPoints"], points)
                self.assertEqual(ordinary["lossPoints"], points)
                self.assertAlmostEqual(sum(added["scoreBreakdown"].values()), added["score"], places=8)
                self.assertEqual(s, original)
                s["rivers"][1] = [{"tile": "5p", "called": True}]
                safe = get_action(s, "shouminkan")
                self.assertEqual(next(r for r in safe["opponentRisks"] if r["seat"] == 1)["probability"], 0)

    def test_kita_retains_unknown_yaku_eligibility_discount(self):
        s = own_action("123p123s789s45p77z4z", 11, [], players=3)
        s["melds"][1] = [{"type": 1, "tiles": tiles("999p")}]
        s["left"] = 4
        original = deepcopy(s)
        candidate = get_action(s, "kita")
        remaining = unseen_counts(s)
        ordinary = _danger("4z", remaining, _opponents(s, remaining))
        self.assertEqual(candidate["opponentRisks"], ordinary[2])
        self.assertEqual(candidate["robKanProbability"], round(ordinary[0], 4))
        self.assertEqual(candidate["opponentRisks"][0]["yakuConfidence"], .6)
        self.assertGreater(candidate["opponentRisks"][0]["probability"], 0)
        self.assertEqual(s, original)

    def test_kita_replacement_has_rinshan_yaku_for_otherwise_yakuless_open_hand(self):
        s = own_action("456p789s23s55z4z", 11, [], players=3)
        s["melds"][0] = [{"type": 1, "tiles": tiles("111p")}]
        c = get_action(s, "kita")
        for draw in ("1s", "4s"):
            outcome = next(o for o in c["replacementOutcomes"] if o["draw"] == draw)
            self.assertEqual(outcome["winProbability"], 1)
            self.assertIsNone(outcome["followupDiscard"])

    def test_kita_robbery_is_not_limited_to_closed_kokushi(self):
        s = own_action("123p123s789s45p77z4z", 11, [], players=3)
        s["melds"][1] = [{"type": 1, "tiles": tiles("555z")}]
        c = get_action(s, "kita")
        remaining = unseen_counts(s)
        expected = _danger("4z", remaining, _opponents(s, remaining))[0]
        self.assertAlmostEqual(c["robKanProbability"], expected, delta=.00005)
        self.assertTrue(any(o["seat"] == 1 and o["probability"] > 0 for o in c["opponentRisks"]))
        self.assertIn("不额外加入抢杠役", " ".join(c["reasons"]))

    def test_ankan_robbery_is_yakuman_and_respects_discard_furiten(self):
        s = own_action("1111m234p456s77z12s", 4, ["1m|1m|1m|1m"])
        c = get_action(s, "ankan")
        self.assertTrue(all(r["lossPoints"] >= 32000 for r in c["opponentRisks"]))
        s["riichi"][1] = True
        s["riichiStep"][1] = 1
        # Exercise the supplied safe-tile classification conservatively,
        # including river entries marked called rather than counted twice.
        s["rivers"][1] = [{"tile": "1m", "called": True}]
        c = get_action(s, "ankan")
        self.assertFalse(any(r["seat"] == 1 for r in c["opponentRisks"]))

    def test_locked_optional_windows_without_discard_operation_compare_skip(self):
        for hand, kind, combination, action, players in (
                ("1111m234p456s77z12s", 4, ["1m|1m|1m|1m"], "ankan", 4),
                ("123p123s789s45p77z4z", 11, [], "kita", 3)):
            with self.subTest(action=action):
                s = own_action(hand, kind, combination, players)
                s.update(operations=[kind], canDiscard=False)
                s["riichi"][0] = True
                a = advise(s)
                self.assertEqual(a["status"], "ready")
                self.assertEqual({c["action"] for c in a["candidates"]}, {"pass", action})
                skip = get_action(s, "pass")
                self.assertEqual(skip["followupDiscard"], s["lastDraw"])
                self.assertIsNone(skip["tile"])

    def test_four_kan_abort_stops_all_nonwinning_replacement_branches(self):
        s = own_action("1111m123p123s12s55z", 4, ["1m|1m|1m|1m"])
        s["melds"][1] = [{"type": 3, "tiles": tiles(t)} for t in ("7777m", "7777p", "9999p")]
        c = get_action(s, "ankan")
        self.assertTrue(c["abortAfterDiscard"])
        self.assertTrue(all(o["winProbability"] in (0, 1) for o in c["replacementOutcomes"]))
        nonwin = next(o for o in c["replacementOutcomes"] if o["draw"] == "2m")
        self.assertEqual(nonwin["winProbability"], 0)
        self.assertLess(c["winProbability"], .1)
        self.assertIn("无听牌料", " ".join(c["reasons"]))

    def test_four_kan_by_one_player_continues_but_fifth_is_rejected(self):
        s = own_action("1111m5z", 4, ["1m|1m|1m|1m"])
        s["melds"][0] = [{"type": 3, "tiles": tiles(t)} for t in ("7777m", "7777p", "9999p")]
        c = get_action(s, "ankan")
        self.assertFalse(c["abortAfterDiscard"])
        self.assertTrue(any(0 < o["winProbability"] < 1 for o in c["replacementOutcomes"]))
        s["melds"][1] = [{"type": 3, "tiles": tiles("4444s")}]
        self.assertFalse(any(c["action"] == "ankan" for c in advise(s)["candidates"]))

    def test_four_riichi_aborts_after_declaration_without_future_win_or_noten(self):
        s = own_action("123m123p123s45s77z1z", 7, ["1z"])
        s["riichi"] = [False, True, True, True]
        for seat in (1, 2, 3):
            s["rivers"][seat] = [{"tile": "1z"}]
        c = get_action(s, "riichi")
        self.assertTrue(c["abortAfterRiichi"])
        self.assertEqual(c["winProbability"], 0)
        self.assertEqual(c["futureForcedDealInLoss"], 0)
        self.assertEqual(c["score"], -1000)
        self.assertEqual(c["expectedRiichiCost"], 1000)

    def test_three_riichi_in_sanma_does_not_abort(self):
        s = own_action("123p123s789s45p77z1z", 7, ["1z"], players=3)
        s["riichi"] = [False, True, True, False]
        c = get_action(s, "riichi")
        self.assertFalse(c.get("abortAfterRiichi", False))
        self.assertGreater(c["winProbability"], 0)

    def test_weak_nine_kind_aborts_but_strong_kokushi_continues(self):
        weak = own_action("19m19p19s123z245p67s", 10, [])
        self.assertEqual(advise(weak)["best"]["action"], "abort")
        strong = own_action("119m19p19s123456z2p", 10, [])
        advice = advise(strong)
        self.assertEqual(advice["best"]["action"], "discard")
        # Full one-shanten search also values the furiten thirteen-sided
        # double-yakuman route; the old exact recommendation was a heuristic.
        ready = next(c for c in advice["candidates"] if c["tile"] == "2p")
        self.assertEqual(ready["shanten"], 0)
        self.assertGreater(ready["winProbability"], 0)
        self.assertEqual(ready["expectedWinPoints"], 48000)

    def test_abort_and_kita_share_point_scale_regardless_of_operation_order(self):
        s = own_action("19m19p19s124z245p67s", 10, [], players=3)
        s["operations"].append(11)
        s["operationDetails"].append({"type": 11, "combination": []})
        forward = advise(s)
        self.assertEqual(forward["best"]["action"], "abort")
        kita = get_action(s, "kita")
        self.assertLess(kita["score"], 0)
        self.assertIn("不计形状奖励", " ".join(kita["reasons"]))
        s["operations"].reverse()
        self.assertEqual([(c["actionId"], c["score"]) for c in advise(s)["candidates"]],
                         [(c["actionId"], c["score"]) for c in forward["candidates"]])


if __name__ == "__main__":
    unittest.main()
