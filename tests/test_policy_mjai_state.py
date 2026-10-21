"""Independent public-state and action-contract checks for MJAI projection."""
from copy import deepcopy
import json
import unittest

from policy_actions import legal_actions
from policy_mjai_state import MjaiVisibleState, tile_name


HAND = ["1m", "2m", "3m", "4p", "0p", "5p", "6p", "7p", "8p", "1s", "2s", "3s", "7z", "5p"]
DISCARD = [{"type": 1, "combination": []}]


def start_event(**values):
    return {"type": "start_kyoku", "bakaze": "E", "kyoku": 1, "honba": 2,
            "kyotaku": 1, "oya": 0, "scores": [25000] * 4,
            "dora_marker": "9m", "tehais": [["secret hand"]] * 4, **values}


class MjaiVisibleStateTests(unittest.TestCase):
    def opened(self):
        state = MjaiVisibleState()
        state.apply({"type": "start_game", "names": ["PRIVATE NAME"] * 4}, 0)
        state.apply(start_event(), 1)
        state.apply({"type": "tsumo", "actor": 0, "pai": "5p"}, 2)
        return state

    def test_tile_mapping_preserves_reds_and_honors(self):
        self.assertEqual([tile_name(value) for value in ("5mr", "5pr", "5sr", "E", "C")],
                         ["0m", "0p", "0s", "1z", "7z"])
        for value in ("?", "0z", "5zr", "10m"):
            with self.assertRaises(ValueError):
                tile_name(value)

    def test_match_metadata_survives_round_reset_and_unknown_never_uses_future_rounds(self):
        metadata = {'schemaVersion': 1, 'gameId': '260101-11111111-2222-4333-8444-555555555555',
                    'modeId': 15, 'roundCount': 1, 'playerCount': 4,
                    'sourceCompressedSha256': '1' * 64,
                    'provenance': {'kind': 'official-header-config', 'archive': 'fixture',
                                   'headSha256': '2' * 64, 'responseSha256': '3' * 64,
                                   'schemaSha256': '4' * 64}}
        known, unknown = MjaiVisibleState(metadata), MjaiVisibleState()
        metadata['roundCount'] = 2
        for state in (known, unknown):
            state.apply({'type': 'start_game'}, 0)
            state.apply(start_event(), 1)
            state.apply(start_event(bakaze='S'), 100)
        self.assertEqual(known.state['match']['roundCount'], 1)
        self.assertEqual(known.state['match']['modeId'], 15)
        self.assertIsNone(unknown.state['match']['roundCount'])

    def test_starting_hands_names_and_outcomes_are_not_retained(self):
        state = self.opened()
        snapshot = state.snapshot(0, HAND, DISCARD, False)
        serialized = json.dumps(vars(state))
        self.assertNotIn("secret hand", serialized)
        self.assertNotIn("PRIVATE NAME", serialized)
        self.assertNotIn("tehais", serialized)
        self.assertEqual(snapshot["match"], {"playerCount": 4, "roundCount": None})
        self.assertEqual(snapshot["round"], {"chang": 0, "ju": 0, "ben": 2})
        self.assertEqual(snapshot["operationSource"], "riichienv-reconstructed")
        state.state["outcomes"] = "DO NOT COPY"
        self.assertNotIn("outcomes", state.snapshot(0, HAND, DISCARD, False))

    def test_opening_discard_is_handcut_and_other_view_has_no_draw(self):
        state = self.opened()
        snapshot = state.snapshot(0, HAND, DISCARD, False)
        self.assertEqual(snapshot["left"], 69)
        self.assertEqual(snapshot["lastDraw"], "5p")
        self.assertEqual(snapshot["lastAction"]["name"], "ActionNewRound")
        self.assertTrue(all(not value["moqie"] for value in legal_actions(snapshot)))
        hidden = state.snapshot(1, HAND[:-1], [], False)
        self.assertIsNone(hidden["lastDraw"])
        self.assertIsNone(hidden["lastAction"]["tile"])
        state.apply({"type": "dahai", "actor": 0, "pai": "5p", "tsumogiri": True}, 3)
        self.assertFalse(state.state["rivers"][0][-1]["moqie"])
        self.assertIsNone(state.snapshot(0, HAND[:-1], [], False)["lastDraw"])

    def test_later_duplicate_tile_keeps_both_discard_sources(self):
        state = self.opened()
        state.apply({"type": "dahai", "actor": 0, "pai": "C", "tsumogiri": False}, 3)
        state.apply({"type": "tsumo", "actor": 1, "pai": "5p"}, 4)
        snapshot = state.snapshot(1, HAND, DISCARD, False)
        choices = [a for a in legal_actions(snapshot) if a["tile"] == "5p"]
        self.assertEqual({a["moqie"] for a in choices}, {True, False})
        self.assertEqual(snapshot["left"], 68)
        self.assertEqual(snapshot["lastAction"]["name"], "ActionDealTile")

    def test_called_discard_is_counted_once_and_kuikae_is_external(self):
        state = self.opened()
        state.apply({"type": "dahai", "actor": 0, "pai": "5pr", "tsumogiri": False}, 3)
        state.apply({"type": "chi", "actor": 1, "target": 0,
                     "pai": "5pr", "consumed": ["3p", "4p"]}, 4)
        hand = ["1m", "2m", "3m", "6p", "7p", "8p", "1s", "2s", "3s", "7z", "5p"]
        snapshot = state.snapshot(1, hand, [{"type": 1, "combination": ["5p", "2p"]}], False)
        self.assertTrue(snapshot["rivers"][0][-1]["called"])
        self.assertEqual(snapshot["melds"][1], [{"type": 0, "tiles": ["3p", "4p", "0p"],
                                                "froms": [1, 1, 0]}])
        self.assertEqual(snapshot["lastAction"]["type"], 0)
        self.assertFalse(snapshot["noCallsYet"])
        self.assertIsNone(snapshot["lastDraw"])
        self.assertFalse(any(a["tile"] in ("5p", "2p") for a in legal_actions(snapshot)))
        try:
            from policy_features import encode_state, tile34
        except ImportError:
            return
        planes, _ = encode_state(snapshot)
        self.assertEqual(float(planes[8, tile34("5p")]), .5)  # one own five + called red

    def test_riichi_timing_does_not_rewrite_discard_window(self):
        state = self.opened()
        before = state.snapshot(0, HAND, DISCARD, False)
        state.apply({"type": "reach", "actor": 0}, 3)
        self.assertEqual(state.state["lastStep"], 2)
        state.apply({"type": "dahai", "actor": 0, "pai": "C", "tsumogiri": False}, 4)
        window = state.snapshot(1, HAND[:-1], [{"type": 9, "combination": []}], False)
        self.assertEqual(window["scores"], [25000] * 4)
        self.assertEqual(window["riichiSticks"], 1)
        self.assertTrue(window["riichiPending"][0])
        self.assertFalse(window["riichi"][0])
        self.assertTrue(window["rivers"][0][-1]["riichi"])
        self.assertEqual(window["riichiStep"][0], 4)
        state.apply({"type": "reach_accepted", "actor": 0}, 5)
        after = state.snapshot(1, HAND[:-1], [], False)
        self.assertEqual(after["lastAction"], window["lastAction"])
        self.assertEqual(after["lastStep"], 4)
        self.assertEqual(after["scores"], [24000, 25000, 25000, 25000])
        self.assertEqual(after["riichiSticks"], 2)
        self.assertTrue(after["riichi"][0])
        self.assertTrue(after["doubleRiichi"][0])
        self.assertFalse(after["riichiPending"][0])
        self.assertEqual(before["scores"], [25000] * 4)
        self.assertFalse(before["riichiPending"][0])
        self.assertEqual(window["scores"], [25000] * 4)

    def test_snapshots_and_supplied_arrays_are_isolated(self):
        state = self.opened()
        hand, details = list(HAND), deepcopy(DISCARD)
        snapshot = state.snapshot(0, hand, details, True)
        hand.clear()
        details[0]["combination"].append("5p")
        snapshot["scores"][0] = -1
        snapshot["doras"].append("1z")
        snapshot["rivers"][0].append({"tile": "1z"})
        clean = state.snapshot(0, HAND, DISCARD, False)
        self.assertEqual(snapshot["hand"], HAND)
        self.assertEqual(snapshot["operationDetails"], DISCARD)
        self.assertEqual(clean["scores"], [25000] * 4)
        self.assertEqual(clean["doras"], ["9m"])
        self.assertEqual(clean["rivers"], [[], [], [], []])

    def test_kan_updates_red_tiles_and_replacement_draw_consumes_wall(self):
        state = self.opened()
        state.apply({"type": "dahai", "actor": 0, "pai": "5p", "tsumogiri": False}, 3)
        state.apply({"type": "pon", "actor": 2, "target": 0,
                     "pai": "5p", "consumed": ["5pr", "5p"]}, 4)
        state.apply({"type": "dahai", "actor": 2, "pai": "1m", "tsumogiri": False}, 5)
        state.apply({"type": "tsumo", "actor": 2, "pai": "5p"}, 6)
        state.apply({"type": "kakan", "actor": 2, "pai": "5p"}, 7)
        self.assertEqual(state.state["melds"][2][0]["tiles"], ["0p", "5p", "5p", "5p"])
        self.assertEqual(state.state["melds"][2][0]["type"], 2)
        self.assertEqual(state.state["lastAction"]["type"], 2)
        state.apply({"type": "dora", "dora_marker": "W"}, 8)
        self.assertEqual(state.state["lastStep"], 7)
        state.apply({"type": "tsumo", "actor": 2, "pai": "9s"}, 9)
        self.assertEqual(state.state["left"], 67)
        state.apply({"type": "ankan", "actor": 2, "consumed": ["9s"] * 4}, 10)
        self.assertEqual(state.state["melds"][2][-1], {"type": 3, "tiles": ["9s"] * 4, "froms": []})
        self.assertIsNone(state.snapshot(2, HAND[:7], [], False)["lastDraw"])

    def test_complete_baseline_and_round_boundaries(self):
        state = MjaiVisibleState()
        self.assertFalse(state.snapshot(0, HAND, DISCARD, False)["historyComplete"])
        with self.assertRaisesRegex(ValueError, "baseline"):
            state.apply({"type": "tsumo", "actor": 0, "pai": "1m"}, 0)
        with self.assertRaisesRegex(ValueError, "four starting scores"):
            state.apply(start_event(scores=[35000] * 3), 0)
        state = self.opened()
        state.apply({"type": "hora", "actor": 0, "target": 0, "deltas": [123456789] * 4}, 3)
        finished = state.snapshot(0, HAND, DISCARD, False)
        self.assertFalse(finished["canAct"])
        self.assertEqual(finished["scores"], [25000] * 4)
        state.apply({"type": "end_kyoku"}, 4)
        state.apply(start_event(oya=2, bakaze="S", honba=0), 5)
        state.apply({"type": "tsumo", "actor": 2, "pai": "E"}, 6)
        restarted = state.snapshot(2, HAND[:-1] + ["1z"], DISCARD, False)
        self.assertEqual(restarted["left"], 69)
        self.assertEqual(restarted["round"], {"chang": 1, "ju": 2, "ben": 0})
        self.assertEqual(restarted["lastAction"]["name"], "ActionNewRound")


if __name__ == "__main__":
    unittest.main()
