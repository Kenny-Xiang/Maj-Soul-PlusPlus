"""End-to-end policy contracts, export parity and an actual learning smoke test."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

try:
    import numpy as np
    import torch
except ImportError:
    np = torch = None


def visible_state(players=4):
    return {"phase": "playing", "playerCount": players, "selfSeat": 0,
            "hand": ["1p", "2p", "3p", "4p", "0p", "5p", "6p", "7p", "8p", "1s", "2s", "3s", "7z", "5p"],
            "handComplete": True, "historyComplete": True, "recovery": None,
            "canAct": True, "canDiscard": True, "operations": [1],
            "operationDetails": [{"type": 1, "combination": []}], "forbiddenDiscards": [],
            "lastStep": 12, "lastAction": {"name": "ActionDealTile", "seat": 0, "tile": "5p", "step": 12},
            "lastDraw": "5p", "melds": [[], [], [], []], "rivers": [[], [], [], []],
            "north": [0, 0, 0, 0], "riichi": [False] * 4, "riichiPending": [False] * 4,
            "doubleRiichi": [False] * 4, "round": {"chang": 0, "ju": 0, "ben": 0},
            "scores": [35000 if players == 3 else 25000] * players, "left": 40,
            "doras": ["9m"], "riichiSticks": 0, "furiten": False,
            "match": {"playerCount": players, "roundCount": 2}}


@unittest.skipIf(torch is None, "install requirements-training.txt for policy model tests")
class PolicyModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        from policy_training import CandidatePolicy
        torch.manual_seed(17)
        self.network = CandidatePolicy({"channels": 8, "blocks": 2, "hidden": 16}).eval()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "model.npz"
        self.export()

    def export(self, players=4, purpose="behavior-cloning"):
        from policy_training import export_model
        export_model(self.network, self.path, {"playerCount": players, "purpose": purpose})

    def test_export_matches_training_for_both_modes_and_many_candidate_counts(self):
        from policy_actions import legal_actions
        from policy_features import encode_state, encode_actions
        from policy_model import PolicyModel
        for players in (3, 4):
            self.export(players)
            model = PolicyModel(self.path)
            state = visible_state(players)
            planes, scalars = encode_state(state)
            actions = encode_actions(state, legal_actions(state))
            for count in (1, 2, len(actions)):
                with torch.no_grad():
                    expected = self.network(torch.tensor(planes[None]), torch.tensor(scalars[None]),
                                            torch.tensor(actions[None, :count]),
                                            torch.ones((1, count), dtype=torch.bool)).numpy()[0]
                actual = model.logits(planes, scalars, actions[:count])
                np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-6)

    def test_padding_is_masked_and_not_an_action(self):
        from policy_training import batch_tensors
        from policy_features import encode_state, encode_actions
        from policy_actions import legal_actions
        state = visible_state()
        planes, scalars = encode_state(state)
        actions = encode_actions(state, legal_actions(state))
        rows = [{"planes": planes, "globals": scalars, "actions": actions[:count], "target": 0}
                for count in (1, len(actions))]
        p, g, a, mask, _ = batch_tensors(rows, "cpu")
        with torch.no_grad():
            logits = self.network(p, g, a, mask)
        self.assertTrue(torch.isneginf(logits[0, 1:]).all())
        self.assertEqual(float(logits.softmax(1)[0, 0]), 1.)

    def test_red_and_draw_origin_have_distinct_features(self):
        from policy_actions import legal_actions
        from policy_features import encode_actions
        state = visible_state()
        actions = [a for a in legal_actions(state) if a.get("tile") in ("0p", "5p")]
        encoded = encode_actions(state, actions)
        self.assertEqual(len(actions), 3)
        self.assertEqual(len({row.tobytes() for row in encoded}), 3)

    def test_prediction_is_pure_normalized_and_legal(self):
        from policy_actions import legal_actions, action_key
        from policy_model import PolicyModel
        state = visible_state()
        original = deepcopy(state)
        predictions = PolicyModel(self.path).predict(state)
        self.assertEqual(state, original)
        self.assertEqual({action_key(a) for a in predictions}, {action_key(a) for a in legal_actions(state)})
        self.assertAlmostEqual(sum(a["policyProbability"] for a in predictions), 1., places=6)
        self.assertEqual([a["policyProbability"] for a in predictions],
                         sorted((a["policyProbability"] for a in predictions), reverse=True))

    def test_runtime_rejects_wrong_mode_and_incomplete_state(self):
        from policy_model import PolicyModel, PolicyAdvisor
        with self.assertRaisesRegex(ValueError, "player count"):
            PolicyModel(self.path).predict(visible_state(3))
        advisor = PolicyAdvisor({4: self.path})
        state = visible_state()
        state["historyComplete"] = False
        self.assertEqual(advisor(state)["status"], "unavailable")
        self.assertEqual(advisor(visible_state(3))["status"], "unavailable")
        state["canAct"] = False
        self.assertEqual(advisor(state)["status"], "waiting")

    def test_sanma_kita_survives_training_encoding_export_and_inference(self):
        from policy_model import PolicyModel
        from policy_training import batch_tensors
        from policy_actions import legal_actions
        from policy_features import encode_state, encode_actions
        self.export(players=3)
        state = visible_state(3)
        state["hand"][12] = "4z"
        state["operations"].append(11)
        state["operationDetails"].append({"type": 11, "combination": []})
        candidates = legal_actions(state)
        target = next(i for i, action in enumerate(candidates) if action["action"] == "kita")
        planes, scalars = encode_state(state)
        encoded = encode_actions(state, candidates)
        p, g, a, mask, labels = batch_tensors([{"planes": planes, "globals": scalars,
                                               "actions": encoded, "target": target}], "cpu")
        loss = torch.nn.functional.cross_entropy(self.network(p, g, a, mask), labels)
        self.assertTrue(torch.isfinite(loss))
        prediction = PolicyModel(self.path).predict(state)
        kita = next(action for action in prediction if action["action"] == "kita")
        self.assertEqual(kita["consumed"], ["4z"])
        self.assertFalse(kita["moqie"])
        self.assertGreater(kita["policyProbability"], 0)
        self.assertFalse(any(action["action"] == "chi" for action in prediction))

    def test_smoke_model_cannot_produce_executable_advice(self):
        from policy_model import PolicyAdvisor
        self.export(purpose="smoke")
        result = PolicyAdvisor({4: self.path})(visible_state())
        self.assertEqual(result["status"], "analysis")
        self.assertIsNotNone(result["best"])
        self.assertNotIn("winProbability", result["best"])

    def test_real_optimizer_step_reduces_choice_loss_and_exports(self):
        from policy_actions import legal_actions
        from policy_features import encode_state, encode_actions
        from policy_training import train
        from policy_model import PolicyModel
        state = visible_state()
        planes, scalars = encode_state(state)
        actions = encode_actions(state, legal_actions(state))
        samples = [{"game": "synthetic-pipeline-check", "planes": planes, "globals": scalars,
                    "actions": actions, "target": 2, "action": "discard", "labelSource": "accepted"} for _ in range(8)]
        _, report = train(samples, {"channels": 4, "blocks": 1, "hidden": 16}, players=4,
                          epochs=8, batch_size=8, learning_rate=.02, seed=42, device="cpu",
                          smoke=True, output=self.path, report={})
        self.assertLess(report["metrics"]["train"]["choiceNll"], report["initialTrain"]["choiceNll"])
        self.assertIsNone(report["metrics"]["test"])
        self.assertIsNone(report["metrics"]["validation"])
        self.assertEqual(PolicyModel(self.path).metadata["purpose"], "smoke")

    def test_monitor_factory_preserves_default_and_load_failure_is_explicit(self):
        from monitor import create_advice_worker
        worker = create_advice_worker({})
        self.addCleanup(worker.close)
        self.assertTrue(worker.cooperative)
        configured = create_advice_worker({"MAJSOUL_POLICY_MODEL_4P": str(self.path)})
        self.addCleanup(configured.close)
        self.assertFalse(configured.cooperative)
        self.assertEqual(configured.calculate(visible_state())["kind"], "policy")
        broken = create_advice_worker({"MAJSOUL_POLICY_MODEL_4P": str(self.path) + ".missing"})
        self.addCleanup(broken.close)
        self.assertEqual(broken.calculate(visible_state())["status"], "unavailable")
        # A truncated NPZ must disable this backend instead of crashing startup.
        self.path.write_bytes(self.path.read_bytes()[:100])
        corrupt = create_advice_worker({"MAJSOUL_POLICY_MODEL_4P": str(self.path)})
        self.addCleanup(corrupt.close)
        self.assertEqual(corrupt.calculate(visible_state())["status"], "unavailable")

    def test_normal_training_requires_independent_games_and_reports_held_out_metrics(self):
        from policy_actions import legal_actions
        from policy_features import encode_state, encode_actions
        from policy_training import train
        from policy_model import PolicyModel
        samples = []
        for index in range(3):
            state = visible_state()
            state["left"] -= index
            planes, scalars = encode_state(state)
            samples.append({"game": f"synthetic-game-{index}", "planes": planes, "globals": scalars,
                            "actions": encode_actions(state, legal_actions(state)), "target": index,
                            "action": "discard", "labelSource": "accepted"})
        options = dict(players=4, epochs=2, batch_size=8, learning_rate=.001,
                       seed=42, device="cpu", smoke=False, output=self.path, report={})
        with self.assertRaisesRegex(ValueError, "three distinct games"):
            train(samples[:1], self.network.config, **options)
        _, report = train(samples, self.network.config, **options)
        self.assertEqual({name: len(games) for name, games in report["gameSplit"].items()},
                         {"train": 1, "validation": 1, "test": 1})
        for name in ("train", "validation", "test"):
            self.assertEqual(report["metrics"][name]["choices"], 1)
            self.assertIsNotNone(report["metrics"][name]["choiceNll"])
        self.assertEqual(PolicyModel(self.path).metadata["purpose"], "behavior-cloning")


if __name__ == "__main__":
    unittest.main()
