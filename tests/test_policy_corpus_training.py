"""Streaming corpus training, provenance and split regressions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import numpy as np
    import torch
    import zstandard
except ImportError:
    np = torch = zstandard = None

from test_policy_model import visible_state


@unittest.skipIf(torch is None, "optional policy training and zstandard dependencies are not installed")
class CorpusTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def write_game(self, identifier, count, compressed=True):
        from policy_actions import legal_actions
        from policy_features import RULESET
        rows = []
        for index in range(count):
            state = visible_state()
            state["left"] -= index
            actions = legal_actions(state)
            rows.append({"schemaVersion": 1, "ruleset": RULESET, "gameId": identifier,
                         "roundId": "0", "decisionId": f"0:{index}", "seat": 0,
                         "state": state, "action": actions[index % len(actions)], "labelSource": "accepted"})
        data = "".join(json.dumps(row) + "\n" for row in rows).encode()
        name = identifier + (".jsonl.zst" if compressed else ".jsonl")
        if compressed:
            data = zstandard.ZstdCompressor().compress(data)
        (self.root / name).write_bytes(data)
        return {"gameId": identifier, "path": name, "samples": count,
                "sha256": hashlib.sha256(data).hexdigest()}

    def manifest(self, count=6):
        rows = [self.write_game(f"game-{i}", i % 3 + 2) for i in range(count)]
        path = self.root / "manifest.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path, rows

    def test_compressed_and_plain_samples_have_identical_features(self):
        from policy_training import read_samples
        compressed = self.write_game("game-a", 3)
        plain = self.write_game("game-a", 3, compressed=False)
        first, first_audit = read_samples([self.root / compressed["path"]], 4)
        second, second_audit = read_samples([self.root / plain["path"]], 4)
        self.assertEqual(len(first), 3)
        for lhs, rhs in zip(first, second):
            for field in ("planes", "globals", "actions"):
                np.testing.assert_array_equal(lhs[field], rhs[field])
            self.assertEqual(lhs["target"], rhs["target"])
        self.assertEqual(first_audit["inputs"][0]["sha256"], compressed["sha256"])
        self.assertEqual(second_audit["inputs"][0]["sha256"], plain["sha256"])

    def test_manifest_split_is_disjoint_deterministic_and_subset_is_explicit(self):
        from policy_corpus_training import read_manifest
        path, rows = self.manifest(40)
        first, groups, audit = read_manifest(path, seed=42, max_games=30)
        path.write_text("".join(json.dumps(row) + "\n" for row in reversed(rows)))
        second, reversed_groups, _ = read_manifest(path, seed=42, max_games=30)
        self.assertEqual(groups, reversed_groups)
        self.assertEqual({name: len(values) for name, values in groups.items()},
                         {"train": 24, "validation": 3, "test": 3})
        combined = [identifier for values in groups.values() for identifier in values]
        self.assertEqual(len(set(combined)), 30)
        self.assertEqual(audit["manifestGames"], 40)
        self.assertEqual(audit["selectedGames"], 30)
        self.assertEqual(audit["maxGames"], 30)
        self.assertEqual(audit["matchLengthCoverage"], {"unknown": 30})
        self.assertEqual(first, second)
        with self.assertRaisesRegex(ValueError, "three distinct games"):
            read_manifest(path, seed=42, max_games=2)

    def test_manifest_and_shard_identity_counts_and_hashes_are_enforced(self):
        from policy_corpus_training import read_manifest, load_game
        path, rows = self.manifest()
        for changed in ([*rows, rows[0]], [{**rows[0], "path": "../outside.jsonl.zst"}, *rows[1:]],
                        [{**rows[0], "samples": 0}, *rows[1:]],
                        [{**rows[0], "sha256": "bad"}, *rows[1:]]):
            path.write_text("".join(json.dumps(row) + "\n" for row in changed))
            with self.assertRaises(ValueError):
                read_manifest(path, 42)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        groups, _, _ = read_manifest(path, 42)
        row = groups["train"][0]
        for changed in ({**row, "gameId": "wrong-game"}, {**row, "samples": row["samples"] + 1},
                        {**row, "sha256": "0" * 64}):
            with self.assertRaises(ValueError):
                load_game(changed, 4)

    def test_frozen_manifest_preserves_partitions_and_rejects_mixed_converters(self):
        from policy_corpus_training import read_manifest
        from policy_split import freeze_split
        path, rows = self.manifest(6)
        corpus = []
        for i, row in enumerate(rows):
            row['sourceSha256'] = hashlib.sha256(f'source-{i}'.encode()).hexdigest()
            row['converterSignature'] = 'a' * 64
            corpus.append({'gameId': row['gameId'], 'compressedSha256': row['sourceSha256'],
                           'eventsSha256': hashlib.sha256(f'events-{i}'.encode()).hexdigest()})
        split = freeze_split(corpus, [r['gameId'] for r in rows], {}, count=6)
        split_path = self.root / 'split.json'
        split_path.write_text(json.dumps(split))
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        _, groups, audit = read_manifest(path, 999, split_file=split_path)
        self.assertEqual(groups, split['groups'])
        self.assertEqual(audit['converterSignature'], 'a' * 64)
        with self.assertRaisesRegex(ValueError, 'cannot change a frozen split'):
            read_manifest(path, 42, max_games=3, split_file=split_path)
        rows[0]['converterSignature'] = 'b' * 64
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaisesRegex(ValueError, 'mixes converter'):
            read_manifest(path, 42, split_file=split_path)

    def test_metric_merge_weights_decisions_instead_of_games(self):
        from policy_corpus_training import merge_metrics
        from policy_training import CandidatePolicy, read_samples, evaluate
        row = self.write_game("metrics", 4)
        samples, _ = read_samples([self.root / row["path"]], 4)
        samples = samples + [deepcopy(samples[0])]
        samples[-1]["actions"] = samples[-1]["actions"][:1]
        samples[-1]["target"] = 0
        model = CandidatePolicy({"channels": 4, "blocks": 1, "hidden": 8})
        direct = evaluate(model, samples, "cpu", 2)
        merged = merge_metrics([evaluate(model, samples[:1], "cpu", 2),
                                evaluate(model, samples[1:], "cpu", 2)])
        for field in ("samples", "choices", "forced", "byAction", "macroActionAccuracy"):
            self.assertEqual(merged[field], direct[field])
        for field in ("choiceTop1", "choiceTop3", "choiceNll"):
            self.assertAlmostEqual(merged[field], direct[field], places=6)

    def test_shared_state_scoring_preserves_logits_and_training_gradients(self):
        import torch
        from policy_training import CandidatePolicy, read_samples, batch_tensors
        row = self.write_game('factorized', 3)
        samples, _ = read_samples([self.root / row['path']], 4)
        model = CandidatePolicy({'channels': 4, 'blocks': 1, 'hidden': 8})
        planes, globals_, actions, mask, targets = batch_tensors(samples, 'cpu')
        old_encoded = model.blocks(torch.relu(model.conv(planes))).flatten(1)
        old_encoded = torch.relu(model.state(torch.cat((old_encoded, globals_), dim=1)))
        expanded = old_encoded[:, None, :].expand(-1, actions.shape[1], -1)
        expected = model.score(torch.cat((expanded, actions), dim=2)).squeeze(-1).masked_fill(~mask, -torch.inf)
        actual = model(planes, globals_, actions, mask)
        torch.testing.assert_close(actual, expected, atol=1e-6, rtol=1e-5)
        torch.nn.functional.cross_entropy(expected, targets).backward()
        old_gradients = {name: value.grad.clone() for name, value in model.named_parameters()}
        model.zero_grad(set_to_none=True)
        torch.nn.functional.cross_entropy(actual, targets).backward()
        for name, value in model.named_parameters():
            torch.testing.assert_close(value.grad, old_gradients[name], atol=1e-6, rtol=1e-5)

    def test_streamed_training_exports_held_out_report_and_reads_one_game_at_a_time(self):
        import policy_corpus_training as corpus
        from policy_model import PolicyModel
        path, _ = self.manifest()
        output = self.root / "model.npz"
        actual_read = corpus.read_samples
        actual_batch = corpus.batch_tensors
        calls, sizes = [], []

        def read_one(paths, players):
            self.assertEqual(len(paths), 1)
            calls.append(paths[0])
            return actual_read(paths, players)

        def bounded_batch(samples, device):
            sizes.append(len(samples))
            self.assertLessEqual(len(samples), 2)
            return actual_batch(samples, device)

        with patch.object(corpus, "read_samples", side_effect=read_one), \
                patch.object(corpus, "batch_tensors", side_effect=bounded_batch):
            _, report = corpus.train_corpus(path, output, max_games=4, batch_size=2,
                                             config={"channels": 4, "blocks": 1, "hidden": 8})
        self.assertTrue(calls)
        self.assertTrue(sizes)
        self.assertEqual(report["purpose"], "behavior-cloning")
        self.assertEqual(report["dataAudit"]["manifestGames"], 6)
        self.assertEqual(report["dataAudit"]["selectedGames"], 4)
        self.assertEqual(report["dataAudit"]["selectedGameCounts"], {"train": 2, "validation": 1, "test": 1})
        self.assertEqual(report["bestEpoch"], 1)
        self.assertTrue(report["exportParity"]["argmaxAgreement"])
        self.assertLess(report["exportParity"]["maxAbsError"], 1e-4)
        self.assertEqual(PolicyModel(output).metadata["purpose"], "behavior-cloning")
        self.assertEqual(json.loads(output.with_suffix(".report.json").read_text()), report)
        for name, values in report["metrics"].items():
            self.assertEqual(values["samples"], report["dataAudit"]["partitions"][name]["samples"])
            self.assertIsNotNone(values["choiceNll"])

    def test_failed_export_parity_keeps_existing_model_and_removes_temporary(self):
        import policy_corpus_training as corpus
        path, _ = self.manifest(3)
        output = self.root / "model.npz"
        output.write_bytes(b"existing-model")
        with patch.object(corpus, "verify_export", side_effect=ValueError("export parity failed")):
            with self.assertRaisesRegex(ValueError, "export parity failed"):
                corpus.train_corpus(path, output, batch_size=2,
                                    config={"channels": 4, "blocks": 1, "hidden": 8})
        self.assertEqual(output.read_bytes(), b"existing-model")
        self.assertFalse(output.with_suffix(".report.json").exists())
        self.assertEqual(list(self.root.glob(".policy-corpus-*.npz")), [])

    def test_encoded_cache_is_exact_reuses_verified_features_and_rechecks_source(self):
        import policy_corpus_training as corpus
        path, _ = self.manifest()
        partitions, _, _ = corpus.read_manifest(path, 42)
        row = partitions["train"][0]
        expected, audit = corpus.load_game(row, 4)
        cache = self.root / "cache"
        corpus.load_game(row, 4, cache)
        with patch.object(corpus, "read_samples", side_effect=AssertionError("cache recomputed features")):
            actual, cached_audit = corpus.load_game(row, 4, cache)
        self.assertEqual(cached_audit, audit)
        for left, right in zip(expected, actual):
            for key in ("planes", "globals", "actions"):
                np.testing.assert_array_equal(left[key], right[key])
            for key in ("game", "target", "action", "labelSource"):
                self.assertEqual(left[key], right[key])
        row["path"].write_bytes(b"changed source bytes")
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            corpus.load_game(row, 4, cache)

    def test_resume_restores_exact_training_order_optimizer_rng_and_final_test_once(self):
        import policy_corpus_training as corpus
        path, _ = self.manifest()
        options = {"epochs": 2, "batch_size": 2, "checkpoint_every_games": 1,
                   "game_window": 2, "config": {"channels": 4, "blocks": 1, "hidden": 8}}
        expected, expected_report = corpus.train_corpus(path, self.root / "baseline.npz", **options)
        output = self.root / "resumed.npz"
        original_save, original_evaluate = corpus.save_training_checkpoint, corpus.evaluate_corpus
        phases = []

        def interrupt_after_save(checkpoint, payload):
            original_save(checkpoint, payload)
            raise InterruptedError("simulated process interruption")

        def record_evaluation(*args, **kwargs):
            phases.append(kwargs.get("phase"))
            return original_evaluate(*args, **kwargs)

        with patch.object(corpus, "save_training_checkpoint", side_effect=interrupt_after_save), \
                patch.object(corpus, "evaluate_corpus", side_effect=record_evaluation):
            with self.assertRaises(InterruptedError):
                corpus.train_corpus(path, output, **options)
        self.assertEqual(phases, [])
        with patch.object(corpus, "evaluate_corpus", side_effect=record_evaluation):
            actual, report = corpus.train_corpus(path, output, resume=True, **options)
        for key, value in expected.state_dict().items():
            torch.testing.assert_close(value, actual.state_dict()[key], rtol=0, atol=0)
        for field in ("gameSplit", "history", "metrics", "bestEpoch"):
            self.assertEqual(report[field], expected_report[field])
        self.assertEqual(report["streaming"]["optimizerSteps"], expected_report["streaming"]["optimizerSteps"])
        self.assertEqual(phases.count("final-test"), 1)
        self.assertLessEqual(report["streaming"]["largestTrainingWindowSamples"],
                             2 * report["streaming"]["largestTrainingGameSamples"])
        with self.assertRaisesRegex(ValueError, "already completed"):
            corpus.train_corpus(path, output, resume=True, **options)

    def test_resume_rejects_changed_hyperparameters_or_manifest(self):
        import policy_corpus_training as corpus
        path, _ = self.manifest()
        output = self.root / "resumed.npz"
        options = {"epochs": 2, "batch_size": 2, "checkpoint_every_games": 1,
                   "config": {"channels": 4, "blocks": 1, "hidden": 8}}
        original_save = corpus.save_training_checkpoint

        def interrupt_after_save(checkpoint, payload):
            original_save(checkpoint, payload)
            raise InterruptedError()

        with patch.object(corpus, "save_training_checkpoint", side_effect=interrupt_after_save):
            with self.assertRaises(InterruptedError):
                corpus.train_corpus(path, output, **options)
        for changed in ({"batch_size": 3}, {"learning_rate": .002}, {"seed": 43}, {"epochs": 3},
                        {"game_window": 2}):
            with self.assertRaisesRegex(ValueError, "differs in source"):
                corpus.train_corpus(path, output, resume=True, **{**options, **changed})
        path.write_text("\n".join(reversed(path.read_text().splitlines())) + "\n")
        with self.assertRaisesRegex(ValueError, "differs in source"):
            corpus.train_corpus(path, output, resume=True, **options)


if __name__ == "__main__":
    unittest.main()
