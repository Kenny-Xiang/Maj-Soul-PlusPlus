"""Independent invariants for candidate scoring, visibility and data grouping."""
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

from policy_actions import legal_actions
from test_policy_actions import state, hand_with

if np is not None and torch is not None:
    from policy_features import RULESET, encode_state, encode_actions
    from policy_model import PolicyModel
    from policy_training import CandidatePolicy, export_model, read_samples, split_games


def complete_state(players=4):
    value = state(hand_with(["0p", "5p"], 13) + ["5p"], players=players,
                  ops=[{"type": 1, "combination": []}, {"type": 7, "combination": ["5p"]}])
    value.update(scores=[25000, 28000, 22000, 25000][:players], doras=["9p"], north=[0] * 4,
                 riichiSticks=1, left=50, round={"chang": 1, "ju": 1, "ben": 2},
                 furiten=False, doubleRiichi=[False] * 4, match={"roundCount": 2})
    return value


@unittest.skipIf(np is None or torch is None, "optional policy/training dependencies are not installed")
class PolicyIndependentReviewTests(unittest.TestCase):
    def test_hidden_and_outcome_fields_never_change_actor_features(self):
        visible = complete_state()
        before = encode_state(visible)
        contaminated = deepcopy(visible)
        contaminated.update(opponentHands=[["7z"] * 13], wall=["4z"] * 70,
                            uraDoras=["1p"], futureEvents=[{"name": "ActionHule"}],
                            outcome={"rank": 1, "points": 99000}, accountId=123,
                            opponentsOperations=[{"type": 9}], rawRecord={"tiles1": ["7z"] * 13})
        after = encode_state(contaminated)
        for original, changed in zip(before, after):
            np.testing.assert_array_equal(original, changed)

    def test_seat_rotation_preserves_visible_and_candidate_encoding(self):
        for players in (3, 4):
            original = complete_state(players)
            original["canDiscard"] = False
            original["lastDraw"] = None
            original["hand"] = hand_with(["0p", "5p"], 13)
            original["operations"] = [3]
            original["operationDetails"] = [{"type": 3, "combination": ["0p|5p"]}]
            original["lastAction"] = {"name": "ActionDiscardTile", "seat": players - 1, "tile": "5p", "step": 12}
            original["rivers"][players - 1] = [{"tile": "5p", "step": 12, "moqie": True, "called": False}]
            base_actions = legal_actions(original)
            for shift in range(1, players):
                rotated = deepcopy(original)
                for key in ("scores", "rivers", "melds", "north", "riichi", "riichiPending", "doubleRiichi"):
                    for seat in range(players):
                        rotated[key][(seat + shift) % players] = deepcopy(original[key][seat])
                rotated["selfSeat"] = shift
                rotated["lastAction"]["seat"] = (original["lastAction"]["seat"] + shift) % players
                rotated["round"]["ju"] = (original["round"]["ju"] + shift) % players
                for expected, actual in zip(encode_state(original), encode_state(rotated)):
                    np.testing.assert_array_equal(expected, actual)
                rotated_actions = legal_actions(rotated)
                by_kind = {action["action"]: action for action in rotated_actions}
                rotated_actions = [by_kind[action["action"]] for action in base_actions]
                np.testing.assert_array_equal(encode_actions(original, base_actions),
                                              encode_actions(rotated, rotated_actions))

    def test_candidate_permutation_changes_neither_scores_nor_softmax(self):
        torch.manual_seed(17)
        training = CandidatePolicy({"channels": 8, "blocks": 2, "hidden": 16}).eval()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.npz"
            export_model(training, path, {"playerCount": 4, "purpose": "smoke"})
            deployed = PolicyModel(path)
        s = complete_state()
        planes, globals_ = encode_state(s)
        actions = encode_actions(s, legal_actions(s))
        order = np.random.default_rng(19).permutation(len(actions))
        original = deployed.logits(planes, globals_, actions)
        permuted = deployed.logits(planes, globals_, actions[order])
        np.testing.assert_allclose(permuted, original[order], rtol=1e-6, atol=1e-7)
        softmax = lambda logits: np.exp(logits - logits.max()) / np.exp(logits - logits.max()).sum()
        np.testing.assert_allclose(softmax(permuted), softmax(original)[order], rtol=1e-6, atol=1e-7)
        with torch.no_grad():
            expected = training(torch.tensor(planes[None]), torch.tensor(globals_[None]),
                                torch.tensor(actions[order][None]), torch.ones((1, len(actions)), dtype=torch.bool))
        np.testing.assert_allclose(expected.numpy()[0], permuted, rtol=1e-5, atol=1e-6)

    def test_all_views_of_a_game_stay_in_one_split_independently_of_sample_order(self):
        samples = [{"game": f"game-{game}", "seat": seat, "round": hand}
                   for game in range(20) for seat in range(4) for hand in range(2)]
        partitions, groups = split_games(samples, seed=31)
        reversed_partitions, reversed_groups = split_games(list(reversed(samples)), seed=31)
        self.assertEqual(groups, reversed_groups)
        memberships = {}
        for name, values in partitions.items():
            self.assertTrue(values)
            self.assertEqual({v["game"] for v in values}, set(groups[name]))
            self.assertEqual({v["game"] for v in values}, {v["game"] for v in reversed_partitions[name]})
            for value in values:
                memberships.setdefault(value["game"], set()).add(name)
        self.assertTrue(all(len(group) == 1 for group in memberships.values()))
        smoke, smoke_groups = split_games(samples, seed=31, smoke=True)
        self.assertEqual(smoke_groups["validation"], [])
        self.assertEqual(smoke["test"], [])

    def test_sample_ingestion_deduplicates_and_rejects_conflicting_or_illegal_labels(self):
        s = complete_state()
        actions = legal_actions(s)
        sample = {"schemaVersion": 1, "ruleset": RULESET, "gameId": "fixture-game",
                  "roundId": "0", "decisionId": "0:12", "seat": 0, "state": s,
                  "action": actions[0], "labelSource": "accepted"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.jsonl"

            def write(values):
                path.write_text("".join(json.dumps(value) + "\n" for value in values))

            write([sample, sample])
            loaded, audit = read_samples([path], players=4)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(audit["duplicateSamples"], 1)
            write([sample, {**sample, "action": actions[1]}])
            with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
                read_samples([path], players=4)
            write([{**sample, "action": {"action": "discard", "tile": "7z", "moqie": True}}])
            with self.assertRaisesRegex(ValueError, "not in the complete legal"):
                read_samples([path], players=4)
            write([{**sample, "labelSource": "censored_response"}])
            with self.assertRaisesRegex(ValueError, "uncertain action"):
                read_samples([path], players=4)

    def test_model_rejects_incompatible_metadata_and_invalid_weight_payloads(self):
        network = CandidatePolicy({"channels": 4, "blocks": 1, "hidden": 8})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.npz"
            export_model(network, path, {"playerCount": 3, "purpose": "smoke"})
            with np.load(path, allow_pickle=False) as saved:
                arrays = {name: saved[name] for name in saved.files}
            metadata = json.loads(arrays["metadata"].item())
            for key, value in (("actionVersion", 99), ("featureSignature", "wrong"),
                               ("ruleset", "custom-event"), ("playerCount", 5), ("purpose", None)):
                with self.subTest(key=key):
                    bad = {**arrays, "metadata": np.asarray(json.dumps({**metadata, key: value}))}
                    np.savez(path, **bad)
                    with self.assertRaises(ValueError):
                        PolicyModel(path)
            for value in (arrays["conv.weight"].astype(np.float64), arrays["conv.weight"][:1],
                          np.full_like(arrays["conv.weight"], np.nan)):
                np.savez(path, **{**arrays, "conv.weight": value})
                with self.assertRaises(ValueError):
                    PolicyModel(path)
            np.savez(path, **{**arrays, "extra": np.array([1.], dtype=np.float32)})
            with self.assertRaises(ValueError):
                PolicyModel(path)


if __name__ == "__main__":
    unittest.main()
