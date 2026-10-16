"""Pilot screening cannot hide riichi regressions or change validation subsets."""
from copy import deepcopy
import unittest

from policy_experiment_gate import evaluate_experiment


def result():
    return {"validationIdentity": "same-frozen-validation", "metrics": {
        "samples": 1100, "choices": 1000, "forced": 100, "choiceNll": .7, "choiceTop1": .745,
        "byAction": {"discard": {"count": 800, "correct": 600}},
        "byOpportunity": {
            "riichi": {"opportunityCount": 400, "actualPositive": 100, "predictedPositive": 100,
                       "truePositive": 70, "exactCorrectPositive": 60, "falsePositive": 30,
                       "falseNegative": 30, "exactCorrect": 250, "passAvailable": 0,
                       "passCorrect": 0, "passAvailableExactCorrect": 0},
            "daiminkan": {"opportunityCount": 100, "actualPositive": 10, "predictedPositive": 10,
                          "truePositive": 6, "exactCorrectPositive": 5, "falsePositive": 4,
                          "falseNegative": 4, "exactCorrect": 80, "passAvailable": 100,
                          "passCorrect": 90, "passAvailableExactCorrect": 80}}}}


def policy():
    guards = []
    paths = [("choiceNll", "lower", 100), ("choiceTop1", "higher", 100),
             ("byAction.discard.accuracy", "higher", 100)]
    paths += [(f"byOpportunity.riichi.{metric}", "lower" if metric == "falsePositiveRate" else "higher", 50)
              for metric in ("recall", "exactPositiveRecall", "precision", "falsePositiveRate", "exactCandidateTop1")]
    paths += [(f"byOpportunity.daiminkan.{metric}", "higher", 5)
              for metric in ("precision", "recall", "passAvailableExactCandidateTop1")]
    for path, direction, support in paths:
        guards.append({"metric": path, "direction": direction, "tolerance": 0.,
                       "minimumSupport": support, "against": ["v1", "parent", "control"]})
    return {"guards": guards, "improvementMode": "any", "improvements": [
        {"metric": "byOpportunity.riichi.exactPositiveRecall", "direction": "higher",
         "minimumDelta": .01, "minimumSupport": 50, "against": ["control"]}]}


class ExperimentGateTests(unittest.TestCase):
    def setUp(self):
        self.base = result()
        self.treatment = deepcopy(self.base)
        self.rules = policy()

    def run_gate(self):
        return evaluate_experiment(self.treatment, self.base,
                                   {"v1": deepcopy(self.base), "parent": deepcopy(self.base)}, self.rules)

    def improve_riichi(self):
        self.treatment["metrics"]["byOpportunity"]["riichi"].update(
            truePositive=75, falseNegative=25, falsePositive=25, exactCorrectPositive=65, exactCorrect=255)

    def test_pass_is_only_full_retrain_screening_and_contains_all_deltas(self):
        self.improve_riichi()
        gate = self.run_gate()
        self.assertEqual(gate["status"], "passed_screening")
        self.assertTrue(gate["recommendFullRetrain"])
        self.assertFalse(gate["deployable"])
        self.assertEqual(len(gate["checks"]), 34)
        self.assertAlmostEqual(gate["checks"][-1]["delta"], .05)

    def test_aggregate_improvement_does_not_hide_riichi_regression(self):
        self.treatment["metrics"].update(choiceNll=.6, choiceTop1=.8)
        self.treatment["metrics"]["byOpportunity"]["riichi"].update(
            truePositive=60, falseNegative=40, predictedPositive=90, exactCorrectPositive=55)
        gate = self.run_gate()
        self.assertEqual(gate["status"], "rejected")
        self.assertTrue(any(c["metric"].endswith(".recall") and c["status"] == "failed" for c in gate["checks"]))

    def test_false_positive_inflation_is_rejected_despite_better_recall(self):
        self.improve_riichi()
        self.treatment["metrics"]["byOpportunity"]["riichi"].update(falsePositive=65, predictedPositive=140)
        gate = self.run_gate()
        self.assertEqual(gate["status"], "rejected")
        fpr = next(c for c in gate["checks"] if c["metric"].endswith(".falsePositiveRate"))
        self.assertEqual(fpr["support"], 300)
        self.assertEqual(fpr["status"], "failed")

    def test_wrong_tile_regression_is_not_hidden_by_correct_action_type(self):
        self.improve_riichi()
        self.treatment["metrics"]["byOpportunity"]["riichi"]["exactCorrectPositive"] = 59
        self.assertEqual(self.run_gate()["status"], "rejected")

    def test_different_subset_identity_is_invalid(self):
        self.improve_riichi()
        self.treatment["validationIdentity"] = "another-subset"
        gate = self.run_gate()
        self.assertEqual(gate["status"], "invalid_evidence")
        self.assertFalse(gate["recommendFullRetrain"])

    def test_same_hash_with_changed_invariant_counts_is_invalid(self):
        self.improve_riichi()
        self.treatment["metrics"]["byOpportunity"]["riichi"]["opportunityCount"] += 1
        gate = self.run_gate()
        self.assertEqual(gate["status"], "invalid_evidence")
        self.assertIn("byOpportunity.riichi.opportunityCount", gate["evidenceIssues"][0]["fields"])

    def test_different_prediction_counts_are_allowed(self):
        self.improve_riichi()
        self.treatment["metrics"]["byOpportunity"]["riichi"].update(predictedPositive=95, falsePositive=20)
        self.assertEqual(self.run_gate()["status"], "passed_screening")

    def test_inconsistent_confusion_counts_are_invalid(self):
        self.improve_riichi()
        self.treatment["metrics"]["byOpportunity"]["riichi"]["predictedPositive"] = 99
        self.assertEqual(self.run_gate()["status"], "invalid_evidence")

    def test_missing_or_zero_precision_denominator_never_passes(self):
        self.improve_riichi()
        opportunity = self.treatment["metrics"]["byOpportunity"]["daiminkan"]
        opportunity.update(predictedPositive=0, truePositive=0, falsePositive=0,
                           falseNegative=10, exactCorrectPositive=0)
        gate = self.run_gate()
        self.assertEqual(gate["status"], "insufficient_evidence")
        precision = next(c for c in gate["checks"] if c["metric"] == "byOpportunity.daiminkan.precision")
        self.assertEqual(precision["support"], 0)
        self.assertIsNone(precision["value"])
        del opportunity["predictedPositive"]
        self.assertEqual(self.run_gate()["status"], "insufficient_evidence")

    def test_reference_support_is_checked_independently(self):
        self.improve_riichi()
        self.treatment["metrics"]["byOpportunity"]["riichi"].update(
            predictedPositive=110, truePositive=85, falseNegative=15)
        self.rules["guards"][5]["minimumSupport"] = 101  # Riichi precision: baseline predicts only 100.
        gate = self.run_gate()
        self.assertEqual(gate["status"], "insufficient_evidence")
        precision = next(c for c in gate["checks"] if c["metric"] == "byOpportunity.riichi.precision")
        self.assertEqual((precision["support"], precision["referenceSupport"]), (110, 100))

    def test_missing_label_denominator_is_insufficient_rather_than_subset_mismatch(self):
        self.improve_riichi()
        del self.treatment["metrics"]["byOpportunity"]["riichi"]["actualPositive"]
        self.assertEqual(self.run_gate()["status"], "insufficient_evidence")

    def test_invalid_global_probability_is_not_a_pass(self):
        self.improve_riichi()
        self.treatment["metrics"]["choiceTop1"] = 1.1
        self.assertEqual(self.run_gate()["status"], "invalid_evidence")

    def test_no_improvement_is_not_a_pass(self):
        self.assertEqual(self.run_gate()["status"], "rejected")

    def test_same_pass_subset_floor_compares_model_and_always_pass(self):
        self.improve_riichi()
        self.rules["guards"].append({"metric": "byOpportunity.daiminkan.passAvailableExactCandidateTop1",
            "againstMetric": "byOpportunity.daiminkan.alwaysPassTop1", "direction": "higher",
            "tolerance": 0., "minimumSupport": 50, "against": ["control"]})
        gate = self.run_gate()
        self.assertEqual(gate["status"], "rejected")
        check = next(c for c in gate["checks"] if c["againstMetric"].endswith(".alwaysPassTop1"))
        self.assertEqual((check["support"], check["referenceSupport"]), (100, 100))
        self.assertAlmostEqual(check["delta"], -.1)

    def test_stored_derived_ratios_cannot_mask_count_regression(self):
        self.improve_riichi()
        self.treatment["metrics"]["byOpportunity"]["riichi"].update(
            truePositive=60, falseNegative=40, predictedPositive=85, exactCorrectPositive=59,
            recall=1., precision=1., exactPositiveRecall=1.)
        self.assertEqual(self.run_gate()["status"], "rejected")

    def test_thresholds_and_improvements_cannot_be_implicit(self):
        del self.rules["guards"][0]["tolerance"]
        with self.assertRaises(ValueError):
            self.run_gate()
        self.rules = policy()
        self.rules["improvements"] = []
        with self.assertRaises(ValueError):
            self.run_gate()


if __name__ == "__main__":
    unittest.main()
