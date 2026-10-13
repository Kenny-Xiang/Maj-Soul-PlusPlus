"""Opportunity metrics keep exact candidates and action-type confusion separate."""
import unittest

try:
    import numpy as np
    import torch
except ImportError:
    np = torch = None


@unittest.skipIf(torch is None, "optional policy training dependencies are not installed")
class OpportunityMetricTests(unittest.TestCase):
    def sample(self, action_types, target, predicted):
        from policy_features import ACTIONS, ACTION_NAMES, GLOBAL_NAMES, PLANE_NAMES
        actions = np.zeros((len(action_types), len(ACTION_NAMES)), dtype=np.float32)
        for index, name in enumerate(action_types):
            actions[index, ACTIONS.index(name)] = 1
        # Two candidates of one type remain distinct indices. The fixture model
        # reads this extra column as its deterministic score, not as a feature.
        actions[predicted, -1] = 5
        return {"planes": np.zeros((len(PLANE_NAMES), 34), dtype=np.float32),
                "globals": np.zeros(len(GLOBAL_NAMES), dtype=np.float32),
                "actions": actions, "action": action_types[target], "target": target}

    def model(self):
        class FixedScores(torch.nn.Module):
            def forward(self, planes, globals_, actions, mask):
                return actions[:, :, -1].masked_fill(~mask, -torch.inf)
        return FixedScores()

    def samples(self):
        return [self.sample(["pass", "chi", "chi"], 1, 2),
                self.sample(["pass", "chi", "chi"], 2, 2),
                self.sample(["pass", "chi"], 0, 1),
                self.sample(["pass", "chi"], 1, 0),
                self.sample(["pass", "chi"], 0, 0),
                self.sample(["discard", "riichi"], 0, 0),
                self.sample(["discard", "chi", "chi"], 1, 1),
                self.sample(["chi"], 0, 0)]

    def test_type_confusion_counts_each_opportunity_once_and_preserves_exact_identity(self):
        from policy_training import evaluate
        metrics = evaluate(self.model(), self.samples(), "cpu", 3)
        chi = metrics["byOpportunity"]["chi"]
        expected = {"opportunityCount": 6, "actualPositive": 4, "predictedPositive": 4,
                    "truePositive": 3, "exactCorrectPositive": 2, "falsePositive": 1,
                    "falseNegative": 1, "exactCorrect": 3, "passAvailable": 5,
                    "passCorrect": 2, "passAvailableExactCorrect": 2}
        for name, count in expected.items():
            self.assertEqual(chi[name], count, name)
        self.assertEqual(chi["precision"], .75)
        self.assertEqual(chi["recall"], .75)
        self.assertEqual(chi["exactPositiveRecall"], .5)
        self.assertEqual(chi["falseSelectionRate"], 1 / 6)
        self.assertEqual(chi["falsePositiveRate"], .5)
        self.assertEqual(chi["exactCandidateTop1"], .5)
        self.assertEqual(chi["alwaysPassTop1"], .4)
        self.assertEqual(chi["passAvailableExactCandidateTop1"], .4)
        self.assertEqual(metrics["byAction"]["chi"], {"count": 4, "correct": 2, "accuracy": .5})
        self.assertEqual((metrics["samples"], metrics["choices"], metrics["forced"]), (8, 7, 1))
        self.assertEqual(metrics["choiceTop1"], 4 / 7)
        self.assertIn("Choice windows only", metrics["opportunityScope"])

    def test_undefined_ratios_remain_null_and_forced_actions_are_excluded(self):
        from policy_training import evaluate
        metrics = evaluate(self.model(), self.samples(), "cpu", 8)
        riichi = metrics["byOpportunity"]["riichi"]
        for name in ("precision", "recall", "exactPositiveRecall", "alwaysPassTop1",
                     "passAvailableExactCandidateTop1"):
            self.assertIsNone(riichi[name], name)
        self.assertEqual(riichi["opportunityCount"], 1)
        forced = evaluate(self.model(), [self.sample(["ron"], 0, 0)], "cpu", 1)
        self.assertEqual(forced["byOpportunity"], {})
        self.assertEqual(forced["byAction"], {})
        self.assertIsNone(forced["choiceTop1"])

    def test_per_game_merge_uses_integer_numerators_and_pass_subset_denominators(self):
        from policy_corpus_training import merge_metrics
        from policy_training import evaluate
        samples = self.samples()
        direct = evaluate(self.model(), samples, "cpu", 3)
        partitions = [samples[:1], samples[1:5], samples[5:7], samples[7:]]
        merged = merge_metrics(evaluate(self.model(), part, "cpu", 2) for part in partitions)
        for name in ("samples", "choices", "forced", "byAction", "byOpportunity",
                     "opportunityScope", "macroActionAccuracy", "choiceTop1", "choiceTop3"):
            self.assertEqual(merged[name], direct[name], name)
        self.assertAlmostEqual(merged["choiceNll"], direct["choiceNll"], places=6)
        self.assertEqual(merge_metrics([])["byOpportunity"], {})


if __name__ == "__main__":
    unittest.main()
