"""Result assembly verifies provenance and keeps the frozen terminal epoch."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("riichi_result", ROOT / "scripts/policy_riichi_result.py")
result_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(result_module)


def evaluation(identity, nll=.5):
    riichi = {"opportunityCount": 400, "actualPositive": 100, "predictedPositive": 100,
              "truePositive": 70, "exactCorrectPositive": 60, "falsePositive": 30,
              "falseNegative": 30, "exactCorrect": 250, "passAvailable": 0,
              "passCorrect": 0, "passAvailableExactCorrect": 0, "recall": .7,
              "exactPositiveRecall": .6, "precision": .7, "falsePositiveRate": .1,
              "positivePredictedOtherTypes": {"discard": 28, "kita": 2}, "typeCorrectParameterMismatch": 10}
    kan = {"opportunityCount": 100, "actualPositive": 10, "predictedPositive": 10,
           "truePositive": 6, "exactCorrectPositive": 5, "falsePositive": 4,
           "falseNegative": 4, "exactCorrect": 80, "passAvailable": 100,
           "passCorrect": 90, "passAvailableExactCorrect": 80, "recall": .6,
           "precision": .6, "passAvailableExactCandidateTop1": .8, "alwaysPassTop1": .9}
    return {"validationIdentity": identity, "metrics": {
        "samples": 1100, "choices": 1000, "forced": 100, "choiceNll": nll, "choiceTop1": .745,
        "byAction": {"discard": {"count": 800, "correct": 600}},
        "byOpportunity": {"riichi": riichi, "daiminkan": kan}},
        "numerics": {"choiceWindows": 1000, "top1TieDisagreements": 0,
                     "maximumAbsoluteLogit": 10., "maximumLogitSpan": 5.},
        "diagnosticScope": "riichi and daiminkan opportunities",
        "diagnostics": {"byOpportunity": {"riichi": deepcopy(riichi), "daiminkan": deepcopy(kan)},
                        "riichiDiscardLogitMargin": {"recordedRiichiPair": {"mean": -.3, "count": 100},
                                                     "recordedDiscardPair": {"mean": -1.1, "count": 300}}}}


class RiichiResultTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        protected = {}
        for name in ("v1.npz", "parent.npz", "resume.pt"):
            path = self.folder / name
            path.write_bytes(name.encode())
            protected[str(path)] = result_module.sha(path)
        rule = {"metric": "choiceNll", "direction": "lower", "minimumSupport": 100,
                "against": ["v1", "parent", "control"], "tolerance": .005}
        self.plan = {"purpose": "riichi-screening-only", "epochs": 3, "primaryEpoch": 3,
            "testSampleReadsAllowed": 0, "deploymentAllowed": False, "fullRetrainingAutomatic": False,
            "output": str(self.folder), "protectedSha256": protected, "v1Model": str(self.folder / "v1.npz"),
            "parentModel": str(self.folder / "parent.npz"), "parentResume": str(self.folder / "resume.pt"),
            "device": "cpu", "threads": 2, "trainGames": 2, "monitorGames": 1, "validationGames": 3,
            "partitionIdentities": {"train": "train", "monitor": "monitor", "validation": "validation"},
            "learningRate": .0001, "arms": {"control": {"opportunityWeights": {"daiminkan": 4}},
                                            "riichi2": {"opportunityWeights": {"daiminkan": 4, "riichi": 2}}},
            "scope": "synthetic test only", "screeningPolicy": {"guards": [rule], "improvementMode": "all",
                "improvements": [{"metric": "byOpportunity.riichi.recall", "direction": "higher",
                    "minimumSupport": 50, "against": ["control"], "minimumDelta": 0}]},
            "convergenceRules": {"naturalLossPlateauAbsoluteDelta": .001, "requiredConsecutiveIntervals": 2,
                "riichiRecallMaxPlateauSwing": .003, "kanPositiveMinimumSupport": 100,
                "interpretation": "Within-budget plateau does not establish global convergence."}}
        self.plan_path = self.folder / "plan.json"
        self.plan_path.write_text(json.dumps(self.plan))
        self.phases = {}
        for name in ("v1", "parent", "control", "riichi2"):
            trained = name in self.plan["arms"]
            model_path = self.plan["v1Model"] if name == "v1" else self.plan["parentModel"]
            phase = {"phase": name, "status": "complete", "planSha256": result_module.sha(self.plan_path),
                "device": "cpu", "threads": 2, "initialModelSha256": protected[model_path],
                "testSampleOrCacheReads": 0, "appWrites": 0, "cacheWrites": 0,
                "validationIdentity": "validation", "uniqueGamesRead": 5 if trained else 4,
                "history": [], "validation": evaluation("validation"), "trainMonitor": evaluation("monitor"),
                "elapsedSeconds": 1., "cacheHashesSha256": "same-cache"}
            if trained:
                phase["initialization"] = {"modelOptimizerAndRngFromSameParent": True,
                    "parentResumeSha256": protected[self.plan["parentResume"]],
                    "opportunityWeights": self.plan["arms"][name]["opportunityWeights"], "actionWeights": {}}
                for epoch in (1, 2, 3):
                    checkpoint = self.folder / f"{name}.epoch-{epoch}.npz"
                    checkpoint.write_bytes(f"{name}-{epoch}".encode())
                    phase["history"].append({"epoch": epoch, "learningRate": .0001,
                        "trainChoices": 1000, "optimizerSteps": 2, "orderSha256": f"order-{epoch}",
                        "checkpoint": str(checkpoint), "checkpointSha256": result_module.sha(checkpoint),
                        "weightedTrainLoss": .6, "maximumPreclipGradientNorm": .5,
                        "validation": evaluation("validation", .5 - epoch * .0001),
                        "trainMonitor": evaluation("monitor", .5 - epoch * .0001)})
                phase.update({key: deepcopy(phase["history"][-1][key]) for key in ("validation", "trainMonitor")})
                phase["exportParity"] = {"samples": 32, "argmaxAgreement": True, "maxAbsError": 0.}
                phase["opportunityWeightAudit"] = {"windows": 1000, "riichiOffered": 200,
                    "weightChanged": 100, "unchangedRiichiAlreadyWeighted": 100,
                    "changedByRecordedType": {"discard": 50, "riichi": 50}}
            self.phases[name] = phase
        self.write_phases()

    def write_phases(self):
        for name, phase in self.phases.items():
            (self.folder / (name + ".json")).write_text(json.dumps(phase))

    def assemble(self):
        self.write_phases()
        return result_module.assemble(self.plan_path)

    def test_complete_report_retains_all_epochs_without_deployment(self):
        report = self.assemble()
        self.assertEqual(report["screening"]["status"], "passed_screening")
        self.assertFalse(report["deploymentAllowed"])
        self.assertIn("counterfactual", report["opportunityWeightAuditScope"])
        self.assertEqual([entry["epoch"] for entry in report["models"]["riichi2"]["history"]], [1, 2, 3])
        self.assertFalse(report["convergence"]["control"]["globalConvergenceEstablished"])
        text = result_module.markdown(report)
        self.assertIn("riichi2 / 3", text)
        self.assertIn("没有事后选择最优轮次", text)
        self.assertIn("| v1 | 100 | 28 | kita: 2 | 10 | 60 |", text)
        self.assertIn("-0.300000 / 100", text)
        self.assertIn("这不是和牌率或胜率", text)
        self.assertIn("只有 10 / 10 / 10 / 10 个大明杠正例", text)
        self.assertIn("| 保护 | `choiceNll` | v1/parent/control | ≤ 参照值 + 0.005 | 100 |", text)
        self.assertEqual(text.count("| 保护 | `choiceNll`"), 1)
        self.assertIn("验证集已在此前研究中被反复查看", text)
        self.assertIn("窗口不是相互独立的样本", text)
        self.assertIn("v1 在 400 个固定公开立直机会窗口中预测立直 100 次（25.000%）", text)
        self.assertIn("牌谱真实立直 100 次（25.000%）", text)
        self.assertIn("不是连续实战立直率", text)
        self.assertIn("同时约束漏选与误选", text)
        self.assertIn("并不表示对照组实际加权", text)

    def test_incomplete_phase_prevents_any_assembly(self):
        self.phases["riichi2"]["status"] = "running"
        with self.assertRaisesRegex(ValueError, "complete"):
            self.assemble()

    def test_source_plan_sha_must_match_every_phase(self):
        self.phases["control"]["planSha256"] = "wrong-plan"
        with self.assertRaisesRegex(ValueError, "source plan"):
            self.assemble()

    def test_protected_model_change_is_rejected(self):
        Path(self.plan["v1Model"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Protected input changed"):
            self.assemble()

    def test_checkpoint_change_is_rejected(self):
        Path(self.phases["control"]["history"][1]["checkpoint"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "checkpoint changed"):
            self.assemble()

    def test_order_mismatch_is_rejected(self):
        self.phases["riichi2"]["history"][1]["orderSha256"] = "different-order"
        with self.assertRaisesRegex(ValueError, "Arm order"):
            self.assemble()

    def test_choice_count_mismatch_is_rejected(self):
        self.phases["riichi2"]["history"][1]["trainChoices"] += 1
        with self.assertRaisesRegex(ValueError, "Arm order"):
            self.assemble()

    def test_earlier_best_epoch_cannot_replace_terminal_result(self):
        self.phases["riichi2"]["history"][0]["validation"]["metrics"]["choiceNll"] = .1
        report = self.assemble()
        self.assertAlmostEqual(report["models"]["riichi2"]["validation"]["metrics"]["choiceNll"], .4997)
        self.phases["riichi2"]["validation"] = deepcopy(self.phases["riichi2"]["history"][0]["validation"])
        with self.assertRaisesRegex(ValueError, "not terminal"):
            self.assemble()

    def test_low_kan_support_does_not_become_convergence(self):
        report = self.assemble()
        monitor = report["convergence"]["riichi2"]["partitions"]["trainMonitor"]
        self.assertEqual(monitor["status"], "plateau_within_budget")
        self.assertEqual(monitor["daiminkan"]["status"], "insufficient_evidence")

    def test_weighted_online_loss_does_not_determine_plateau(self):
        self.phases["riichi2"]["history"][1]["weightedTrainLoss"] = 1000.
        report = self.assemble()
        self.assertEqual(report["convergence"]["riichi2"]["partitions"]["validation"]["status"], "plateau_within_budget")
        self.assertFalse(report["convergence"]["riichi2"]["weightedOnlineLossComparableToNaturalLoss"])

    def test_recall_swing_applies_to_entire_plateau_window(self):
        history = deepcopy(self.phases["riichi2"]["history"])
        for entry, recall in zip(history, (.7, .702, .704)):
            entry["validation"]["metrics"]["byOpportunity"]["riichi"]["recall"] = recall
        evidence = result_module.convergence(self.phases["parent"], history, self.plan["convergenceRules"])
        self.assertEqual(evidence["partitions"]["validation"]["status"], "not_plateau")
        self.assertAlmostEqual(evidence["partitions"]["validation"]["riichiRecallPlateauWindowSwing"], .004)

    def test_monitor_subset_counts_must_stay_stationary(self):
        self.phases["riichi2"]["history"][0]["trainMonitor"]["metrics"]["byAction"]["discard"]["count"] += 1
        with self.assertRaisesRegex(ValueError, "coverage differs"):
            self.assemble()

    def test_app_write_or_test_read_prevents_assembly(self):
        for key in ("appWrites", "testSampleOrCacheReads"):
            self.phases["v1"][key] = 1
            with self.assertRaisesRegex(ValueError, "forbidden"):
                self.assemble()
            self.phases["v1"][key] = 0

    def test_numeric_tie_disagreement_prevents_assembly(self):
        self.phases["parent"]["trainMonitor"]["numerics"]["top1TieDisagreements"] = 1
        with self.assertRaisesRegex(ValueError, "tie disagreement"):
            self.assemble()

    def test_optional_audit_hashes_and_cpu_difference_are_reported(self):
        report = self.assemble()
        data = {"sources": {str(self.plan_path): result_module.sha(self.plan_path),
                            str(self.folder / "v1.json"): result_module.sha(self.folder / "v1.json")},
                "differingIntegerCounts": [{"path": "byAction.discard.correct", "difference": 1}],
                "globalMetrics": {"choiceNll": {"difference": 7.3e-9}}}
        audit_path = self.folder / "v1-cpu-equivalence.json"
        audit_path.write_text(json.dumps(data))
        for name in ("riichi-objective-audit.json", "daiminkan-path-audit.json", "control-completion-audit.json"):
            (self.folder / name).write_text(json.dumps({"status": "read-only-audit-complete"}))
        audits = result_module._external_audits(self.folder, self.plan_path, result_module.sha(self.plan_path),
                                               self.folder / "v1.json")
        self.assertEqual(list(audits), ["v1-cpu-equivalence.json", "riichi-objective-audit.json",
                                      "daiminkan-path-audit.json", "control-completion-audit.json"])
        self.assertEqual(audits["v1-cpu-equivalence.json"]["sha256"], result_module.sha(audit_path))
        report["provenance"]["externalAudits"] = audits
        text = result_module.markdown(report)
        self.assertIn("普通出牌完整动作正确数变化 +1", text)
        self.assertIn("并非计数完全相同", text)
        self.assertIn("+7.300e-09", text)
        self.assertIn(result_module.sha(audit_path), text)
        self.assertIn(result_module.sha(self.folder / "riichi-objective-audit.json"), text)
        self.assertIn("[daiminkan-path-audit.json]", text)

    def test_unbound_cpu_audit_does_not_supply_comparison_claims(self):
        report = self.assemble()
        (self.folder / "v1-cpu-equivalence.json").write_text(json.dumps({"sources": {}}))
        report["provenance"]["externalAudits"] = result_module._external_audits(
            self.folder, self.plan_path, result_module.sha(self.plan_path), self.folder / "v1.json")
        self.assertNotIn("CPU 重算的 v1", result_module.markdown(report))

    def test_preexisting_parent_regression_is_not_attributed_to_treatment(self):
        report = self.assemble()
        for name, correct in (("v1", 900), ("parent", 838)):
            report["models"][name]["validation"]["metrics"]["byAction"]["shouminkan"] = {"count": 1000, "correct": correct}
        text = result_module.markdown(report)
        self.assertIn("shouminkan -6.200 个百分点", text)
        self.assertIn("不能自动归因于立直加权", text)
        self.assertIn("实验组与匹配对照组的差值", text)


if __name__ == "__main__":
    unittest.main()
