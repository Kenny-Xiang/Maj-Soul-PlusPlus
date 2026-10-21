"""A fixed natural training monitor does not alter fitting or held-out selection."""
from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import torch
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "optional policy training dependencies are not installed")
class TrainMonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_selection_is_seeded_order_independent_and_not_an_old_prefix(self):
        from policy_corpus_training import select_train_monitor
        rows = [{"gameId": f"{generation}-{index}"} for generation in ("old", "new") for index in range(20)]
        original = list(rows)
        selected = select_train_monitor(rows, 42, 8)
        self.assertEqual(selected, select_train_monitor(list(reversed(rows)), 42, 8))
        self.assertNotEqual(selected, select_train_monitor(rows, 43, 8))
        self.assertNotEqual(selected, rows[:8])
        self.assertEqual({row["gameId"].split("-")[0] for row in selected}, {"old", "new"})
        self.assertEqual(rows, original)
        self.assertEqual(len(select_train_monitor(rows, 42, 100)), len(rows))
        self.assertEqual(select_train_monitor(rows, 42, None), [])

    def test_invalid_counts_reject_before_manifest_read(self):
        import policy_corpus_training as corpus
        with patch.object(corpus, "read_manifest") as reader:
            for count in (0, -1, 1.5, True, "4"):
                with self.subTest(count=count), self.assertRaisesRegex(ValueError, "train monitor games"):
                    corpus.train_corpus("unread", "unwritten", train_monitor_games=count)
            reader.assert_not_called()

    def test_monitor_preserves_training_validation_and_full_natural_metrics(self):
        import policy_corpus_training as corpus
        from test_policy_opportunity_metrics import OpportunityMetricTests
        fixture = OpportunityMetricTests()
        samples = [fixture.sample(["riichi", "discard"], 0, 0),
                   fixture.sample(["daiminkan", "pass", "pon"], 1, 1)]
        train_ids = ["old-0", "old-1", "new-0", "new-1"]
        groups = {"train": train_ids, "validation": ["validation"], "test": ["test"]}
        partitions = {name: [{"gameId": game, "samples": 2} for game in games] for name, games in groups.items()}
        audit = {"actions": {"riichi": 1, "pass": 1}, "labelSources": {"accepted": 2}, "duplicateSamples": 0}
        runs = []
        original_evaluate = corpus.evaluate_corpus
        with tempfile.TemporaryDirectory() as folder:
            for count in (None, 3):
                reads, evaluations = [], []

                def load(row, *args):
                    self.assertNotEqual(row["gameId"], "test")
                    reads.append(row["gameId"])
                    return samples, audit

                def evaluate(model, rows, *args, **kwargs):
                    result = original_evaluate(model, rows, *args, **kwargs)
                    evaluations.append((kwargs.get("phase"), [row["gameId"] for row in rows], result[0]))
                    return result

                output = Path(folder) / f"monitor-{count}.npz"
                options = {"epochs": 2, "validation_only": True, "batch_size": 3, "game_window": 2,
                           "config": {"channels": 4, "blocks": 1, "hidden": 8},
                           "opportunity_weights": {"daiminkan": 4.},
                           "action_boundary_weights": {"riichi": 1.}, "train_monitor_games": count}
                with patch.object(corpus, "read_manifest", return_value=(partitions, groups, {})), \
                        patch.object(corpus, "load_game", side_effect=load), \
                        patch.object(corpus, "evaluate_corpus", side_effect=evaluate), redirect_stdout(io.StringIO()):
                    model, report = corpus.train_corpus("unused", output, **options)
                    saved = torch.load(output.with_suffix(".resume.pt"), weights_only=True)
                    self.assertEqual(saved["binding"]["trainMonitor"], report["trainMonitor"])
                    if count is not None:
                        with self.assertRaisesRegex(ValueError, "differs in source"):
                            corpus.train_corpus("unused", output, resume=True,
                                                **{**options, "train_monitor_games": 2})
                runs.append((model.state_dict(), report, reads, evaluations))

        baseline, monitored = runs
        self.assertIsNone(baseline[1]["trainMonitor"])
        self.assertFalse(any("trainMonitor" in row for row in baseline[1]["history"]))
        self.assertFalse(any("train-monitor" in phase for phase, _, _ in baseline[3]))
        self.assertEqual(len(monitored[2]) - len(baseline[2]), 2 * 3)
        for key in baseline[0]:
            torch.testing.assert_close(baseline[0][key], monitored[0][key], rtol=0, atol=0)
        self.assertEqual(baseline[1]["bestEpoch"], monitored[1]["bestEpoch"])
        for a, b in zip(baseline[1]["history"], monitored[1]["history"]):
            self.assertEqual(a, {key: value for key, value in b.items() if key != "trainMonitor"})
        metadata = monitored[1]["trainMonitor"]
        self.assertEqual(metadata["requestedGames"], 3)
        self.assertEqual(metadata["games"], 3)
        self.assertTrue(set(metadata["gameIds"]) <= set(train_ids))
        self.assertIn("not independent held-out", metadata["scope"])
        self.assertEqual(len(metadata["identitySha256"]), 64)
        monitor_evaluations = [item for item in monitored[3] if "train-monitor" in item[0]]
        for history, (_, ids, natural_metrics) in zip(monitored[1]["history"], monitor_evaluations):
            self.assertEqual(ids, metadata["gameIds"])
            self.assertEqual(history["trainMonitor"], natural_metrics)
            self.assertIn("byOpportunity", natural_metrics)
            self.assertIn("byAction", natural_metrics)

    def test_cli_passes_monitor_count_and_default(self):
        import policy_corpus_training as corpus
        script = Path(__file__).resolve().parents[1] / "scripts" / "policy_train_corpus.py"
        spec = importlib.util.spec_from_file_location("monitor_cli", script)
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        report = {"purpose": "fixture", "dataAudit": {"selectedGames": 0, "selectedGameCounts": {}}}
        for count in (None, 4096):
            argv = [str(script), "--manifest", "unused", "--players", "3", "--output", "unused.npz"]
            if count is not None:
                argv += ["--train-monitor-games", str(count)]
            with patch("sys.argv", argv), patch.object(corpus, "train_corpus", return_value=(None, report)) as train, \
                    redirect_stdout(io.StringIO()):
                cli.main()
            self.assertEqual(train.call_args.kwargs["train_monitor_games"], count)


if __name__ == "__main__":
    unittest.main()
