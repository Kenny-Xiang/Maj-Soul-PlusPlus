"""Packaged policy acceptance uses real weights and predecoded visible fixtures."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_policy_model import torch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/policy_verify_windows.json"


@unittest.skipIf(torch is None, "requires training dependencies to create test weights")
class PolicyVerifyTests(unittest.TestCase):
    def setUp(self):
        from policy_bundle import BUNDLE_FORMAT, MODEL_NAMES
        from policy_training import CandidatePolicy, export_model
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "src"
        folder = self.root / "policy-models"
        folder.mkdir(parents=True)
        manifest = {"format": BUNDLE_FORMAT, "models": {}}
        for players, name in MODEL_NAMES.items():
            torch.manual_seed(players)
            path = folder / name
            export_model(CandidatePolicy({"channels": 4, "blocks": 1, "hidden": 8}), path,
                         {"playerCount": players, "purpose": "behavior-cloning"})
            manifest["models"][str(players)] = {"file": name, "playerCount": players,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        (folder / "manifest.json").write_text(json.dumps(manifest))
        self.manifest = manifest

    def test_bundled_models_ignore_environment_and_cover_all_windows(self):
        from policy_verify import verify_policy
        with patch.dict(os.environ, {"MAJSOUL_POLICY_MODEL_3P": "/missing-override.npz"}):
            result = verify_policy(self.root, FIXTURE)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["windows"], 56)
        self.assertEqual(len(result["actionTypes"]), 12)
        self.assertEqual(result["models"]["3"]["readyWindows"], 18)
        self.assertEqual(result["models"]["4"]["readyWindows"], 16)
        for players in ("3", "4"):
            self.assertEqual(result["models"][players]["sha256"], self.manifest["models"][players]["sha256"])
            self.assertGreater(result["models"][players]["waitingWindows"], 0)

    def test_missing_bundle_and_corrupt_weights_fail(self):
        from policy_verify import verify_policy
        with self.assertRaisesRegex(ValueError, "both bundled"):
            verify_policy(self.root / "missing", FIXTURE)
        path = self.root / "policy-models/three-player.npz"
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            verify_policy(self.root, FIXTURE)

    def test_invalid_probabilities_missing_candidates_wrong_slot_and_closed_advice_fail(self):
        from policy_model import PolicyAdvisor
        from policy_verify import verify_policy
        original = PolicyAdvisor.__call__
        for kind in ("probability", "candidate", "slot", "closed"):
            def changed(advisor, state):
                result = original(advisor, state)
                if state["canAct"]:
                    if kind == "probability":
                        result["candidates"][0]["policyProbability"] = float("nan")
                    elif kind == "candidate":
                        result["candidates"].pop()
                    elif kind == "slot":
                        result["modelSha256"] = advisor.models[7 - state["playerCount"]].sha256
                elif kind == "closed":
                    result["status"] = "ready"
                return result
            with self.subTest(kind=kind), patch.object(PolicyAdvisor, "__call__", changed):
                with self.assertRaises(ValueError):
                    verify_policy(self.root, FIXTURE)

    def test_cli_runs_without_torch_node_gui_or_profile_access(self):
        shutil.copyfile(ROOT / "src/monitor.py", self.root / "monitor.py")
        fixture = self.root.parent / "tests/fixtures/policy_verify_windows.json"
        fixture.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURE, fixture)
        program = """
import json, runpy, sys
def guard(event, args):
    if event == 'import' and args[0].split('.')[0] in ('torch', 'AppKit', 'WebKit', 'Foundation'):
        raise AssertionError('unexpected runtime dependency: ' + args[0])
    if event == 'subprocess.Popen' or event.startswith('socket.'):
        raise AssertionError('unexpected network or child process')
    if event == 'open' and isinstance(args[0], str) and 'Application Support/Maj-Soul++' in args[0]:
        raise AssertionError('unexpected game profile access')
sys.addaudithook(guard)
sys.argv = [sys.argv[1], '--verify-policy']
runpy.run_path(sys.argv[0], run_name='__main__')
"""
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src"),
                       "MAJSOUL_POLICY_MODEL_3P": "/must-ignore-this.npz"}
        result = subprocess.run([sys.executable, "-c", program, str(self.root / "monitor.py")],
                                capture_output=True, text=True, env=environment, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["status"], "ok")
        (self.root / "policy-models/three-player.npz").unlink()
        failed = subprocess.run([sys.executable, "-c", program, str(self.root / "monitor.py")],
                                capture_output=True, text=True, env=environment, timeout=30)
        self.assertEqual(failed.returncode, 1)
        self.assertEqual(json.loads(failed.stdout)["status"], "error")

    def test_frozen_entry_reads_fixture_from_packaged_source_directory(self):
        shutil.copyfile(ROOT / "src/monitor.py", self.root / "monitor.py")
        fixture = self.root / "source/tests/fixtures/policy_verify_windows.json"
        fixture.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURE, fixture)
        program = """
import runpy, sys
sys.frozen = True
sys.argv = [sys.argv[1], '--verify-policy']
runpy.run_path(sys.argv[0], run_name='__main__')
"""
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        result = subprocess.run([sys.executable, "-c", program, str(self.root / "monitor.py")],
                                capture_output=True, text=True, env=environment, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["fixtureSha256"], hashlib.sha256(FIXTURE.read_bytes()).hexdigest())


class PolicyFixtureTests(unittest.TestCase):
    def test_official_spec_collects_verification_fixture_at_runtime_path(self):
        from types import ModuleType
        hooks = ModuleType("PyInstaller.utils.hooks")
        hooks.copy_metadata = lambda name: []
        prelude = (ROOT / "Maj-Soul++.spec").read_text().split("\na = Analysis(", 1)[0]
        namespace = {"SPECPATH": str(ROOT)}
        with patch.dict(sys.modules, {"PyInstaller.utils.hooks": hooks}), patch.dict(os.environ, {}, clear=True):
            exec(compile(prelude, "Maj-Soul++.spec", "exec"), namespace)
        self.assertIn((str(FIXTURE), "source/tests/fixtures"), namespace["datas"])

    @unittest.skipIf(shutil.which("node") is None, "requires Node only to regenerate the source fixture")
    def test_fixture_matches_live_wire_decoder_visible_snapshots(self):
        from test_policy_live_windows import wire_cases
        fixture = json.loads(FIXTURE.read_text())
        run = subprocess.run([shutil.which("node"), str(ROOT / "tests/helpers/policy_live_windows.cjs")],
                             input=json.dumps(wire_cases()), capture_output=True, text=True, timeout=30, check=True)
        expected = [{"scenario": flow["name"], "state": turn["state"]}
                    for flow in json.loads(run.stdout) for turn in flow["turns"]]
        self.assertEqual(fixture["windows"], expected)
        for name, digest in fixture["sourceSha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest, name)


if __name__ == "__main__":
    unittest.main()
