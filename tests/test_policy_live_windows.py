"""Live wire -> visible state -> independent policies, including replacement draws."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from threading import Event
import unittest
from unittest.mock import Mock, patch

from test_policy_actions import hand_with
from test_policy_model import torch

ROOT = Path(__file__).resolve().parents[1]


def op(field, *choices):
    return [field, [[1, 0], *[[2, [[1, kind], *[[2, value] for value in combos]]]
                             for kind, combos in choices], [4, 20000], [5, 5000]]]


def action(name, fields):
    return {"name": name, "fields": fields}


def opening(players, hand, choices=(), dealer=0):
    return action("ActionNewRound", [[1, 0], [2, dealer], [3, 0],
                  *[[4, tile] for tile in hand], *[[6, 35000 if players == 3 else 25000]] * players,
                  op(7, *choices), [13, 54 if players == 3 else 69], [14, "9m"]])


def wire_cases():
    cases = []
    discard = lambda tile: action("ActionDiscardTile", [[1, 0], [2, tile]])
    draw = lambda tile, *choices: action("ActionDealTile", [[1, 0], [2, tile], [3, 40], op(4, *choices)])
    for players in (3, 4):
        cases.append({"name": f"{players}p-draw", "actions": [
            opening(players, hand_with(["7z", "7z"]), [(1, [])]),
            discard("3s"), draw("9s", (1, []), (7, ["9s"]), (8, []))]})
        for kind, tiles, called in ((3, ["7z", "7z"], "7z"),
                                    (5, ["7z"] * 3, "7z"),
                                    *(([(2, ["3p", "0p"], "4p")]) if players == 4 else [])):
            meld = sorted(tiles + [called]) if kind == 2 else tiles + [called]
            sources = [players - 1 if i == meld.index(called) else 0 for i in range(len(meld))]
            entries = [[1, 0], [2, {2: 0, 3: 1, 5: 2}[kind]],
                       *[[3, tile] for tile in meld], *[[4, seat] for seat in sources]]
            events = [opening(players, hand_with(tiles, 13), dealer=players - 1),
                      action("ActionDiscardTile", [[1, players - 1], [2, called],
                             op(4, (kind, ["|".join(tiles)]), (9, []))]),
                      action("ActionChiPengGang", entries + ([] if kind == 5 else [op(6, (1, [called]))]))]
            if kind == 5:
                events.append(draw("9s", (1, [])))
            cases.append({"name": f"{players}p-call-{kind}", "actions": events})
        cases.append({"name": f"{players}p-ankan", "actions": [
            opening(players, hand_with(["7z"] * 4), [(1, []), (4, ["7z|7z|7z|7z"])]),
            action("ActionAnGangAddGang", [[1, 0], [2, 3], [3, "7z"]]),
            draw("9s", (1, []))]})
        cases.append({"name": f"{players}p-shouminkan", "actions": [
            opening(players, hand_with(["5p", "5p"], 13), dealer=players - 1),
            action("ActionDiscardTile", [[1, players - 1], [2, "5p"], op(4, (3, ["5p|5p"]))]),
            action("ActionChiPengGang", [[1, 0], [2, 1], *[[3, "5p"]] * 3,
                   [4, 0], [4, 0], [4, players - 1], op(6, (1, ["5p"]))]),
            discard("1p"), draw("0p", (1, []), (6, ["0p|5p|5p|5p"])),
            action("ActionAnGangAddGang", [[1, 0], [2, 2], [3, "0p"]]), draw("9s", (1, []))]})
        terminals = ["1m", "9m", "1p", "9p", "1s", "9s"] + [f"{n}z" for n in range(1, 8)] + ["1m"]
        cases.append({"name": f"{players}p-abort", "actions": [opening(players, terminals, [(1, []), (10, [])])]})
        # Rare legal reactions still originate in server operations, not an event whitelist.
        cases.append({"name": f"{players}p-rob-ankan", "actions": [
            opening(players, hand_with([], 13), dealer=players - 1),
            action("ActionAnGangAddGang", [[1, players - 1], [2, 3], [3, "7z"], op(4, (9, []))])]})
    cases.append({"name": "3p-kita-replacement", "actions": [
        opening(3, hand_with(["4z"]), [(1, []), (11, [])]),
        action("ActionBaBei", [[1, 0], [9, 0]]),
        draw("4z", (1, []), (11, [])),
        action("ActionBaBei", [[1, 0], [9, 1]]), draw("9s", (1, []))]})
    cases.append({"name": "3p-rob-kita", "actions": [
        opening(3, hand_with([], 13), dealer=2),
        action("ActionBaBei", [[1, 2], [9, 0], op(4, (9, []))])]})
    return cases


@unittest.skipIf(torch is None or shutil.which("node") is None, "requires training dependencies and Node")
class PolicyLiveWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests/helpers/policy_live_windows.cjs")],
                                input=json.dumps(wire_cases()), text=True, capture_output=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.flows = json.loads(result.stdout)

    def setUp(self):
        from policy_model import PolicyAdvisor
        from policy_training import CandidatePolicy, export_model
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        paths = {}
        for players in (3, 4):
            torch.manual_seed(players)
            path = paths[players] = Path(folder.name) / f"{players}p.npz"
            export_model(CandidatePolicy({"channels": 4, "blocks": 1, "hidden": 8}), path,
                         {"playerCount": players, "purpose": "behavior-cloning"})
        self.advisor = PolicyAdvisor(paths)

    def test_wire_windows_route_only_to_their_own_model_and_preserve_legal_actions(self):
        from policy_actions import legal_actions
        seen = set()
        self.assertNotEqual(self.advisor.models[3].sha256, self.advisor.models[4].sha256)
        for flow in self.flows:
            for packet in flow["turns"]:
                state = packet["state"]
                with self.subTest(flow=flow["name"], step=state["lastStep"]):
                    model = self.advisor.models[state["playerCount"]]
                    other = self.advisor.models[7 - state["playerCount"]]
                    with patch.object(model, "predict", wraps=model.predict) as predict, \
                            patch.object(other, "predict", side_effect=AssertionError("wrong model slot")):
                        result = self.advisor(state)
                    if not state["canAct"]:
                        predict.assert_not_called()
                        self.assertEqual((result["status"], result["candidates"], result["best"]),
                                         ("waiting", [], None))
                        continue
                    predict.assert_called_once()
                    self.assertEqual(result["status"], "ready", result)
                    self.assertEqual(result["modelSha256"], model.sha256)
                    self.assertEqual({a["actionId"] for a in result["candidates"]},
                                     {a["actionId"] for a in legal_actions(state)})
                    seen.update(a["action"] for a in result["candidates"])
                    if state["lastAction"]["name"] == "ActionChiPengGang":
                        self.assertTrue(all(a["moqie"] is False for a in result["candidates"]))
                    if "rob-" in flow["name"] and state["lastStep"] == 1:
                        ron = next(a for a in result["candidates"] if a["action"] == "ron")
                        self.assertEqual(ron["fromSeat"], state["playerCount"] - 1)
                        self.assertEqual(ron["tile"], "4z" if "kita" in flow["name"] else "7z")
        self.assertEqual(seen, {"discard", "riichi", "chi", "pon", "daiminkan", "ankan",
                                "shouminkan", "kita", "ron", "tsumo", "pass", "abort"})

    def test_missing_slot_does_not_use_the_other_model(self):
        state = self.flows[0]["turns"][0]["state"]
        self.advisor.models.pop(3)
        with patch.object(self.advisor.models[4], "predict", side_effect=AssertionError("wrong slot")):
            result = self.advisor(state)
        self.assertEqual((result["status"], result["best"]), ("unavailable", None))

    def test_closed_window_suppresses_an_inflight_policy_result(self):
        from advice_worker import AdviceWorker
        from monitor import accept_event
        opened, closed = self.flows[0]["turns"][:2]
        started, release = Event(), Event()

        def calculate(state):
            if state["canAct"]:
                started.set()
                if not release.wait(3):
                    raise AssertionError("test did not release inference")
            return self.advisor(state)

        worker = AdviceWorker(calculate)
        try:
            accept_event(worker, Mock(), opened)
            self.assertTrue(started.wait(3))
            accept_event(worker, Mock(), closed)
            release.set()
            with worker.condition:
                self.assertTrue(worker.condition.wait_for(lambda: worker.completed is not None, 3))
            result = worker.take_result()
            self.assertEqual(result["adviceKey"], f'{closed["session"]}:{closed["serial"]}')
            self.assertEqual((result["advice"]["status"], result["advice"]["best"]), ("waiting", None))
            self.assertTrue(any(item["outcome"] == "superseded" and item["stage"] == "running"
                                for item in worker.take_diagnostics()))
        finally:
            worker.close()
            release.set()
            worker.thread.join(3)


if __name__ == "__main__":
    unittest.main()
