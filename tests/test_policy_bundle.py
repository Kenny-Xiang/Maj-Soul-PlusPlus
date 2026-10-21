"""The installed app loads exact bundled slots and refuses incomplete training."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from test_policy_model import visible_state

try:
    import torch
except ImportError:
    torch = None

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("policy_prepare_bundle", ROOT / "scripts/policy_prepare_bundle.py")
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


@unittest.skipIf(torch is None, "install requirements-training.txt for bundle tests")
class PolicyBundleTests(unittest.TestCase):
    def setUp(self):
        from policy_training import CandidatePolicy
        torch.set_num_threads(1)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.network = CandidatePolicy({"channels": 4, "blocks": 1, "hidden": 8}).eval()
        self.models = {players: self.root / f"source-{players}.npz" for players in (3, 4)}
        ids = [f"fixture-game-{i}" for i in range(40000)]
        self.report = {
            "purpose": "behavior-cloning", "playerCount": 3,
            "gameSplit": {"train": ids[:32000], "validation": ids[32000:36000], "test": ids[36000:]},
            "dataAudit": {"selectedGames": 40000, "manifestGames": 40000, "maxGames": None,
                          "manifestSha256": "a" * 64,
                          "selectedGameCounts": {"train": 32000, "validation": 4000, "test": 4000},
                          "frozenSplit": {"unit": "whole-game-all-seats", "sha256": "b" * 64}},
            "metrics": {name: {"choices": 1, "choiceNll": 1.} for name in ("train", "validation", "test")}}
        for players in (3, 4):
            self.export(players)
        self.folder = self.root / "resources/policy-models"

    def export(self, players, report=None, purpose="behavior-cloning"):
        from policy_training import export_model
        data = deepcopy(self.report if report is None else report)
        data["playerCount"] = players
        path = self.models[players]
        export_model(self.network, path, {"playerCount": players, "purpose": purpose, "training": data})
        data.update(modelSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    exportParity={"samples": 32, "argmaxAgreement": True, "maxAbsError": 0.})
        path.with_suffix(".report.json").write_text(json.dumps(data))

    def worker(self, environ=None):
        from monitor import create_advice_worker
        worker = create_advice_worker({} if environ is None else environ, self.folder.parent)
        self.addCleanup(worker.close)
        return worker

    def test_both_models_load_without_environment_and_route_exactly(self):
        manifest = bundle.prepare_bundle(self.models, self.folder)
        self.assertEqual(len(bundle.validate_bundle(self.folder)), 5)
        worker = self.worker()
        for players in (3, 4):
            result = worker.calculate(visible_state(players))
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["modelSha256"], manifest["models"][str(players)]["sha256"])

    def test_no_bundle_preserves_default_but_missing_manifest_does_not_fallback(self):
        self.assertTrue(self.worker().cooperative)
        self.folder.mkdir(parents=True)
        worker = self.worker()
        self.assertFalse(worker.cooperative)
        self.assertEqual(worker.calculate(visible_state())["status"], "unavailable")

    def test_missing_or_modified_model_is_explicitly_unavailable(self):
        bundle.prepare_bundle(self.models, self.folder)
        model = self.folder / "three-player.npz"
        model.write_bytes(model.read_bytes() + b"changed")
        result = self.worker().calculate(visible_state(3))
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("SHA256", result["message"])
        model.unlink()
        self.assertEqual(self.worker().calculate(visible_state(3))["status"], "unavailable")

    def test_malformed_manifest_is_explicitly_unavailable(self):
        self.folder.mkdir(parents=True)
        for data in ([], {"format": bundle.BUNDLE_FORMAT, "models": {"3": None, "4": None}}):
            (self.folder / "manifest.json").write_text(json.dumps(data))
            self.assertEqual(self.worker().calculate(visible_state(3))["status"], "unavailable")

    def test_explicit_override_replaces_one_slot_and_retains_other_bundle_slot(self):
        from policy_training import export_model
        manifest = bundle.prepare_bundle(self.models, self.folder)
        torch.manual_seed(33)
        for parameter in self.network.parameters():
            torch.nn.init.normal_(parameter, 0, .01)
        export_model(self.network, self.models[3], {"playerCount": 3, "purpose": "behavior-cloning"})
        worker = self.worker({"MAJSOUL_POLICY_MODEL_3P": str(self.models[3])})
        self.assertNotEqual(worker.calculate(visible_state(3))["modelSha256"], manifest["models"]["3"]["sha256"])
        self.assertEqual(worker.calculate(visible_state(4))["modelSha256"], manifest["models"]["4"]["sha256"])
        wrong = self.worker({"MAJSOUL_POLICY_MODEL_3P": str(self.models[4])})
        self.assertEqual(wrong.calculate(visible_state(3))["status"], "unavailable")

    def test_explicit_two_slots_can_replace_an_unusable_bundle(self):
        self.folder.mkdir(parents=True)
        worker = self.worker({f"MAJSOUL_POLICY_MODEL_{players}P": str(path)
                              for players, path in self.models.items()})
        self.assertEqual(worker.calculate(visible_state(3))["status"], "ready")

    def test_pilot_subset_unfrozen_checkpoint_and_smoke_are_not_full_bundles(self):
        mutations = [lambda report: report["dataAudit"].update(selectedGames=500),
                     lambda report: report["dataAudit"].update(maxGames=40000),
                     lambda report: report["dataAudit"].update(frozenSplit=None),
                     lambda report: report.pop("metrics"),
                     lambda report: report["gameSplit"]["test"].__setitem__(0, "fixture-game-0")]
        for mutate in mutations:
            report = deepcopy(self.report)
            mutate(report)
            self.export(3, report)
            with self.assertRaises(ValueError):
                bundle.prepare_bundle(self.models, self.folder)
        self.export(3, purpose="smoke")
        with self.assertRaises(ValueError):
            bundle.prepare_bundle(self.models, self.folder)
        self.assertFalse(self.folder.exists())

    def test_report_mismatch_and_changed_staging_block_build(self):
        report_path = self.models[3].with_suffix(".report.json")
        report = json.loads(report_path.read_text())
        report["dataAudit"]["selectedGames"] = 50000
        report_path.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, "matching completed"):
            bundle.prepare_bundle(self.models, self.folder)
        self.export(3)
        bundle.prepare_bundle(self.models, self.folder)
        report_path = self.folder / "three-player.report.json"
        report_path.write_text(report_path.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "differs from its manifest"):
            bundle.validate_bundle(self.folder)


if __name__ == "__main__":
    unittest.main()
