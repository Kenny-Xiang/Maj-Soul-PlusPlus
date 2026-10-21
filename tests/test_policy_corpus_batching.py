"""Cross-game evaluation batches remain bounded and preserve decision metrics."""
from collections import Counter
from contextlib import redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

try:
    import torch
except ImportError:
    torch = None

@unittest.skipIf(torch is None, "optional policy training dependencies are not installed")
class CorpusEvaluationBatchTests(unittest.TestCase):
    def test_cross_game_batches_preserve_metrics_audit_and_completed_log_boundaries(self):
        import policy_corpus_training as corpus
        from policy_training import CandidatePolicy
        from test_policy_opportunity_metrics import OpportunityMetricTests
        torch.set_num_threads(1)
        torch.manual_seed(3)
        model = CandidatePolicy({"channels": 4, "blocks": 1, "hidden": 8})
        templates = OpportunityMetricTests().samples()
        rows = list(range(101))

        def load_game(row, players, encoded_cache):
            self.assertEqual((players, encoded_cache), (4, "cache-path"))
            samples = [{**sample, "game": row} for sample in templates[:row % len(templates) + 1]]
            return samples, {"actions": dict(Counter(s["action"] for s in samples)),
                             "labelSources": {"accepted": len(samples)}, "duplicateSamples": row % 3}

        results, logs, group_sizes = [], [], []
        for game_window in (1, 16):
            sizes = []
            actual_evaluate = corpus.evaluate

            def evaluate(model, samples, device, batch_size):
                sizes.append(len({sample["game"] for sample in samples}))
                self.assertLessEqual(sizes[-1], game_window)
                return actual_evaluate(model, samples, device, batch_size)

            output = io.StringIO()
            with patch.object(corpus, "load_game", side_effect=load_game), \
                    patch.object(corpus, "evaluate", side_effect=evaluate), redirect_stdout(output):
                results.append(corpus.evaluate_corpus(model, rows, 4, "cpu", 32,
                                                       phase="validation", encoded_cache="cache-path",
                                                       game_window=game_window))
            logs.append([json.loads(line) for line in output.getvalue().splitlines()])
            group_sizes.append(sizes)

        first, grouped = results
        self.assertEqual(first[1], grouped[1])
        for name in first[0]:
            if name == "choiceNll":
                self.assertAlmostEqual(first[0][name], grouped[0][name], places=6)
            else:
                self.assertEqual(first[0][name], grouped[0][name], name)
        self.assertEqual(first[1]["games"], 101)
        self.assertEqual(first[1]["duplicateSamples"], sum(row % 3 for row in rows))
        self.assertEqual(logs[0], [{"phase": "validation", "completedGames": 100, "totalGames": 101}])
        self.assertEqual(logs[0], logs[1])
        self.assertEqual(group_sizes[0], [1] * 101)
        self.assertEqual(group_sizes[1], [16] * 6 + [4, 1])

    def test_empty_corpus_and_invalid_game_window(self):
        from policy_corpus_training import evaluate_corpus
        metrics, audit = evaluate_corpus(None, [], 4, "cpu", 32)
        self.assertEqual(metrics["samples"], 0)
        self.assertEqual(audit["games"], 0)
        for invalid in (0, -1, 1.5, True):
            with self.assertRaisesRegex(ValueError, "game_window"):
                evaluate_corpus(None, [], 4, "cpu", 32, game_window=invalid)


if __name__ == "__main__":
    unittest.main()
