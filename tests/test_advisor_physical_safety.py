"""Physical ron exclusions: rule checks, never fitted risk estimates."""
from copy import deepcopy
import unittest

from advisor import ORPHANS, _danger, _opponents, unseen_counts, tile_index
from test_advisor import state, tiles
from test_advisor_risk_rules import enemy_risk


def exhausted_five_position():
    """Four rounds, seat 3's white called by seat 1, then play returns to us."""
    s = state("123m123s789s22z55p1z")
    s.update(doras=["9m"], left=51, lastStep=39, lastDraw="1z",
             lastAction={"name": "ActionDealTile", "seat": 0, "step": 39})
    s["melds"][1] = [{"type": 1, "tiles": tiles("555z"), "froms": [1, 1, 3]}]
    for seat, (river, steps) in enumerate((
            ("4466p", [2, 10, 18, 26]),
            ("3467m1p", [4, 12, 20, 28, 34]),
            ("456p7z2p", [6, 14, 22, 30, 36]),
            ("406p5z3p", [8, 16, 24, 32, 38]))):
        s["rivers"][seat] = [
            {"tile": tile, "step": step, "called": seat == 3 and step == 32,
             "moqie": not (seat == 1 and step == 34)}
            for tile, step in zip(tiles(river), steps)]
    return s


class PhysicalSafetyTests(unittest.TestCase):
    def test_reachable_exhausted_five_is_safe_to_every_opponent(self):
        s = exhausted_five_position()
        before = deepcopy(s)
        remaining = unseen_counts(s)
        self.assertEqual(tuple(remaining[tile_index(t)] for t in ("4p", "5p", "6p")), (0, 0, 0))
        danger = _danger("5p", remaining, _opponents(s, remaining))
        self.assertEqual(danger[:2], (0., 0.))
        self.assertTrue(all(d["conditionalRonProbability"] == d["probability"] == 0 for d in danger[2]))
        self.assertEqual(s, before)

    def test_red_and_normal_copy_share_absolute_safety(self):
        s = exhausted_five_position()
        # Move the unique red from seat 3's river into our own hand.
        s["rivers"][3][1]["tile"] = "5p"
        s["hand"][s["hand"].index("5p")] = "0p"
        remaining = unseen_counts(s)
        enemies = _opponents(s, remaining)
        for tile in ("5p", "0p"):
            self.assertEqual(_danger(tile, remaining, enemies)[:2], (0., 0.))

    def test_exhausted_number_requires_every_sequence_to_be_blocked(self):
        for players in (3, 4):
            s = state("123s456s789s22z5p1m9m", players)
            s["melds"][1] = [{"type": 1, "tiles": tiles("555z")}]
            remaining = list(unseen_counts(s))
            for n in range(9, 18):
                remaining[n] = 0
            enemy = _opponents(s, remaining)[:1]
            self.assertEqual(_danger("5p", remaining, enemy)[:2], (0., 0.))
            for companions in (("3p", "4p"), ("4p", "6p"), ("6p", "7p")):
                with self.subTest(players=players, companions=companions):
                    trial = remaining.copy()
                    for tile in companions:
                        trial[tile_index(tile)] = 1
                    self.assertGreater(_danger("5p", trial, enemy)[0], 0.)
            remaining[tile_index("5p")] = 1
            self.assertGreater(_danger("5p", remaining, enemy)[0], 0.)

    def test_suji_or_one_wall_does_not_prove_safety(self):
        s = state("123s456s789s22z5p1m9m")
        s["riichi"][1] = True
        s["rivers"][1] = [{"tile": "2p"}, {"tile": "8p"}]
        s["rivers"][2] = [{"tile": "4p"}] * 4
        enemy, danger = enemy_risk(s, "5p")
        self.assertGreater(danger[0], 0.)  # Pair and 67 sequence remain possible.
        remaining = list(unseen_counts(s))
        remaining[tile_index("5p")] = 0
        self.assertGreater(_danger("5p", remaining, [enemy])[0], 0.)

    def test_four_melds_only_allow_an_available_singleton(self):
        s = state("123s456s789s22z5p1m9m")
        s["melds"][1] = [{"type": 1, "tiles": tiles(t)} for t in ("111z", "333z", "555z", "666z")]
        remaining = list(unseen_counts(s))
        enemy = _opponents(s, remaining)[:1]
        self.assertGreater(_danger("5p", remaining, enemy)[0], 0.)
        remaining[tile_index("5p")] = 0
        self.assertEqual(_danger("5p", remaining, enemy)[:2], (0., 0.))

    def test_kokushi_exception_needs_all_other_orphans_and_a_pair(self):
        for players, tile in ((3, "1m"), (4, "1z"), (4, "1m")):
            with self.subTest(players=players, tile=tile):
                s = state("123p456p789s22z" + tile + "7z9s", players)
                remaining = list(unseen_counts(s))
                remaining[tile_index(tile)] = 0
                # For four-player terminals block all sequence companions too.
                if tile == "1m":
                    remaining[1] = remaining[2] = 0
                enemy = _opponents(s, remaining)[:1]
                self.assertGreater(_danger(tile, remaining, enemy)[0], 0.)
                remaining[tile_index("9m")] = 0
                self.assertEqual(_danger(tile, remaining, enemy)[:2], (0., 0.))
                for index in ORPHANS:
                    remaining[index] = int(index != tile_index(tile))
                self.assertEqual(_danger(tile, remaining, enemy)[:2], (0., 0.))
                remaining[tile_index("9m")] = 2
                self.assertGreater(_danger(tile, remaining, enemy)[0], 0.)


if __name__ == "__main__":
    unittest.main()
