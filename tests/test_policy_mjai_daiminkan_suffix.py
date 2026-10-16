"""Bounded open-kan replay recovery: exact prefixes and replacement contexts."""
from collections import Counter
from copy import deepcopy
import unittest

from test_policy_mjai_review import discard, draw, riichienv


GAME_ID = "2016101600gm-00b9-0000-01234567"


def opening(players, required, draws, indicators=("N",)):
    pool = Counter({f"{n}{s}": 4 for s in "mps" for n in range(1, 10)
                    if players == 4 or s != "m" or n in (1, 9)})
    for suit in ("mps" if players == 4 else "ps"):
        pool["5" + suit], pool["5" + suit + "r"] = 3, 1
    pool.update({tile: 4 for tile in ("E", "S", "W", "N", "P", "F", "C")})
    hands = deepcopy(required)
    for tile in [*indicators, *draws, *(tile for hand in hands for tile in hand)]:
        pool[tile] -= 1
        assert pool[tile] >= 0, tile
    for hand in hands:
        assert len(hand) <= 13
        while len(hand) < 13:
            tile = next(tile for tile, count in pool.items() if count)
            pool[tile] -= 1
            hand.append(tile)
    metadata = None
    header = {"type": "start_game", "names": ["synthetic"] * players}
    if players == 3:
        metadata = {"schemaVersion": 1, "sourcePlatform": "tenhou", "gameId": GAME_ID,
                    "playerCount": 3, "goType": 185, "roundCount": 2,
                    "sourceCompressedSha256": "1" * 64,
                    "provenance": {"kind": "tenhou-xml-header", "archive": "synthetic-kan",
                                   "xmlSha256": "2" * 64}}
        header["_tenhou"] = {"game_id": GAME_ID, "GO": {"type": "185"}, "xml_sha256": "2" * 64}
    return [header, {"type": "start_kyoku", "bakaze": "E", "kyoku": 1, "honba": 0,
                     "kyotaku": 0, "oya": 0, "scores": [35000 if players == 3 else 25000] * players,
                     "dora_marker": indicators[0], "tehais": hands}], metadata


def finish(events, players):
    return events + [{"type": "ryukyoku", "deltas": [0] * players},
                     {"type": "end_kyoku"}, {"type": "end_game"}]


def kan(actor=1, target=0, tile="1m"):
    return {"type": "daiminkan", "actor": actor, "target": target,
            "pai": tile, "consumed": [tile] * 3}


@unittest.skipIf(riichienv is None, "install conversion dependencies for open-kan replay checks")
class DaiminkanSuffixTests(unittest.TestCase):
    def extract(self, events, metadata):
        from policy_mjai import extract_game
        return extract_game(events, GAME_ID, match_metadata=metadata)

    def at(self, samples, step, seat=1):
        return next(s for s in samples if s["state"]["lastStep"] == step and s["seat"] == seat)

    def kinds(self, sample):
        from policy_actions import legal_actions
        return {a["action"] for a in legal_actions(sample["state"])}

    def no_yaku_prefix(self, players, extra_draws=(), indicators=("N",)):
        # After the terminal kan: 234p 456s 78s EE. An open normal 9s win
        # has no yaku; the replacement 9s must supply rinshan.
        hand = ["1m"] * 3 + ["2p", "3p", "4p", "4s", "5s", "6s", "7s", "8s", "E", "E"]
        events, metadata = opening(players, [["1m"], hand, *([[]] * (players - 2))],
                                   ["C", "9s", *extra_draws], indicators)
        return events + [draw(0, "C"), discard(0, "1m"), kan()], metadata

    def test_replacement_win_is_restored_for_both_modes_and_prefix_is_unchanged(self):
        for players in (3, 4):
            with self.subTest(players=players):
                prefix, metadata = self.no_yaku_prefix(players)
                before, _ = self.extract(finish(prefix, players), metadata)
                events = prefix + [draw(1, "9s"), {"type": "hora", "actor": 1, "target": 1},
                                   {"type": "end_kyoku"}, {"type": "end_game"}]
                samples, audit = self.extract(events, metadata)
                win = self.at(samples, len(prefix))
                self.assertEqual(win["action"]["action"], "tsumo")
                self.assertIn("tsumo", self.kinds(win))
                self.assertEqual(win["state"]["left"], 53 if players == 3 else 68)
                self.assertEqual(win["state"]["melds"][1][0]["type"], 2)
                self.assertTrue(win["state"]["rivers"][0][-1]["called"])
                self.assertFalse(win["state"]["noCallsYet"])
                by_id = {s["decisionId"]: s for s in samples}
                self.assertTrue(before)
                self.assertTrue(any(s["action"]["action"] == "daiminkan" for s in before))
                for old in before:
                    self.assertEqual(old, by_id[old["decisionId"]])
                self.assertEqual(audit["excluded"].get("label_not_in_reconstructed_mask", 0), 0)

    def test_deferred_dora_does_not_leak_into_draw_and_rinshan_resets(self):
        for players in (3, 4):
            with self.subTest(players=players):
                later = [(2, "P")] + ([(3, "F")] if players == 4 else []) + [(0, "C"), (1, "9s")]
                prefix, metadata = self.no_yaku_prefix(players, [tile for _, tile in later], ("N", "S"))
                events = prefix + [draw(1, "9s"), {"type": "dora", "dora_marker": "S"},
                                   discard(1, "9s", True)]
                for seat, tile in later:
                    events += [draw(seat, tile), discard(seat, tile, True)]
                samples, audit = self.extract(finish(events, players), metadata)
                replacement = self.at(samples, len(prefix))
                normal = self.at(samples, len(events) - 2)
                self.assertEqual(replacement["state"]["doras"], ["4z"])
                self.assertEqual(normal["state"]["doras"], ["4z", "2z"])
                self.assertIn("tsumo", self.kinds(replacement))
                self.assertNotIn("tsumo", self.kinds(normal))
                self.assertEqual(audit["excluded"].get("label_not_in_reconstructed_mask", 0), 0)

    def test_passed_ron_before_open_kan_preserves_temporary_and_riichi_furiten(self):
        for locked in (False, True):
            with self.subTest(locked=locked):
                players = 3
                kokushi = ["9m", "1p", "9p", "1s", "9s", "E", "E", "S", "W", "N", "P", "F", "C"]
                caller = ["1m"] * 3 + ["2p", "3p", "4p", "4s", "5s", "6s", "7s", "8s", "E", "E"]
                events, metadata = opening(players, [["1m"], caller, kokushi],
                                           ["C", "P", "7p", "F", "9s", "N"])
                events += [draw(0, "C"), discard(0, "C", True), draw(1, "P"), discard(1, "P", True), draw(2, "7p")]
                if locked:
                    events += [{"type": "reach", "actor": 2}]
                events += [discard(2, "7p", True)]
                if locked:
                    events += [{"type": "reach_accepted", "actor": 2}]
                events += [draw(0, "F"), discard(0, "1m"), kan(), draw(1, "9s"), discard(1, "E")]
                after_kan_discard = len(events) - 1
                events += [draw(2, "N"), discard(2, "N", True)]
                samples, audit = self.extract(finish(events, players), metadata)
                own_draw = self.at(samples, len(events) - 2, 2)
                self.assertEqual(own_draw["state"]["furiten"], locked)
                if not locked:
                    response = self.at(samples, after_kan_discard, 2)
                    self.assertTrue(response["state"]["furiten"])
                    self.assertEqual(response["action"]["action"], "pass")
                else:
                    self.assertEqual(own_draw["action"]["action"], "pass")
                self.assertEqual(audit["excluded"].get("label_not_in_reconstructed_mask", 0), 0)

    def test_open_kan_recomputes_own_discard_furiten_when_waits_shrink(self):
        # Nine gates waits on 1m..9m before the call. After opening 1111m,
        # 9m is no longer a wait, so the player's previous 9m is not furiten.
        hand = [n + "m" for n in "1112345678999"]
        events, metadata = opening(4, [["1m"], hand, [], []], ["C", "9m", "P", "F", "C", "S"])
        events += [draw(0, "C"), discard(0, "C", True), draw(1, "9m"), discard(1, "9m", True),
                   draw(2, "P"), discard(2, "P", True), draw(3, "F"), discard(3, "F", True),
                   draw(0, "C"), discard(0, "1m"), kan(), draw(1, "S"), discard(1, "S", True)]
        samples, audit = self.extract(finish(events, 4), metadata)
        self.assertTrue(self.at(samples, len(events) - 4)["state"]["furiten"])
        self.assertFalse(self.at(samples, len(events) - 2)["state"]["furiten"])
        self.assertEqual(audit["excluded"].get("label_not_in_reconstructed_mask", 0), 0)

    def test_later_closed_kan_remains_a_suffix_boundary(self):
        for players in (3, 4):
            with self.subTest(players=players):
                hand = ["1m"] * 3 + ["9p"] * 4 + ["2p", "3p", "4p", "5s", "6s", "7s"]
                events, metadata = opening(players, [["1m"], hand, *([[]] * (players - 2))], ["C", "8s", "E"])
                events += [draw(0, "C"), discard(0, "1m"), kan(), draw(1, "8s")]
                closed_step = len(events)
                events += [{"type": "ankan", "actor": 1, "consumed": ["9p"] * 4},
                           draw(1, "E"), discard(1, "E", True)]
                samples, audit = self.extract(finish(events, players), metadata)
                self.assertEqual(self.at(samples, closed_step - 1)["action"]["action"], "ankan")
                self.assertFalse(any(s["state"]["lastStep"] >= closed_step for s in samples))
                self.assertEqual(audit["excluded"]["hand_suffix_after_kan"], 1)

    def test_later_added_kan_remains_a_suffix_boundary(self):
        for players in (3, 4):
            with self.subTest(players=players):
                hand = ["1m"] * 3 + ["9p"] * 2 + ["2p", "3p", "4p", "5s", "6s", "7s", "E", "E"]
                draws = ["C", "P", "C", "9p", "S"] + (["F"] if players == 4 else [])
                events, metadata = opening(players, [["1m", "9p"], hand, *([[]] * (players - 2))], draws)
                events += [draw(0, "C"), discard(0, "9p"),
                           {"type": "pon", "actor": 1, "target": 0, "pai": "9p", "consumed": ["9p"] * 2},
                           discard(1, "E"), draw(2, "P"), discard(2, "P", True)]
                if players == 4:
                    events += [draw(3, "F"), discard(3, "F", True)]
                events += [draw(0, "C"), discard(0, "1m"), kan(), draw(1, "9p")]
                added_step = len(events)
                events += [{"type": "kakan", "actor": 1, "pai": "9p"}, draw(1, "S"), discard(1, "S", True)]
                samples, audit = self.extract(finish(events, players), metadata)
                self.assertEqual(self.at(samples, added_step - 1)["action"]["action"], "shouminkan")
                self.assertFalse(any(s["state"]["lastStep"] >= added_step for s in samples))
                self.assertEqual(audit["excluded"]["hand_suffix_after_kan"], 1)
                self.assertEqual(audit["excluded"].get("label_not_in_reconstructed_mask", 0), 0)

    def test_dora_before_replacement_is_visible_and_does_not_clear_rinshan(self):
        prefix, metadata = self.no_yaku_prefix(3, indicators=("N", "S"))
        events = prefix + [{"type": "dora", "dora_marker": "S"}, draw(1, "9s"),
                           {"type": "hora", "actor": 1, "target": 1},
                           {"type": "end_kyoku"}, {"type": "end_game"}]
        samples, _ = self.extract(events, metadata)
        win = self.at(samples, len(prefix) + 1)
        self.assertEqual(win["state"]["doras"], ["4z", "2z"])
        self.assertEqual(win["action"]["action"], "tsumo")

    def test_missing_or_wrong_actor_replacement_keeps_suffix_censored(self):
        for replacement in ([draw(2, "9s"), discard(2, "9s", True)], [discard(1, "E")]):
            with self.subTest(replacement=replacement):
                prefix, metadata = self.no_yaku_prefix(3)
                samples, audit = self.extract(finish(prefix + replacement, 3), metadata)
                self.assertTrue(any(s["action"]["action"] == "daiminkan" for s in samples))
                self.assertFalse(any(s["state"]["lastStep"] >= len(prefix) for s in samples))
                self.assertEqual(audit["excluded"]["hand_suffix_after_unverified_daiminkan_draw"], 1)

    def test_open_kan_label_outside_frozen_mask_does_not_unlock_suffix(self):
        prefix, metadata = self.no_yaku_prefix(3)
        prefix[-1]["consumed"] = ["1m", "1m", "9p"]  # Deliberately corrupt source claim.
        samples, audit = self.extract(finish(prefix + [draw(1, "9s"), discard(1, "9s", True)], 3), metadata)
        self.assertFalse(any(s["state"]["lastStep"] >= len(prefix) for s in samples))
        self.assertEqual(audit["excluded"]["label_not_in_reconstructed_mask"], 1)
        self.assertEqual(audit["excluded"]["hand_suffix_after_unverified_daiminkan"], 1)

    def test_later_rob_north_uncertainty_remains_a_suffix_boundary(self):
        kokushi = ["1m", "9m", "1p", "9p", "1s", "9s", "E", "E", "S", "W", "P", "F", "C"]
        caller = ["2p"] * 3 + ["3p", "4p", "5p", "4s", "5s", "6s", "7s", "8s", "E", "E"]
        events, metadata = opening(3, [["2p"], caller, kokushi], ["C", "N", "C"], indicators=("S",))
        events += [draw(0, "C"), discard(0, "2p"), kan(tile="2p"), draw(1, "N")]
        north_step = len(events)
        events += [{"type": "kita", "actor": 1, "pai": "N", "_tenhou": {"tsumogiri": True}},
                   draw(1, "C"), discard(1, "C", True)]
        samples, audit = self.extract(finish(events, 3), metadata)
        self.assertEqual(self.at(samples, north_step - 1)["action"]["action"], "kita")
        self.assertFalse(any(s["state"]["lastStep"] >= north_step for s in samples))
        self.assertEqual(audit["excluded"]["hand_suffix_after_rob_north_uncertainty"], 1)
        self.assertEqual(audit["excluded"].get("label_not_in_reconstructed_mask", 0), 0)

    def test_fourth_open_kan_is_retained_but_its_suffix_stays_excluded(self):
        for players in (3, 4):
            with self.subTest(players=players):
                tiles = ["1m", "9m", "1p", "9p"]
                replacements = ["5p", "6p", "7p", "E"]
                hand = [tile for tile in tiles for _ in range(3)] + ["E"]
                draws = ["2p"] * 4 + replacements + ["3p"] * 3 + (["4p"] * 3 if players == 4 else [])
                events, metadata = opening(players, [tiles, hand, *([[]] * (players - 2))], draws)
                replacement_steps = []
                for index, (tile, replacement) in enumerate(zip(tiles, replacements)):
                    events += [draw(0, "2p"), discard(0, tile), kan(tile=tile)]
                    replacement_steps.append(len(events))
                    events += [draw(1, replacement)]
                    if index < 3:
                        events += [discard(1, replacement, True), draw(2, "3p"), discard(2, "3p", True)]
                        if players == 4:
                            events += [draw(3, "4p"), discard(3, "4p", True)]
                events += [{"type": "hora", "actor": 1, "target": 1}, {"type": "end_kyoku"}, {"type": "end_game"}]
                samples, audit = self.extract(events, metadata)
                self.assertEqual(sum(s["action"]["action"] == "daiminkan" for s in samples), 4)
                self.assertTrue(all(self.at(samples, step) for step in replacement_steps[:3]))
                self.assertFalse(any(s["state"]["lastStep"] >= replacement_steps[-1] for s in samples))
                self.assertEqual(audit["excluded"]["hand_suffix_after_four_kans"], 1)


if __name__ == "__main__":
    unittest.main()
