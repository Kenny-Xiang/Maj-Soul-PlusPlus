"""Focused binary losses preserve full labels, negatives and base normalization."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import torch
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "optional policy training dependencies are not installed")
class ActionBoundaryLossTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def actions(self, rows, width=None):
        from policy_features import ACTIONS
        result = torch.zeros(len(rows), width or max(map(len, rows)), len(ACTIONS))
        for row, names in enumerate(rows):
            for col, name in enumerate(names):
                result[row, col, ACTIONS.index(name)] = 1
        return result

    def test_disabled_preserves_exact_loss_and_gradients(self):
        from policy_corpus_training import supervised_loss
        actions = self.actions([["pass", "daiminkan"], ["riichi", "discard"]], 3)
        targets = torch.tensor([0, 0])
        for disabled in (None, {}, {"riichi": 0., "daiminkan": 0.}):
            scores = torch.tensor([[1., 2., -torch.inf], [3., 0., -torch.inf]], requires_grad=True)
            reference = scores.detach().clone().requires_grad_()
            ce = torch.nn.functional.cross_entropy(reference, targets, reduction="none")
            expected = (2 * ce[0] + 3 * ce[1]) / 5
            actual = supervised_loss(scores, targets, actions, {"pass": .5, "riichi": 3.},
                                     {"daiminkan": 4.}, disabled)
            torch.testing.assert_close(actual, expected, rtol=0, atol=0)
            actual.backward()
            expected.backward()
            torch.testing.assert_close(scores.grad, reference.grad, rtol=0, atol=0)

    def test_multiple_parameters_all_negatives_and_original_weight_denominator(self):
        from policy_corpus_training import supervised_loss
        actions = self.actions([["riichi", "riichi", "discard", "kita"],
                                ["daiminkan", "pon", "pass"], ["discard", "discard"]], 5)
        scores = torch.tensor([[0., 1., 2., 3., -torch.inf],
                               [2., 1., 0., -torch.inf, -torch.inf],
                               [1., 2., -torch.inf, -torch.inf, -torch.inf]], requires_grad=True)
        targets = torch.tensor([1, 2, 0])
        reference = scores.detach().clone().requires_grad_()
        probabilities = reference.softmax(dim=1)
        ce = torch.nn.functional.cross_entropy(reference, targets, reduction="none")
        # A positive declaration accepts either declaration parameter. A true
        # negative kan accepts both pon and pass in the auxiliary only.
        binary_r = -probabilities[0, :2].sum().log()
        binary_k = -probabilities[1, 1:3].sum().log()
        expected = (2 * (ce[0] + .5 * binary_r) + 8 * (ce[1] + 2 * binary_k) + ce[2]) / 11
        actual = supervised_loss(scores, targets, actions, {"pass": 2.},
                                 {"riichi": 2., "daiminkan": 4.},
                                 {"riichi": .5, "daiminkan": 2.})
        torch.testing.assert_close(actual, expected)
        actual.backward()
        expected.backward()
        torch.testing.assert_close(scores.grad, reference.grad)
        self.assertEqual(float(scores.grad[:, -1].abs().sum()), 0.)
        self.assertGreater(float(scores.grad[1].abs().sum()), 0.)

    def test_binary_negative_does_not_reweight_actual_type_competition(self):
        from policy_corpus_training import supervised_loss
        actions = self.actions([["daiminkan", "pass", "pon"]])
        targets = torch.tensor([1])
        scores = torch.tensor([[0., 1., 2.]])
        ce = torch.nn.functional.cross_entropy(scores, targets)
        binary = -scores.softmax(dim=1)[0, 1:].sum().log()
        actual = supervised_loss(scores, targets, actions, {}, action_boundary_weights={"daiminkan": 1.})
        torch.testing.assert_close(actual, ce + binary)
        self.assertLess(float(actual), float(2 * ce))

    def test_two_candidates_equal_boundary_scaling_without_denominator_change(self):
        from policy_corpus_training import supervised_loss
        scores = torch.tensor([[2., 1.], [1., 2.]], requires_grad=True)
        actions = self.actions([["riichi", "discard"], ["riichi", "discard"]])
        targets = torch.tensor([0, 1])
        ce = torch.nn.functional.cross_entropy(scores, targets, reduction="none")
        actual = supervised_loss(scores, targets, actions, {"riichi": 2.}, {"riichi": 3.},
                                 {"riichi": 1.})
        torch.testing.assert_close(actual, (6 * 2 * ce[0] + 3 * 2 * ce[1]) / 9)

    def test_absent_opportunities_and_all_focal_candidates_add_zero(self):
        from policy_corpus_training import supervised_loss
        for names in (["discard", "discard"], ["riichi", "riichi"]):
            scores = torch.tensor([[1., 2., -torch.inf]], requires_grad=True)
            actions = self.actions([names], 3)
            targets = torch.tensor([1])
            actual = supervised_loss(scores, targets, actions, {},
                                     action_boundary_weights={"riichi": 1., "daiminkan": 1.})
            expected = torch.nn.functional.cross_entropy(scores, targets)
            torch.testing.assert_close(actual, expected, rtol=0, atol=0)
            actual.backward()
            self.assertTrue(torch.isfinite(scores.grad).all())
            self.assertEqual(float(scores.grad[0, 2]), 0.)

    def test_extreme_scores_have_finite_loss_and_gradients(self):
        from policy_corpus_training import supervised_loss
        scores = torch.tensor([[10000., -10000., -9999., -torch.inf],
                               [-10000., 10000., 9999., -torch.inf]], requires_grad=True)
        actions = self.actions([["daiminkan", "pass", "pon"], ["riichi", "riichi", "discard"]], 4)
        loss = supervised_loss(scores, torch.tensor([1, 0]), actions, {},
                               action_boundary_weights={"riichi": 1., "daiminkan": 1.})
        self.assertTrue(torch.isfinite(loss))
        loss.backward()
        self.assertTrue(torch.isfinite(scores.grad).all())
        self.assertEqual(float(scores.grad[:, -1].abs().sum()), 0.)

    def test_invalid_configuration_is_rejected_before_reading_any_data(self):
        import policy_corpus_training as corpus
        invalid = ([], "riichi", {"pon": 1.}, {"riichi": -1.}, {"riichi": float("nan")},
                   {"daiminkan": float("inf")}, {"riichi": True}, {"riichi": "1"}, {"riichi": None})
        with patch.object(corpus, "read_manifest") as reader:
            for weights in invalid:
                with self.subTest(weights=weights), self.assertRaisesRegex(ValueError, "action boundary weights"):
                    corpus.train_corpus("unread", "unwritten", action_boundary_weights=weights)
            reader.assert_not_called()

    def test_synthetic_training_records_weights_and_resume_rejects_changes(self):
        import policy_corpus_training as corpus
        from test_policy_opportunity_metrics import OpportunityMetricTests
        fixture = OpportunityMetricTests()
        samples = [fixture.sample(["riichi", "discard"], 0, 0),
                   fixture.sample(["daiminkan", "pass", "pon"], 1, 1)]
        partitions = {name: [{"gameId": name, "samples": 2}] for name in ("train", "validation")}
        groups = {name: [name] for name in partitions}
        audit = {"actions": {"riichi": 1, "pass": 1}, "labelSources": {"accepted": 2}, "duplicateSamples": 0}
        weights = {"riichi": 1., "daiminkan": 1.}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(corpus, "read_manifest", return_value=(partitions, groups, {})), \
                patch.object(corpus, "load_game", return_value=(samples, audit)), \
                patch.object(corpus, "supervised_loss", wraps=corpus.supervised_loss) as loss, \
                redirect_stdout(io.StringIO()):
            output = Path(folder) / "fixture.npz"
            options = {"validation_only": True, "config": {"channels": 4, "blocks": 1, "hidden": 8},
                       "action_boundary_weights": weights}
            _, report = corpus.train_corpus("unused", output, **options)
            self.assertEqual(loss.call_args.args[-1], weights)
            self.assertEqual(report["actionBoundaryWeights"], weights)
            saved = torch.load(output.with_suffix(".resume.pt"), weights_only=True)
            self.assertEqual(saved["binding"]["actionBoundaryWeights"], weights)
            with self.assertRaisesRegex(ValueError, "differs in source"):
                corpus.train_corpus("unused", output, resume=True, **{**options, "action_boundary_weights": {}})

    def test_cli_passes_json_boundary_weights_and_default(self):
        import policy_corpus_training as corpus
        script = Path(__file__).resolve().parents[1] / "scripts" / "policy_train_corpus.py"
        spec = importlib.util.spec_from_file_location("boundary_cli", script)
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        report = {"purpose": "fixture", "dataAudit": {"selectedGames": 0, "selectedGameCounts": {}}}
        for weights in ({}, {"riichi": 1., "daiminkan": 1.}):
            argv = [str(script), "--manifest", "unused", "--players", "3", "--output", "unused.npz"]
            if weights:
                argv += ["--action-boundary-weights", json.dumps(weights)]
            with patch("sys.argv", argv), patch.object(corpus, "train_corpus", return_value=(None, report)) as train, \
                    redirect_stdout(io.StringIO()):
                cli.main()
            self.assertEqual(train.call_args.kwargs["action_boundary_weights"], weights)


if __name__ == "__main__":
    unittest.main()
