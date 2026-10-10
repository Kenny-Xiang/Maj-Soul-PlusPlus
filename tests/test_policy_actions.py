"""Unscored full-action masks and exact physical action identities."""
from copy import deepcopy
import unittest

from policy_actions import ACTION_SCHEMA_VERSION, ACTION_TYPES, action_key, legal_actions


POOL = [f"{n}{suit}" for suit in "ps" for n in range(1, 10)] + [f"{n}z" for n in range(1, 8)]


def hand_with(prefix, size=14):
    families = {tile.replace("0", "5") for tile in prefix}
    return prefix + [tile for tile in POOL if tile not in families][:size - len(prefix)]


def state(hand=None, ops=None, players=4, reaction=None, melds=None, opening=False):
    ops = ops if ops is not None else [{"type": 1, "combination": []}]
    hand = hand if hand is not None else hand_with(["7z", "7z"])
    last = ({"name": "ActionDiscardTile", "seat": 3 if players == 4 else 2,
             "tile": reaction, "step": 12} if reaction else
            {"name": "ActionNewRound" if opening else "ActionDealTile", "seat": 0,
             "tile": hand[-1], "step": 12})
    rivers = [[], [], [], []]
    if reaction:
        rivers[last["seat"]] = [{"tile": reaction, "step": 12, "called": False}]
    return {"phase": "playing", "playerCount": players, "selfSeat": 0,
            "hand": hand, "handComplete": True, "historyComplete": True,
            "canAct": True, "canDiscard": any(op["type"] == 1 for op in ops),
            "operations": [op["type"] for op in ops], "operationDetails": ops,
            "lastStep": 12, "lastAction": last, "lastDraw": None if reaction else hand[-1],
            "melds": [melds or [], [], [], []], "rivers": rivers, "noCallsYet": True,
            "riichi": [False] * 4, "riichiPending": [False] * 4,
            "forbiddenDiscards": [tile for op in ops if op["type"] == 1 for tile in op["combination"]]}


def choices(s, kind):
    return [action for action in legal_actions(s) if action["action"] == kind]


class PolicyActionsTests(unittest.TestCase):
    def test_sources_are_distinct_and_state_and_candidate_payloads_do_not_alias(self):
        s = state(hand_with(["0p", "5p"], 13) + ["5p"])
        original = deepcopy(s)
        actions = legal_actions(s)
        self.assertEqual(s, original)
        five = [a for a in actions if a.get("tile") == "5p"]
        self.assertEqual({a["moqie"] for a in five}, {False, True})
        self.assertEqual(len({a["actionId"] for a in five}), 2)
        self.assertEqual([a["moqie"] for a in actions if a.get("tile") == "0p"], [False])
        self.assertEqual(actions, legal_actions(deepcopy(s)))
        actions[0]["consumed"].append("1z")
        self.assertEqual(s, original)

    def test_unique_draw_has_no_hand_discard_copy(self):
        s = state(hand_with(["0p"], 13) + ["5p"])
        self.assertEqual([a["moqie"] for a in choices(s, "discard") if a["tile"] == "5p"], [True])

    def test_dealer_opening_only_has_hand_sources_in_both_modes(self):
        for players in (3, 4):
            s = state(hand_with(["0p"], 13) + ["5p"], players=players, opening=True,
                      ops=[{"type": 1, "combination": []}, {"type": 7, "combination": ["5p"]}])
            self.assertTrue(all(action["moqie"] is False for action in legal_actions(s)))
            self.assertEqual({a["tile"] for a in choices(s, "riichi")}, {"0p", "5p"})

    def test_locked_draw_cannot_hand_discard_an_identical_copy(self):
        s = state(hand_with(["5p"], 13) + ["5p"])
        for flag in ("riichi", "riichiPending"):
            locked = deepcopy(s)
            locked[flag][0] = True
            actions = legal_actions(locked)
            self.assertEqual([(a["tile"], a["moqie"]) for a in actions], [("5p", True)])

    def test_red_pon_combinations_are_preserved_and_no_followup_is_invented(self):
        s = state(hand_with(["0p", "5p", "5p"], 13), reaction="5p",
                  ops=[{"type": 3, "combination": ["0p|5p", "5p|5p"]}])
        actions = legal_actions(s)
        self.assertEqual({a["action"] for a in actions}, {"pon", "pass"})
        pons = choices(s, "pon")
        self.assertEqual(len(pons), 2)
        self.assertEqual({tuple(a["consumed"]) for a in pons}, {("0p", "5p"), ("5p", "5p")})
        self.assertTrue(all(a["calledTile"] == "5p" and a["fromSeat"] == 3 for a in pons))
        self.assertTrue(all("followupDiscard" not in a for a in actions))

    def test_chi_and_daiminkan_consume_exact_tiles(self):
        for kind, consumed, called in [(2, ["3p", "0p"], "4p"), (5, ["0p", "5p", "5p"], "5p")]:
            s = state(hand_with(consumed, 13), reaction=called,
                      ops=[{"type": kind, "combination": ["|".join(consumed)]}])
            action = next(a for a in legal_actions(s) if a["action"] != "pass")
            self.assertEqual(action["consumed"], sorted(consumed))
            self.assertEqual(action["calledTile"], called)

    def test_kan_types_and_matching_added_red_tile(self):
        quad = ["0p", "5p", "5p", "5p"]
        concealed = state(hand_with(quad), ops=[{"type": 1, "combination": []},
                                               {"type": 4, "combination": ["|".join(quad)]}])
        self.assertEqual(choices(concealed, "ankan")[0]["consumed"], quad)
        self.assertEqual(choices(concealed, "ankan")[0]["tile"], "5p")
        added = state(hand_with(["0p"], 11), melds=[{"type": 1, "tiles": ["5p"] * 3}],
                      ops=[{"type": 1, "combination": []}, {"type": 6, "combination": ["|".join(quad)]}])
        action = choices(added, "shouminkan")[0]
        self.assertEqual((action["tile"], action["consumed"], action["meldIndex"]), ("0p", ["0p"], 0))

    def test_win_does_not_remove_pass_or_ordinary_actions(self):
        reaction = state(hand_with(["0p", "5p"], 13), reaction="5p",
                         ops=[{"type": 3, "combination": ["0p|5p"]}, {"type": 9, "combination": []}])
        self.assertEqual({a["action"] for a in legal_actions(reaction)}, {"pon", "ron", "pass"})
        ron = choices(reaction, "ron")[0]
        self.assertEqual((ron["tile"], ron["calledTile"], ron["fromSeat"]), ("5p", "5p", 3))
        own = state(ops=[{"type": 1, "combination": []}, {"type": 8, "combination": []}])
        self.assertEqual({a["action"] for a in legal_actions(own)}, {"discard", "tsumo"})
        own["operations"], own["operationDetails"], own["canDiscard"] = [8], [{"type": 8, "combination": []}], False
        self.assertEqual({a["action"] for a in legal_actions(own)}, {"tsumo", "pass"})

    def test_kita_sources_opening_and_locked_optional_pass(self):
        s = state(hand_with(["4z"], 13) + ["4z"], players=3,
                  ops=[{"type": 11, "combination": []}])
        self.assertEqual({a["moqie"] for a in choices(s, "kita")}, {False, True})
        s["riichi"][0] = True
        self.assertEqual([a["moqie"] for a in choices(s, "kita")], [True])
        self.assertEqual({a["action"] for a in legal_actions(s)}, {"kita", "pass"})
        s["riichi"][0] = False
        s["lastAction"]["name"] = "ActionNewRound"
        self.assertEqual([a["moqie"] for a in choices(s, "kita")], [False])

    def test_nine_terminals_and_all_twelve_names_are_explicit(self):
        hand = ["1m", "9m", "1p", "9p", "1s", "9s"] + [f"{n}z" for n in range(1, 8)] + ["1m"]
        s = state(hand, opening=True, ops=[{"type": 1, "combination": []}, {"type": 10, "combination": []}])
        self.assertEqual(len(choices(s, "abort")), 1)
        self.assertEqual(ACTION_SCHEMA_VERSION, 1)
        self.assertEqual(set(ACTION_TYPES), {"discard", "riichi", "chi", "pon", "ankan", "daiminkan",
                                           "shouminkan", "kita", "tsumo", "ron", "abort", "pass"})

    def test_forbidden_discard_family_excludes_both_red_and_normal_five(self):
        s = state(hand_with(["0p", "5p"]), ops=[{"type": 1, "combination": ["5p"]}])
        self.assertFalse({"0p", "5p"}.intersection(a["tile"] for a in legal_actions(s)))

    def test_bad_candidate_rejects_entire_mask_even_with_good_discards(self):
        s = state(ops=[{"type": 1, "combination": []}, {"type": 4, "combination": ["7z|7z|7z|7z"]}])
        with self.assertRaisesRegex(ValueError, "unavailable"):
            legal_actions(s)
        s["operationDetails"][1]["combination"] = []
        with self.assertRaisesRegex(ValueError, "Missing call"):
            legal_actions(s)

    def test_missing_fields_and_unknown_operations_reject_open_windows(self):
        for field in ("phase", "canAct", "canDiscard", "hand", "handComplete", "historyComplete", "selfSeat",
                      "playerCount", "lastStep", "lastAction", "lastDraw", "riichi", "riichiPending",
                      "melds", "rivers", "forbiddenDiscards", "operations", "operationDetails"):
            with self.subTest(field=field):
                s = state()
                del s[field]
                with self.assertRaises(ValueError):
                    legal_actions(s)
        s = state(ops=[{"type": 1, "combination": []}, {"type": 12, "combination": []}])
        with self.assertRaises(ValueError):
            legal_actions(s)

    def test_inconsistent_or_unverified_windows_reject(self):
        changes = [{"historyComplete": False}, {"handComplete": False}, {"recovery": {"status": "waiting"}},
                   {"canDiscard": False}, {"lastDraw": None}, {"forbiddenDiscards": ["1p"]},
                   {"operationDetails": [{"type": 1}]}, {"operations": [1, 1]},
                   {"lastAction": {"name": "ActionDealTile", "seat": 0, "tile": "1p", "step": 11}}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                legal_actions({**state(), **change})

    def test_bad_calls_and_sanma_chi_are_not_silently_filtered(self):
        good = state(hand_with(["3p", "5p"], 13), reaction="4p",
                     ops=[{"type": 2, "combination": ["3p|5p"]}])
        for change in ("sanma", "wrong_source", "wrong_tiles", "stale", "called", "duplicate"):
            s = deepcopy(good)
            if change == "sanma":
                s["playerCount"] = 3
                s["lastAction"]["seat"] = 2
                s["rivers"][2] = s["rivers"][3]
            elif change == "wrong_source":
                s["lastAction"]["seat"] = 1
                s["rivers"][1] = s["rivers"][3]
            elif change == "wrong_tiles":
                s["operationDetails"][0]["combination"] = ["3p|6p"]
            elif change == "stale":
                s["rivers"][3][-1]["step"] = 11
            elif change == "called":
                s["rivers"][3][-1]["called"] = True
            else:
                s["operationDetails"][0]["combination"] += ["5p|3p"]
            with self.subTest(change=change), self.assertRaises(ValueError):
                legal_actions(s)

    def test_robbing_north_and_kan_use_current_target(self):
        for name, tile, players in [("ActionBaBei", "4z", 3), ("ActionAnGangAddGang", "5p", 4)]:
            s = state(hand_with([], 13), players=players, reaction=tile,
                      ops=[{"type": 9, "combination": []}])
            s["lastAction"]["name"] = name
            self.assertEqual(choices(s, "ron")[0]["calledTile"], tile)

    def test_post_call_discard_has_no_draw_source(self):
        s = state(hand_with([], 11), melds=[{"type": 1, "tiles": ["7z"] * 3}])
        s["lastDraw"] = None
        s["lastAction"].update(name="ActionChiPengGang", type=1, tile=None)
        self.assertTrue(all(action["moqie"] is False for action in legal_actions(s)))

    def test_keys_preserve_semantics_not_server_order_or_scores(self):
        action = {"action": "pon", "tile": "5p", "calledTile": "5p", "consumed": ["0p", "5p"], "fromSeat": 3}
        self.assertEqual(action_key(action), action_key({**action, "consumed": ["5p", "0p"], "score": 999}))
        self.assertNotEqual(action_key(action), action_key({**action, "fromSeat": 2}))
        with self.assertRaises(ValueError):
            action_key({"action": "discard", "tile": "1p"})

    def test_closed_windows_have_no_actions(self):
        for change in ({"phase": "ended"}, {"canAct": False}):
            self.assertEqual(legal_actions({**state(), **change}), [])


if __name__ == "__main__":
    unittest.main()
