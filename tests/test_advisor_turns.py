"""Finite turn order and consistent probability/value regression probes."""
from copy import deepcopy
import unittest

import advisor
from test_advisor import state
from test_advisor_actions import offered


class TurnOpportunityTests(unittest.TestCase):
    def test_skip_before_last_own_draw_keeps_tsumo_chance(self):
        s = offered("78m123p456s55z789p", 2, ["7m|8m"], "9m", source=3)
        s["left"] = 1
        result = advisor.advise(s)
        skip = next(c for c in result["candidates"] if c["action"] == "pass")
        call = next(c for c in result["candidates"] if c["action"] == "chi")
        self.assertEqual(result["remainingOwnDraws"], 1)
        self.assertGreater(skip["winProbability"], 0)
        self.assertEqual(advisor._opportunities(s), (0,))
        self.assertIsNotNone(call["followupDiscard"])
        self.assertEqual(advisor._opportunities(s, after_discard=True), (1,))

    def test_rotated_three_and_four_player_order(self):
        for players in (3, 4):
            for seat in range(players):
                for source in range(players):
                    with self.subTest(players=players, seat=seat, source=source):
                        s = state(players=players)
                        s.update(selfSeat=seat, left=players + 1,
                                 lastAction={"name": "ActionDiscardTile", "seat": source, "step": 40})
                        expected = tuple((source + offset) % players for offset in range(1, players + 2))
                        self.assertEqual(advisor._opportunities(s), expected)
                        expected_own = tuple((seat + offset) % players for offset in range(1, players + 2))
                        self.assertEqual(advisor._opportunities(s, after_discard=True), expected_own)

    def test_pending_discard_survives_empty_wall(self):
        for name, kind in (("ActionDealTile", None), ("ActionNewRound", None),
                           ("ActionChiPengGang", 0), ("ActionChiPengGang", 1)):
            with self.subTest(name=name, kind=kind):
                s = state()
                s.update(left=0, lastAction={"name": name, "seat": 2, "type": kind, "step": 40})
                self.assertEqual(advisor._opportunities(s), (2,))
                s["lastAction"]["name"] = "ActionDiscardTile"
                self.assertEqual(advisor._opportunities(s), ())

    def test_pending_replacement_consumes_wall_and_keeps_actor(self):
        for players in (3, 4):
            for name, kind in (("ActionAnGangAddGang", 2), ("ActionAnGangAddGang", 3),
                               ("ActionChiPengGang", 2), ("ActionBaBei", None)):
                with self.subTest(players=players, name=name, kind=kind):
                    s = state(players=players)
                    s.update(left=2, lastAction={"name": name, "seat": players - 1,
                                                "type": kind, "step": 40})
                    self.assertEqual(advisor._opportunities(s), (players - 1, 0))
                    s["left"] = 0
                    self.assertEqual(advisor._opportunities(s), ())

    def test_idle_pending_last_enemy_discard_can_win(self):
        s = state("123m123p123s45s77z")
        s.update(canAct=False, canDiscard=False, operations=[], lastDraw=None, left=0,
                 lastAction={"name": "ActionDealTile", "seat": 1, "step": 40})
        result = advisor.advise(s)
        self.assertEqual(result["status"], "analysis")
        self.assertEqual(result["remainingOwnDraws"], 0)
        self.assertGreater(result["best"]["winProbability"], 0)
        s["lastAction"]["name"] = "ActionDiscardTile"
        after = advisor.advise(s)
        self.assertEqual(after["best"]["winProbability"], 0)
        self.assertEqual(after["best"]["expectedWinPoints"], 0)

    def test_legal_zero_horizon_chi_has_no_no_yaku_penalty(self):
        s = offered("555z123m456p12s9p1z", 2, ["1s|2s"], "3s")
        s["left"] = 0
        result = advisor.advise(s)
        chi = next(c for c in result["candidates"] if c["action"] == "chi")
        self.assertEqual(chi["shanten"], 0)
        self.assertEqual(chi["winProbability"], 0)
        self.assertEqual(chi["expectedWinPoints"], 0)
        self.assertTrue(any(w["ronPoints"] for w in chi["winningTiles"]))
        after = advisor._apply_choice(s, advisor._action_choices(s)[0][0])
        hand = after["hand"].copy()
        hand.remove(chi["followupDiscard"])
        base = advisor._position(hand, after, advisor.unseen_counts(after), chi["followupDiscard"])
        self.assertEqual(chi["score"], base["score"])
        self.assertNotIn("另计无役路线代价", " ".join(chi["reasons"]))


class WinValueWeightTests(unittest.TestCase):
    def setUp(self):
        self.opponents = [{"seat": i, "tenpai": 0.} for i in (1, 2, 3)]

    def test_broad_equal_value_waits_never_inflate_conditional_points(self):
        # A mathematical model probe, with <= four unseen copies per tile.
        waits = [{"tile": tile, "count": 4 if i < 9 else 3,
                  "tsumoPoints": 96000, "ronPoints": 96000}
                 for i, tile in enumerate(advisor.TILES[:10])]
        probability, points = advisor._win_model(0, 39, 54, 1, self.opponents, waits)
        self.assertGreater(probability, 0)
        self.assertLessEqual(probability, 1)
        self.assertAlmostEqual(points, 96000)

    def test_mixed_values_stay_inside_reachable_range(self):
        waits = [{"count": 4, "tsumoPoints": 1000, "ronPoints": 8000},
                 {"count": 3, "tsumoPoints": 16000, "ronPoints": 0}]
        for events in ((), (0,), (1,), (1, 2, 3, 0), (0, 1, 2, 3) * 5):
            with self.subTest(events=events):
                probability, points = advisor._win_model(
                    0, 7, 14, 0, self.opponents, waits, opportunities=events, own_seat=0)
                self.assertGreaterEqual(probability, 0)
                self.assertLessEqual(probability, 1)
                if probability:
                    self.assertGreaterEqual(points, 1000)
                    self.assertLessEqual(points, 16000)
                else:
                    self.assertEqual(points, 0)

    def test_own_only_wait_cannot_win_on_enemy_discard(self):
        waits = [{"count": 4, "tsumoPoints": 4000, "ronPoints": 0}]
        self.assertEqual(advisor._win_model(0, 4, 40, 0, self.opponents, waits,
                                           opportunities=(1,), own_seat=0), (0, 0))
        probability, points = advisor._win_model(0, 4, 40, 0, self.opponents, waits,
                                                 opportunities=(0,), own_seat=0)
        self.assertAlmostEqual(probability, .1)
        self.assertEqual(points, 4000)

    def test_full_cycle_keeps_original_competition_survival(self):
        waits = [{"count": 4, "tsumoPoints": 4000, "ronPoints": 0}]
        probability, _ = advisor._win_model(0, 4, 40, 0, self.opponents, waits,
                                            opportunities=(0, 1, 2, 3, 0), own_seat=0)
        self.assertAlmostEqual(probability, .1 + .9 * (1 - .025) * .1)

    def test_generic_progression_respects_event_order(self):
        args = (1, 12, 90, 0, self.opponents, None)
        before, _ = advisor._win_model(*args, opportunities=(1, 0), own_seat=0)
        after, _ = advisor._win_model(*args, opportunities=(0, 1), own_seat=0)
        self.assertEqual(before, 0)
        self.assertGreater(after, 0)

    def test_kokushi_progression_respects_event_order(self):
        s = state("119m19p19s12345z23p")
        hand = deepcopy(s["hand"])
        hand.remove("2p")
        args = (advisor.counts34(hand), advisor.unseen_counts(s), 0,
                self.opponents, s, "2p", 0)
        before = advisor._kokushi_probability(*args, opportunities=(1, 0))
        after = advisor._kokushi_probability(*args, opportunities=(0, 1))
        self.assertEqual(before, 0)
        self.assertGreater(after, 0)


if __name__ == "__main__":
    unittest.main()
