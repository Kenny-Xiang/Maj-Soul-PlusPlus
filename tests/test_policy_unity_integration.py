"""Exported model -> Python advice -> real JS transport -> ACK and action echo.

The deterministic test weights select a desired legal candidate. They exercise
the deployment boundary, not training quality, and never open a network socket.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_policy_actions import hand_with, state
from test_policy_model import visible_state

try:
    import torch
except ImportError:
    torch = None

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(torch is None or shutil.which("node") is None, "requires training dependencies and Node")
class PolicyUnityIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def advice(self, snapshot, action, purpose="behavior-cloning", **match):
        from policy_actions import legal_actions
        from policy_features import ACTION_NAMES, encode_actions
        from policy_model import PolicyAdvisor
        from policy_training import CandidatePolicy, export_model
        target = next(candidate for candidate in legal_actions(snapshot)
                      if candidate["action"] == action and all(candidate.get(k) == v for k, v in match.items()))
        vector = torch.tensor(encode_actions(snapshot, [target])[0])
        size = len(ACTION_NAMES)
        network = CandidatePolicy({"channels": 1, "blocks": 1, "hidden": size * 2})
        # Negative L1 distance has a unique maximum at the selected candidate.
        # All inference, export validation and candidate generation remain real.
        with torch.no_grad():
            for parameter in network.parameters():
                parameter.zero_()
            network.score[0].weight[:size, size * 2:] = torch.eye(size)
            network.score[0].weight[size:, size * 2:] = -torch.eye(size)
            network.score[0].bias[:size] = -vector
            network.score[0].bias[size:] = vector
            network.score[2].weight.fill_(-1)
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder) / "contract.npz"
            export_model(network, model, {"playerCount": snapshot["playerCount"], "purpose": purpose})
            result = PolicyAdvisor({snapshot["playerCount"]: model})(snapshot)
        self.assertEqual(result["best"]["actionId"], target["actionId"], result)
        return result

    def snapshot(self, **options):
        players = options.get("players", 4)
        result = {**visible_state(players), **state(**options)}
        result["match"].update(category=2)
        result["gameId"] = "contract-game"
        result["operationTiming"] = {"timeFixed": 5000, "timeAdd": 20000, "receivedAt": 0}
        return result

    def run_cases(self, cases):
        completed = subprocess.run([shutil.which("node"), str(ROOT / "tests/helpers/policy_unity_contract.cjs")],
                                   input=json.dumps(cases), text=True, capture_output=True, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        results = json.loads(completed.stdout)
        self.assertEqual(len(results), len(cases))
        return results

    def test_all_model_action_types_preserve_wire_parameters_in_both_modes(self):
        from policy_actions import ACTION_TYPES
        cases = []

        def add(snapshot, action, fields, echo, channel="inputOperation", **match):
            advice = self.advice(snapshot, action, **match)
            self.assertEqual(advice["status"], "ready")
            cases.append({"name": f'{snapshot["playerCount"]}p-{action}-{len(cases)}',
                          "state": snapshot, "advice": advice, "method": ".lq.FastTest." + channel,
                          "fields": {str(k): v for k, v in {6: 2, **fields}.items() if v not in (0, False)},
                          "echo": echo, "echoFirst": len(cases) % 2 == 0})

        for players in (3, 4):
            for action, kind in (("discard", 1), ("riichi", 7)):
                for tile, moqie in (("0p", False), ("5p", False), ("5p", True)):
                    snapshot = self.snapshot(players=players, hand=hand_with(["0p", "5p"], 13) + ["5p"],
                                             ops=[{"type": 1, "combination": []}, {"type": 7, "combination": ["5p"]}])
                    add(snapshot, action, {1: kind, 3: tile, 5: int(moqie)},
                        {"name": "ActionDiscardTile", "seat": 0, "tile": tile, "moqie": moqie,
                         "riichi": action == "riichi"}, tile=tile, moqie=moqie)
            for action, kind, consumed in (("pon", 3, ["0p", "5p"]), ("daiminkan", 5, ["0p", "5p", "5p"])):
                snapshot = self.snapshot(players=players, hand=hand_with(consumed, 13), reaction="5p",
                                         ops=[{"type": kind, "combination": ["|".join(consumed)]}])
                add(snapshot, action, {1: kind}, {"name": "ActionChiPengGang", "seat": 0,
                    "type": 1 if kind == 3 else 2, "tiles": consumed + ["5p"],
                    "froms": [0] * len(consumed) + [players - 1]}, channel="inputChiPengGang")
                add(snapshot, "pass", {3: 1}, {"name": "ActionDealTile", "seat": 1}, channel="inputChiPengGang")
            quad = ["0p", "5p", "5p", "5p"]
            snapshot = self.snapshot(players=players, hand=hand_with(quad),
                                     ops=[{"type": 1, "combination": []}, {"type": 4, "combination": ["|".join(quad)]}])
            add(snapshot, "ankan", {1: 4}, {"name": "ActionAnGangAddGang", "seat": 0, "type": 3, "tile": "5p"})
            snapshot = self.snapshot(players=players, hand=hand_with(["0p"], 11),
                                     melds=[{"type": 1, "tiles": ["5p"] * 3}],
                                     ops=[{"type": 1, "combination": []}, {"type": 6, "combination": ["|".join(quad)]}])
            add(snapshot, "shouminkan", {1: 6}, {"name": "ActionAnGangAddGang", "seat": 0, "type": 2, "tile": "0p"})
            snapshot = self.snapshot(players=players, ops=[{"type": 8, "combination": []}])
            add(snapshot, "tsumo", {1: 8}, {"name": "ActionHule", "hules": [{"seat": 0, "zimo": True}]})
            add(snapshot, "pass", {4: 1}, {"name": "ActionDiscardTile", "seat": 0, "tile": "1p"})
            snapshot = self.snapshot(players=players, hand=hand_with([], 13), reaction="7z",
                                     ops=[{"type": 9, "combination": []}])
            add(snapshot, "ron", {1: 9}, {"name": "ActionHule", "hules": [{"seat": 0, "zimo": False}]})
            terminals = ["1m", "9m", "1p", "9p", "1s", "9s"] + [f"{n}z" for n in range(1, 8)] + ["1m"]
            snapshot = self.snapshot(players=players, hand=terminals, opening=True,
                                     ops=[{"type": 1, "combination": []}, {"type": 10, "combination": []}])
            add(snapshot, "abort", {1: 10}, {"name": "ActionLiuJu", "seat": 0, "type": 1})
        snapshot = self.snapshot(hand=hand_with(["3p", "0p", "5p"], 13), reaction="4p",
                                 ops=[{"type": 2, "combination": ["3p|5p", "3p|0p"]}])
        add(snapshot, "chi", {1: 2, 2: 1}, {"name": "ActionChiPengGang", "seat": 0, "type": 0,
            "tiles": ["3p", "4p", "0p"], "froms": [0, 3, 0]}, channel="inputChiPengGang", consumed=["0p", "3p"])
        for opening, moqie in ((True, False), (False, False), (False, True)):
            snapshot = self.snapshot(players=3, hand=hand_with(["4z"], 13) + ["4z"], opening=opening,
                                     ops=[{"type": 11, "combination": []}])
            add(snapshot, "kita", {1: 11, 5: int(moqie)}, {"name": "ActionBaBei", "seat": 0, "moqie": moqie}, moqie=moqie)
        results = self.run_cases(cases)
        self.assertEqual({item["action"] for item in results}, set(ACTION_TYPES))

    def test_model_smoke_and_stale_predictions_never_send(self):
        snapshot = self.snapshot()
        cases = [{"name": "smoke", "state": snapshot,
                  "advice": self.advice(snapshot, "discard", purpose="smoke"), "reject": "不可执行"},
                 {"name": "stale", "state": snapshot,
                  "advice": self.advice(snapshot, "discard"), "stale": True, "reject": "已过期"}]
        self.run_cases(cases)


if __name__ == "__main__":
    unittest.main()
