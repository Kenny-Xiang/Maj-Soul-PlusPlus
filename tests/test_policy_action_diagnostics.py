"""Recorded-action diagnosis distinguishes declaration, tile identity and origin."""
import json
import unittest

try:
    import numpy as np
except ImportError:
    np = None


@unittest.skipIf(np is None, "optional policy NumPy dependency is not installed")
class ActionDiagnosticsTests(unittest.TestCase):
    def sample(self, candidates, target):
        from policy_features import encode_actions
        return {"actions": encode_actions({"selfSeat": 0, "playerCount": 3}, candidates),
                "target": target, "action": candidates[target]["action"]}

    def action(self, kind, tile="5p", moqie=False, **kwargs):
        return {"action": kind, "tile": tile, "moqie": moqie, **kwargs}

    def test_type_confusion_and_exact_counts_have_distinct_denominators(self):
        from policy_action_diagnostics import ActionDiagnostics
        diagnostic = ActionDiagnostics()
        candidates = [self.action("discard"), self.action("riichi"),
                      self.action("riichi", "0p"), self.action("kita", "4z")]
        for target, best in ((1, 0), (1, 3), (0, 1), (1, 2), (1, 1), (0, 0)):
            scores = np.zeros(4)
            scores[best] = 1
            diagnostic.update(self.sample(candidates, target), scores)
        report = diagnostic.report()["byOpportunity"]["riichi"]
        self.assertEqual([report[key] for key in ("opportunityCount", "actualPositive", "predictedPositive",
                                                  "truePositive", "falsePositive", "falseNegative", "trueNegative")],
                         [6, 4, 3, 2, 1, 2, 1])
        self.assertEqual(report["positivePredictedOtherTypes"], {"discard": 1, "kita": 1})
        self.assertEqual(report["exactCorrectPositive"], 1)
        self.assertEqual(report["exactFalseNegative"], 3)
        self.assertEqual(report["exactFalsePositive"], 2)
        self.assertEqual(report["exactPositiveRecall"], .25)
        self.assertEqual(report["recall"], .5)
        self.assertEqual(report["precision"], 2 / 3)
        self.assertEqual(report["falsePositiveRate"], .5)
        self.assertEqual(report["typeConfusion"]["discard"], {"discard": 1, "riichi": 1})

    def test_red_identity_base_tile_and_origin_errors_are_separate(self):
        from policy_action_diagnostics import ActionDiagnostics
        diagnostic = ActionDiagnostics()
        target = self.action("riichi")
        for predicted in (self.action("riichi", "0p"), self.action("riichi", "6p"),
                          self.action("riichi", "5p", True), self.action("riichi", "0p", True),
                          self.action("riichi", "5p", None)):
            diagnostic.update(self.sample([target, predicted], 0), [0., 1.])
        result = diagnostic.report()["byOpportunity"]["riichi"]
        self.assertEqual(result["typeCorrectParameterMismatch"], 5)
        self.assertEqual(result["parameterMismatches"],
                         {"tile": 3, "baseTile": 1, "redIdentityOnly": 2, "moqie": 3, "otherParameters": 0})
        self.assertEqual(result["parameterMismatchPatterns"],
                         {"redIdentityOnly": 1, "baseTile": 1, "moqie": 2, "redIdentityOnly+moqie": 1})

    def test_pair_margins_require_same_red_and_origin_and_have_window_denominators(self):
        from policy_action_diagnostics import ActionDiagnostics
        diagnostic = ActionDiagnostics()
        candidates = [self.action("discard"), self.action("riichi"),
                      self.action("discard", "0p"), self.action("riichi", "0p"),
                      self.action("riichi", "5p", True)]
        diagnostic.update(self.sample(candidates, 1), [4., 1., 2., 4., 100.])
        diagnostic.update(self.sample(candidates[:2], 0), [1., 5.])
        result = diagnostic.report()["riichiDiscardLogitMargin"]
        self.assertEqual(result["allPairs"]["count"], 3)
        self.assertEqual(result["allPairs"]["sum"], 3.)
        self.assertEqual(result["allPairs"]["mean"], 1.)
        self.assertEqual(result["allPairs"]["positive"], 2)
        self.assertEqual(result["allPairs"]["negative"], 1)
        self.assertAlmostEqual(result["allPairs"]["standardDeviation"], np.std([-3., 2., 4.]))
        self.assertEqual(result["windowMeans"]["mean"], 1.75)
        self.assertEqual(result["recordedRiichiPair"]["mean"], -3.)
        self.assertEqual(result["recordedDiscardPair"]["mean"], 4.)

    def test_daiminkan_consumed_identity_error_and_pass_confusion(self):
        from policy_action_diagnostics import ActionDiagnostics
        diagnostic = ActionDiagnostics(("daiminkan",))
        candidates = [self.action("daiminkan", consumed=["5p", "5p", "5p"]),
                      self.action("daiminkan", consumed=["0p", "5p", "5p"]), {"action": "pass"}]
        diagnostic.update(self.sample(candidates, 0), [0., 1., -1.])
        diagnostic.update(self.sample(candidates, 0), [0., 1., 2.])
        result = diagnostic.report()["byOpportunity"]["daiminkan"]
        self.assertEqual(result["typeCorrectParameterMismatch"], 1)
        self.assertEqual(result["parameterMismatches"]["otherParameters"], 1)
        self.assertEqual(result["positivePredictedOtherTypes"], {"pass": 1})
        self.assertNotIn("riichiDiscardLogitMargin", diagnostic.report())

    def test_merge_matches_direct_accumulation_and_report_is_detached_json(self):
        from policy_action_diagnostics import ActionDiagnostics
        candidates = [self.action("discard"), self.action("riichi")]
        direct, left, right = ActionDiagnostics(), ActionDiagnostics(), ActionDiagnostics()
        for index, scores in enumerate(([3., 1.], [0., 3.], [2., 2.])):
            sample = self.sample(candidates, index % 2)
            direct.update(sample, scores)
            (left if index == 0 else right).update(sample, scores)
        left.merge(right)
        self.assertEqual(left.report(), direct.report())
        report = left.report()
        json.dumps(report, allow_nan=False)
        report["byOpportunity"]["riichi"]["typeConfusion"]["discard"]["discard"] = 999
        report["riichiDiscardLogitMargin"]["allPairs"]["count"] = 999
        self.assertEqual(left.report(), direct.report())
        with self.assertRaisesRegex(ValueError, "different"):
            left.merge(ActionDiagnostics(("riichi",)))

    def test_forced_no_opportunity_padding_and_ties(self):
        from policy_action_diagnostics import ActionDiagnostics
        diagnostic = ActionDiagnostics()
        diagnostic.update(self.sample([self.action("riichi")], 0), [1., -np.inf])
        diagnostic.update(self.sample([self.action("discard"), self.action("discard", "6p")], 1), [0., 1.])
        diagnostic.update(self.sample([self.action("discard"), self.action("riichi")], 1), [0., 0., 99.])
        report = diagnostic.report()
        self.assertEqual([report[key] for key in ("samples", "choices", "forced")], [3, 2, 1])
        self.assertEqual(report["byOpportunity"]["riichi"]["falseNegative"], 1)
        self.assertEqual(report["byOpportunity"]["daiminkan"]["recall"], None)
        self.assertEqual(report["riichiDiscardLogitMargin"]["allPairs"]["zero"], 1)

    def test_bad_logits_and_mislabeled_target_fail_before_counting(self):
        from policy_action_diagnostics import ActionDiagnostics
        diagnostic = ActionDiagnostics()
        sample = self.sample([self.action("discard"), self.action("riichi")], 1)
        for scores in ([0.], [[0., 1.]], [0., np.nan], [0., -np.inf]):
            with self.assertRaises(ValueError):
                diagnostic.update(sample, scores)
        with self.assertRaisesRegex(ValueError, "disagrees"):
            diagnostic.update({**sample, "action": "discard"}, [0., 1.])
        self.assertEqual(diagnostic.report()["samples"], 0)

    def test_natural_nll_and_margins_separate_positive_and_negative_windows(self):
        from policy_action_diagnostics import ActionDiagnostics
        diagnostic = ActionDiagnostics()
        candidates = [self.action("discard"), self.action("riichi"), self.action("riichi", "0p")]
        diagnostic.update(self.sample(candidates, 1), np.log([.5, .3, .2]))
        diagnostic.update(self.sample(candidates, 0), np.log([.2, .7, .1]))
        scores = diagnostic.report()["byOpportunity"]["riichi"]["scoreDiagnostics"]
        positive, negative = scores["actualPositive"], scores["actualNegative"]
        self.assertEqual(positive["recordedCandidateNll"]["count"], 1)
        self.assertAlmostEqual(positive["recordedCandidateNll"]["mean"], -np.log(.3))
        self.assertAlmostEqual(positive["recordedTypeNll"]["mean"], -np.log(.5))
        self.assertAlmostEqual(positive["recordedCandidateMargin"]["mean"], np.log(.3 / .5))
        self.assertAlmostEqual(negative["recordedCandidateNll"]["mean"], -np.log(.2))
        self.assertAlmostEqual(negative["bestTypeVsOtherMargin"]["mean"], np.log(.7 / .2))
        self.assertEqual(negative["tiedMaximum"]["positive"], 0)

    def test_shared_huge_score_does_not_erase_nll_or_hide_ties(self):
        from policy_action_diagnostics import ActionDiagnostics
        diagnostic = ActionDiagnostics()
        candidates = [self.action("discard"), self.action("riichi"), self.action("riichi", "0p")]
        diagnostic.update(self.sample(candidates, 1), np.full(3, 1e20, dtype=np.float32))
        scores = diagnostic.report()["byOpportunity"]["riichi"]["scoreDiagnostics"]["actualPositive"]
        self.assertAlmostEqual(scores["recordedCandidateNll"]["mean"], np.log(3))
        self.assertAlmostEqual(scores["recordedTypeNll"]["mean"], np.log(3 / 2))
        self.assertEqual(scores["logitRange"]["zero"], 1)
        self.assertEqual(scores["tiedMaximum"]["positive"], 1)
        self.assertEqual(scores["bestTypeVsOtherMargin"]["zero"], 1)


if __name__ == "__main__":
    unittest.main()
