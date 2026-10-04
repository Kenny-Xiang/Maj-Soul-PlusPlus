"""Rule, availability, risk and model sanity regressions for discard advice."""
from copy import deepcopy
import json
from pathlib import Path
import re
import unittest

from advisor import (advise, counts34, shanten, unseen_counts, tile_index,
                     _config, _hand_value, _points, _structural_waits,
                     _opponents, _danger, _win_model)


def tiles(text):
    return [n + suit for digits, suit in re.findall(r"([0-9]+)([mpsz])", text) for n in digits]


def state(hand="123m123p123s45s77z1z", players=4):
    return {"phase": "playing", "selfSeat": 0, "playerCount": players,
            "hand": tiles(hand), "handComplete": True, "historyComplete": True,
            "canDiscard": True, "operations": [1], "forbiddenDiscards": [],
            "melds": [[], [], [], []], "rivers": [[], [], [], []],
            "north": [0] * 4, "riichi": [False] * 4,
            "riichiPending": [False] * 4, "riichiStep": [None] * 4,
            "round": {"chang": 0, "ju": 0, "ben": 0}, "left": 48,
            "doras": [], "scores": [25000] * players, "lastStep": 40,
            "lastDraw": "1z", "furiten": False, "riichiSticks": 0}


def candidate(s, tile):
    advice = advise(s)
    if advice["status"] != "ready":
        raise AssertionError(advice)
    return next(c for c in advice["candidates"] if c["tile"] == tile)


class ShantenAndVisibilityTests(unittest.TestCase):
    def test_normal_chiitoitsu_kokushi_complete_and_tenpai(self):
        for hand in ("123m123p123s45s77z", "11m22p33p44s66s11z7z", "19m19p19s1234567z"):
            with self.subTest(hand=hand):
                self.assertEqual(shanten(counts34(tiles(hand))), 0)
        for hand in ("123m123p123s456s77z", "11m22p33p44s66s11z77z", "119m19p19s1234567z"):
            self.assertEqual(shanten(counts34(tiles(hand))), -1)

    def test_ukeire_counts_public_copies_and_never_discards_as_unknown(self):
        s = state()
        c = candidate(s, "1z")
        self.assertEqual({w["tile"]: w["count"] for w in c["improvingTiles"]}, {"3s": 3, "6s": 4})
        s["rivers"][1] = [{"tile": "6s"}, {"tile": "6s"}, {"tile": "3s"}]
        self.assertEqual(candidate(s, "1z")["ukeire"], 4)
        self.assertEqual(unseen_counts(s)[tile_index("1z")], 3)

    def test_called_tile_counted_once_and_north_not_in_wall(self):
        s = state()
        s["rivers"][1] = [{"tile": "9p", "called": True}]
        s["melds"][2] = [{"type": 1, "tiles": tiles("999p")}]
        s["north"][3] = 2
        self.assertEqual(unseen_counts(s)[tile_index("9p")], 1)
        self.assertEqual(unseen_counts(s)[tile_index("4z")], 2)

    def test_sanma_removed_tiles_and_too_many_tiles(self):
        s = state("123p123s789s45p77z1z", 3)
        self.assertEqual(unseen_counts(s)[1:8], (0,) * 7)
        s["hand"][0] = "2m"
        self.assertEqual(advise(s)["status"], "unavailable")

    def test_structural_fifth_tile_in_own_meld_is_excluded(self):
        concealed = counts34(tiles("1p123s456s789s"))
        meld = counts34(tiles("111p"))
        self.assertEqual(_structural_waits(concealed, False, 4, meld), [])
        s = state("1p123s456s789s1z")
        s["melds"][0] = [{"type": 1, "tiles": tiles("111p")}]
        self.assertEqual(advise(s)["status"], "ready")
        self.assertEqual(candidate(s, "1z")["winningTiles"], [])


class ScoringTests(unittest.TestCase):
    def test_no_yaku_open_hand_cannot_win_on_dora_alone(self):
        s = state("456p789s23s55z9m")
        s["melds"][0] = [{"type": 0, "tiles": tiles("123m")}]
        s["doras"] = ["2s"]
        c = candidate(s, "9m")
        self.assertEqual(c["shanten"], 0)
        self.assertEqual(c["winProbability"], 0)
        self.assertEqual(c["expectedWinPoints"], 0)
        self.assertTrue(all(w["ronPoints"] == w["tsumoPoints"] == 0 for w in c["winningTiles"]))

    def test_furiten_applies_to_whole_wait_even_exhausted_called_tile(self):
        s = state()
        s["rivers"][0] = [{"tile": "3s", "called": True}]
        s["melds"][1] = [{"type": 1, "tiles": tiles("333s")}]
        c = candidate(s, "1z")
        self.assertTrue(c["furiten"])
        self.assertEqual(next(w for w in c["winningTiles"] if w["tile"] == "3s")["count"], 0)
        self.assertTrue(all(w["ronPoints"] == 0 for w in c["winningTiles"]))
        self.assertGreater(next(w for w in c["winningTiles"] if w["tile"] == "6s")["tsumoPoints"], 0)

    def test_server_furiten_and_candidate_discard_both_apply(self):
        s = state()
        s["furiten"] = True
        s["lastDraw"] = None
        self.assertTrue(candidate(s, "1z")["furiten"])
        s = state("123m123p123s45s77z6s")
        self.assertTrue(candidate(s, "6s")["furiten"])

    def test_normal_draw_wait_change_can_clear_discard_furiten(self):
        s = state("11223344556679m")
        s["lastDraw"] = "9m"
        s["rivers"][0] = [{"tile": "1m"}]
        s["furiten"] = True
        self.assertTrue(candidate(s, "9m")["furiten"])
        self.assertFalse(candidate(s, "7m")["furiten"])

    def test_held_red_and_red_winning_tile_score_additional_han(self):
        s = state()
        plain = _hand_value(tiles("234m234p678s34p55s"), "2p", s, False)
        red = _hand_value(tiles("234m234p678s34p05s"), "2p", s, False)
        self.assertEqual(red["han"], plain["han"] + 1)
        self.assertGreater(red["points"], plain["points"])
        s = state("234m234p678s34p55s1z")
        wait = next(w for w in candidate(s, "1z")["winningTiles"] if w["tile"] == "5p")
        self.assertEqual(wait["redCount"], 1)
        self.assertGreater(wait["redRonPoints"], wait["normalRonPoints"])

    def test_sanma_dora_cycle_nuki_and_tsumo_loss(self):
        s = state("111m999m123p55z45s1z", 3)
        hand = tiles("111m999m123p55z45s")
        s["riichi"][0] = True
        plain = _hand_value(hand, "6s", s, False)
        s["doras"] = ["1m"]
        dora = _hand_value(hand, "6s", s, False)
        self.assertEqual(dora["han"], plain["han"] + 3)
        s["doras"] = ["3z"]  # North is indicated dora as well as nuki dora.
        s["north"][0] = 1
        nuki = _hand_value(hand, "6s", s, False)
        self.assertEqual(nuki["han"], plain["han"] + 2)
        cfg = _config(s, True)
        self.assertEqual(_points(5, 30, cfg, 3), 8000)
        self.assertEqual(_points(5, 30, cfg, 4), 12000)

    def test_honba_deposits_and_wind_rotation(self):
        s = state(players=3)
        s["round"].update(ju=2, chang=1, ben=2)
        s["riichiSticks"] = 2
        cfg = _config(s)
        self.assertEqual(cfg.player_wind, 28)
        self.assertEqual(cfg.round_wind, 28)
        self.assertEqual(_points(1, 30, cfg, 3), 3400)  # 1000 + 400 + 2000
        s["hand"] = tiles("123p123s789s45p77z1z")
        enemy = _opponents(s, unseen_counts(s))[0]
        no_sticks = deepcopy(s)
        no_sticks["riichiSticks"] = 0
        self.assertEqual(enemy["loss"], _opponents(no_sticks, unseen_counts(no_sticks))[0]["loss"])

    def test_near_kokushi_projects_yakuman_route_and_double_riichi_scores(self):
        s = state("119m19p19s123456z2p")
        c = candidate(s, "2p")
        self.assertEqual(c["shanten"], 0)
        self.assertGreaterEqual(c["expectedWinPoints"], 32000)
        s = state("119m19p19s12345z23p")
        c = candidate(s, "2p")
        self.assertEqual(c["shanten"], 1)
        self.assertEqual(c["expectedWinPoints"], 48000)
        self.assertIn(advise(s)["best"]["tile"], ("2p", "3p"))
        s = state()
        s["riichi"][0] = True
        one = _hand_value(tiles("123m123p123s45s77z"), "6s", s, False)
        s["doubleRiichi"] = [True, False, False, False]
        double = _hand_value(tiles("123m123p123s45s77z"), "6s", s, False)
        self.assertEqual(double["han"], one["han"] + 1)


class AvailabilityAndRiskTests(unittest.TestCase):
    def test_gate_and_server_win_priority(self):
        for key, value in (("handComplete", False), ("historyComplete", False), ("round", None), ("left", None)):
            s = state()
            s[key] = value
            self.assertEqual(advise(s)["status"], "unavailable", key)
        s = state()
        s["canDiscard"] = False
        self.assertEqual(advise(s)["status"], "waiting")
        s["operations"] = [9]
        self.assertEqual(advise(s)["status"], "win")
        s["operations"] = [1, 8]
        self.assertEqual(advise(s)["action"], "tsumo")

    def test_kuikae_and_post_riichi_are_legal_only(self):
        s = state()
        s["forbiddenDiscards"] = ["1z"]
        self.assertNotIn("1z", [c["tile"] for c in advise(s)["candidates"]])
        s["forbiddenDiscards"] = []
        s["riichi"][0] = True
        self.assertEqual([c["tile"] for c in advise(s)["candidates"]], ["1z"])
        s["lastDraw"] = None
        self.assertEqual(advise(s)["status"], "unavailable")

    def test_genbutsu_suji_and_post_riichi_safe_tiles(self):
        s = state()
        s["riichi"][1] = True
        s["riichiStep"][1] = 20
        s["rivers"][1] = [{"tile": "4p", "step": 19}]
        s["rivers"][2] = [{"tile": "9p", "step": 21}, {"tile": "8p", "step": 40}]
        remaining = unseen_counts(s)
        enemy = _opponents(s, remaining)[:1]
        self.assertEqual(_danger("4p", remaining, enemy)[0], 0)
        self.assertEqual(_danger("9p", remaining, enemy)[0], 0)
        self.assertGreater(_danger("8p", remaining, enemy)[0], 0)
        self.assertGreater(_danger("1p", remaining, enemy)[0], 0)
        self.assertLess(_danger("1p", remaining, enemy)[0], _danger("2p", remaining, enemy)[0])

    def test_exhausted_honor_still_has_small_kokushi_risk(self):
        s = state()
        s["rivers"][2] = [{"tile": "1z"}] * 3
        s["riichi"][1] = True
        remaining = unseen_counts(s)
        enemy = _opponents(s, remaining)[:1]
        risk = _danger("1z", remaining, enemy)[0]
        self.assertGreater(risk, 0)
        self.assertLess(risk, .01)

    def test_defensive_choice_against_riichi_when_far_from_ready(self):
        s = state("147m147p147s12345z")
        s["left"] = 8
        for i in (1, 2, 3):
            s["riichi"][i] = True
            s["rivers"][i] = [{"tile": "1m"}]
        a = advise(s)
        self.assertEqual(a["status"], "ready")
        self.assertEqual(a["best"]["tile"], "1m")
        self.assertEqual(a["best"]["dealInProbability"], 0)

    def test_partial_cycle_still_has_ron_chance(self):
        s = state()
        s["left"] = 1
        c = candidate(s, "1z")
        self.assertGreater(c["winProbability"], 0)
        s["furiten"] = True
        s["lastDraw"] = None
        self.assertEqual(candidate(s, "1z")["winProbability"], 0)

    def test_model_sanity_and_live_fixture_latency(self):
        s = json.loads((Path(__file__).parent / "fixtures/turn.json").read_text())["state"]
        s.update(operations=[1], canDiscard=True)
        a = advise(s)
        self.assertEqual(a["status"], "ready")
        self.assertEqual(a["best"]["shanten"], min(c["shanten"] for c in a["candidates"]))
        self.assertLess(a["elapsedMs"], 1000)
        for c in a["candidates"]:
            self.assertTrue(0 <= c["winProbability"] <= 1)
            self.assertTrue(0 <= c["dealInProbability"] <= 1)
        probabilities = [_win_model(sh, 12, 90, 10, [], None)[0] for sh in (1, 2, 3)]
        self.assertEqual(probabilities, sorted(probabilities, reverse=True))


if __name__ == "__main__":
    unittest.main()
