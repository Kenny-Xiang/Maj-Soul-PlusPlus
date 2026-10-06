"""Published settlement amounts and conservative match-metadata boundaries."""
from copy import deepcopy
import unittest

from advisor_rank import profile_for_match, settlement_points


def match(mode=12, room=4, level=10401, players=4, winds=2):
    return {"source": "auth-game", "category": 2, "modeId": mode,
            "room": room, "levelId": level, "levelIds": [level] * players,
            "playerCount": players, "roundCount": winds}


class RankRulesTests(unittest.TestCase):
    def test_gold_and_jade_south_examples_keep_raw_score_separate(self):
        examples = (
            (match(9, 3, 10301), [110, 50, -10, -110]),
            (match(9, 3, 10303), [110, 50, -10, -150]),
            (match(12, 4, 10401), [140, 65, -10, -195]),
            (match(12, 4, 10503), [140, 65, -10, -270]),
        )
        for metadata, expected in examples:
            with self.subTest(level=metadata["levelId"], mode=metadata["modeId"]):
                profile = profile_for_match(metadata, 4)
                self.assertEqual([settlement_points(profile, score, place)
                                  for place, score in enumerate((40000, 30000, 20000, 10000), 1)], expected)

    def test_east_room_rewards_are_not_blindly_half_south(self):
        profile = profile_for_match(match(11, 4, 10401, winds=1), 4)
        self.assertEqual(profile["placementPoints"], [70, 35, -5, -95])
        self.assertEqual(profile["scoreOrigin"], 25000)
        self.assertEqual(profile["roundCount"], 1)

    def test_lower_rooms_and_throne_use_their_own_rewards(self):
        for metadata, points in (
            (match(2, 1, 10201, winds=1), [25, 10, -5, -25]),
            (match(3, 1, 10203), [35, 15, -5, -75]),
            (match(5, 2, 10302, winds=1), [35, 15, -5, -65]),
            (match(6, 2, 10302), [55, 25, -5, -115]),
            (match(15, 6, 10503, winds=1), [75, 35, -5, -145]),
            (match(16, 6, 10503), [135, 65, -5, -255]),
        ):
            with self.subTest(mode=metadata["modeId"]):
                self.assertEqual(profile_for_match(metadata, 4)["placementPoints"], points)

    def test_three_player_origin_and_penalties_are_distinct(self):
        gold = profile_for_match(match(22, 3, 20303, 3), 3)
        jade = profile_for_match(match(24, 4, 20402, 3), 3)
        self.assertEqual(gold["placementPoints"], [120, 0, -135])
        self.assertEqual(jade["placementPoints"], [175, 0, -205])
        self.assertEqual(jade["scoreOrigin"], 35000)
        self.assertEqual(settlement_points(jade, 35000, 2), 0)
        self.assertEqual(settlement_points(jade, 10000, 3), -230)
        east = profile_for_match(match(23, 4, 20503, 3, 1), 3)
        self.assertEqual(east["placementPoints"], [90, 0, -175])

    def test_modern_celestial_ignores_score_and_doubles_only_complete_table(self):
        metadata = match(16, 6, 10701)
        metadata["levelIds"] = [10701, 10503, 10720, 10501]
        profile = profile_for_match(metadata, 4)
        self.assertEqual(profile["unit"], "soul")
        self.assertIsNone(profile["scoreDivisor"])
        self.assertEqual(profile["placementPoints"], [.5, .2, -.2, -.5])
        self.assertEqual(settlement_points(profile, -100000, 4), -.5)
        self.assertEqual(settlement_points(profile, 100000, 4), -.5)
        metadata["levelIds"] = [10701, 10702, 10719, 10720]
        self.assertEqual(profile_for_match(metadata, 4)["placementPoints"], [1., .4, -.4, -1.])
        metadata["levelIds"][2] = None
        self.assertIsNone(profile_for_match(metadata, 4))
        metadata["levelIds"] = [10701] * 3
        self.assertIsNone(profile_for_match(metadata, 4))

    def test_celestial_east_and_three_player(self):
        self.assertEqual(profile_for_match(match(15, 6, 10720, winds=1), 4)["placementPoints"], [.6, .2, -.2, -.6])
        metadata = match(26, 6, 20701, 3)
        metadata["levelIds"] = [20701, 20503, 20701]
        self.assertEqual(profile_for_match(metadata, 3)["placementPoints"], [.5, 0, -.5])
        self.assertEqual(profile_for_match(match(25, 6, 20701, 3, 1), 3)["placementPoints"], [.6, 0, -.6])

    def test_partial_conflicting_nonranked_and_unsupported_metadata_fall_back(self):
        for metadata in (None, {}, [], "ranked"):
            self.assertIsNone(profile_for_match(metadata, 4))
        original = match()
        for key, value in (
            ("source", "inferred"), ("category", 1), ("category", True),
            ("modeId", 14), ("modeId", "12"), ("room", 3),
            ("playerCount", 3), ("roundCount", 1), ("roundCount", True),
            ("levelId", 20401), ("levelId", 10301), ("levelId", 10404),
            ("levelId", "10401"), ("levelId", None),
        ):
            metadata = {**original, key: value}
            with self.subTest(field=key, value=value):
                self.assertIsNone(profile_for_match(metadata, 4))
        self.assertIsNone(profile_for_match(original, 3))
        for level in (10101, 10102, 10103):
            self.assertIsNone(profile_for_match(match(3, 1, level), 4))
        self.assertIsNone(profile_for_match(match(16, 6, 10601), 4))
        self.assertIsNone(profile_for_match(match(26, 6, 20601, 3), 3))

    def test_profile_does_not_mutate_or_depend_on_other_regular_player_ranks(self):
        metadata = match()
        metadata["levelIds"] = [10401, None, None, None]
        before = deepcopy(metadata)
        self.assertIsNotNone(profile_for_match(metadata, 4))
        self.assertEqual(metadata, before)

    def test_fractional_points_round_up_including_negative_values(self):
        profile = profile_for_match(match(), 4)
        # Public client-result examples linked in docs/rank-point-rules.md.
        self.assertEqual(settlement_points(profile, 46900, 1), 147)
        silver_east = profile_for_match(match(5, 2, 10203, winds=1), 4)
        self.assertEqual(settlement_points(silver_east, 48600, 1), 59)
        self.assertEqual(settlement_points(profile, 32200, 1), 133)
        self.assertEqual(settlement_points(profile, 24100, 3), -5)
        self.assertEqual(settlement_points(profile, 23900, 3), -6)
        self.assertEqual(settlement_points(profile, -1100, 4), -206)

    def test_places_are_explicit_and_rank_balance_is_not_clamped(self):
        profile = profile_for_match(match(3, 1, 10201), 4)
        self.assertEqual(settlement_points(profile, 10000, 4), -50)
        for place in (0, 5, -1, 1.5, True):
            with self.assertRaises(ValueError):
                settlement_points(profile, 25000, place)
        for score in (None, True, "25000", float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                settlement_points(profile, score, 1)


if __name__ == "__main__":
    unittest.main()
