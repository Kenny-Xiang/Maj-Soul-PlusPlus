"""Source launcher validates the exact model slots before any GUI starts."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("policy_launch", ROOT / "scripts/policy_launch.py")
launch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launch)


class Model:
    def __init__(self, path):
        self.sha256 = "fixture-model-sha"
        self.metadata = {"format": "fixture", "playerCount": 3 if path.name == "three.npz" else 4,
                         "purpose": "behavior-cloning", "featureSignature": "fixture-signature", "actionVersion": 1}


class PolicyLaunchTests(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        self.patches = [patch.dict(sys.modules, {"policy_model": SimpleNamespace(PolicyModel=Model)}),
                        patch.object(launch.importlib.util, "find_spec", return_value=object()),
                        patch.object(launch, "existing_instance_running", return_value=False),
                        patch.object(launch.sys, "platform", "darwin")]
        for mocked in self.patches:
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_explicit_slots_replace_inherited_slots_and_preserve_other_environment(self):
        report, environment = launch.prepare({3: Path("three.npz")}, {
            "EXISTING": "preserved", "MAJSOUL_POLICY_MODEL_4P": "old.npz"})
        self.assertEqual(report["models"][0]["playerCount"], 3)
        self.assertEqual(report["models"][0]["sha256"], "fixture-model-sha")
        self.assertEqual(environment, {"EXISTING": "preserved",
                                      "MAJSOUL_POLICY_MODEL_3P": str(Path("three.npz").resolve())})

    def test_wrong_player_count_and_no_models_reject(self):
        with self.assertRaisesRegex(ValueError, "slot"):
            launch.prepare({4: Path("three.npz")})
        with self.assertRaisesRegex(ValueError, "provide"):
            launch.prepare({})

    def test_missing_dependencies_and_wrong_platform_reject(self):
        with patch.object(launch.importlib.util, "find_spec", return_value=None):
            with self.assertRaisesRegex(ValueError, "missing source-app dependencies"):
                launch.prepare({4: Path("four.npz")})
        with patch.object(launch.sys, "platform", "linux"):
            with self.assertRaisesRegex(ValueError, "requires macOS"):
                launch.prepare({4: Path("four.npz")})

    def test_check_prints_metadata_without_starting_gui(self):
        with patch.object(launch.os, "execve") as execute, patch("builtins.print") as output:
            launch.main(["--four-player", "four.npz", "--check"])
            execute.assert_not_called()
            self.assertIn("fixture-model-sha", output.call_args.args[0])

    def test_launch_uses_current_python_and_exact_configured_slots(self):
        with patch.object(launch.os, "execve") as execute, patch("builtins.print"):
            launch.main(["--four-player", "four.npz", "--three-player", "three.npz"])
            binary, arguments, environment = execute.call_args.args
            self.assertEqual(binary, sys.executable)
            self.assertEqual(arguments, [sys.executable, str(ROOT / "src/monitor.py")])
            self.assertEqual(environment["MAJSOUL_POLICY_MODEL_4P"], str(Path("four.npz").resolve()))
            self.assertEqual(environment["MAJSOUL_POLICY_MODEL_3P"], str(Path("three.npz").resolve()))

    def test_running_application_is_reported_and_not_reused_for_new_models(self):
        with patch.object(launch, "existing_instance_running", return_value=True), \
                patch.object(launch.os, "execve") as execute, patch("builtins.print") as output:
            launch.main(["--four-player", "four.npz", "--check"])
            self.assertIn('"existingInstanceRunning": true', output.call_args.args[0])
            with self.assertRaises(SystemExit), patch.object(launch.sys, "stderr"):
                launch.main(["--four-player", "four.npz"])
            execute.assert_not_called()


class ExistingInstanceTests(unittest.TestCase):
    def test_lock_probe_is_read_only_and_distinguishes_held_lock(self):
        import fcntl
        import monitor
        with tempfile.TemporaryDirectory() as folder, patch.object(monitor, "DATA", Path(folder)):
            path = Path(folder) / "monitor.lock"
            self.assertFalse(launch.existing_instance_running())
            self.assertFalse(path.exists())
            path.write_text("fixture-owner")
            self.assertFalse(launch.existing_instance_running())
            with path.open("rb") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertTrue(launch.existing_instance_running())
            self.assertEqual(path.read_text(), "fixture-owner")


if __name__ == "__main__":
    unittest.main()
