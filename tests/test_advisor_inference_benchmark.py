"""Baseline reuse exercises the benchmark entry point without running inference."""
from copy import deepcopy
import hashlib
import importlib.metadata
import importlib.util
import io
from pathlib import Path
import platform
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("advisor_compare", ROOT / "scripts/advisor_compare.py")
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)
spec = importlib.util.spec_from_file_location(
    "advisor_inference_benchmark", ROOT / "scripts/advisor_inference_benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class BaselineCopied(Exception):
    """Stop after the real reuse path copies a baseline measurement."""


class InferenceBenchmarkReuseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.reuse = self.directory / "previous"
        self.reuse.mkdir()
        cases = [case for name in benchmark.FIXTURES
                 for case in comparison.load_cases(ROOT / "tests/fixtures" / name)]
        benchmark.save(self.reuse / "fixtures.json", {"schemaVersion": 1, "cases": cases})
        source = self.directory / "source"
        source.mkdir()
        (source / "advisor.py").write_text("SEARCH_SECONDS = 2.0\n")
        self.source_info = {"sourceSha256": comparison.source_hash(source)}
        self.previous = {
            "sources": {"baseline": self.source_info},
            "fixtures": [{"sha256": hashlib.sha256((self.reuse / "fixtures.json").read_bytes()).hexdigest()}],
            "environment": {"python": sys.version, "platform": platform.platform(),
                            "mahjong": importlib.metadata.version("mahjong")},
            "method": {"budgetSeconds": 2, "rankedLimitBothVersions": 3,
                       "warmupPasses": 1, "measuredPasses": 3},
            "runnerSha256": {name: hashlib.sha256((ROOT / "scripts" / name).read_bytes()).hexdigest()
                             for name in ("advisor_compare.py", "advisor_inference_benchmark.py")},
        }
        self.baseline_name = f"cold-{benchmark.COLD_IDS[0]}-1-baseline.json"
        benchmark.save(self.reuse / self.baseline_name, {"measurement": "synthetic baseline"})

    def run_reuse(self, previous, output, accepted):
        benchmark.save(self.reuse / "summary.json", previous)

        def snapshot(repo, destination, ref):
            source = destination / "src"
            source.mkdir()
            (source / "advisor.py").write_text("SEARCH_SECONDS = 2.0\n")
            return source, self.source_info

        def measure(source, *args, **kwargs):
            self.assertEqual(source.parent.name, "current", "baseline must be reused, not measured")
            if (output / self.baseline_name).exists():
                raise BaselineCopied
            return {}

        arguments = [str(ROOT / "scripts/advisor_inference_benchmark.py"),
                     "--repo", str(ROOT), "--baseline", "HEAD",
                     "--baseline-results", str(self.reuse), "--artifacts", str(output)]
        with patch.object(sys, "argv", arguments), patch.object(sys, "path", sys.path[:]), \
                patch.object(sys, "stdout", io.StringIO()), \
                patch.dict(sys.modules, {"advisor_compare": comparison}), \
                patch.object(comparison, "snapshot_source", side_effect=snapshot), \
                patch.object(comparison, "run_version", side_effect=measure) as run_version:
            if accepted:
                with self.assertRaises(BaselineCopied):
                    benchmark.main()
                self.assertEqual((output / self.baseline_name).read_bytes(),
                                 (self.reuse / self.baseline_name).read_bytes())
            else:
                with self.assertRaisesRegex(ValueError, "runner"):
                    benchmark.main()
                run_version.assert_not_called()
                self.assertFalse((output / self.baseline_name).exists())

    def test_matching_runners_reuse_the_baseline_measurement(self):
        self.run_reuse(self.previous, self.directory / "matching", accepted=True)

    def test_each_changed_runner_is_rejected_before_measurement_or_reuse(self):
        for name in self.previous["runnerSha256"]:
            with self.subTest(runner=name):
                previous = deepcopy(self.previous)
                previous["runnerSha256"][name] = "0" * 64
                self.run_reuse(previous, self.directory / name, accepted=False)

    def test_missing_runner_metadata_is_rejected_before_measurement_or_reuse(self):
        for name in (None, *self.previous["runnerSha256"]):
            with self.subTest(runner=name):
                previous = deepcopy(self.previous)
                if name is None:
                    del previous["runnerSha256"]
                else:
                    del previous["runnerSha256"][name]
                self.run_reuse(previous, self.directory / str(name), accepted=False)


if __name__ == "__main__":
    unittest.main()
