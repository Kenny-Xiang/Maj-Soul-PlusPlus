"""Independent corpus boundaries and resumable MJAI conversion regressions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    import numpy
    import riichienv
    import torch
    import zstandard
except ImportError:
    riichienv = None

if riichienv is not None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import policy_convert_mjai as batch

from test_policy_mjai_review import passed_ron_game


GAME = "260101-11111111-2222-4333-8444-555555555555"
OTHER = "260102-aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


@unittest.skipIf(riichienv is None, "optional conversion and training dependencies are not installed")
class MjaiBatchTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.output = self.root / "converted"
        self.manifest = self.source / "manifest.jsonl"
        self.row = self.source_game()
        self.write_manifest([self.row])

    def source_game(self, identifier=GAME, honba=0):
        events = passed_ron_game(False)
        events[1]["honba"] = honba
        raw = "".join(json.dumps(event) + "\n" for event in events).encode()
        compressed = zstandard.ZstdCompressor(write_checksum=True).compress(raw)
        relative = f"data/games/{identifier}.mjai.json.zst"
        target = self.source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(compressed)
        return {"gameId": identifier, "path": relative,
                "compressedSha256": hashlib.sha256(compressed).hexdigest(),
                "roomEvidence": {"kind": "archive-publisher", "room": "throne",
                                 "independentlyVerified": False}}

    def write_manifest(self, rows):
        self.manifest.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def convert(self, limit=1):
        return batch.convert_corpus(self.manifest, self.output, limit=limit, workers=1)

    def output_rows(self):
        return [json.loads(line) for line in (self.output / "manifest.jsonl").read_text().splitlines()]

    def write_output_rows(self, rows):
        (self.output / "manifest.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))

    def test_real_compressed_conversion_is_accepted_by_training_reader(self):
        from policy_training import read_samples
        report = self.convert()
        self.assertTrue(report["goalReached"])
        self.assertEqual(report["convertedGames"], 1)
        self.assertEqual(report["failedGames"], [])
        rows = self.output_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["gameId"], GAME)
        self.assertEqual(row["path"], f"games/{GAME}.jsonl.zst")
        self.assertEqual(row["sourceSha256"], self.row["compressedSha256"])
        self.assertEqual(row["converterSignature"], batch.converter_signature())
        self.assertEqual(row["roomEvidence"], self.row["roomEvidence"])
        payload = (self.output / row["path"]).read_bytes()
        self.assertEqual(row["sha256"], hashlib.sha256(payload).hexdigest())
        loaded, audit = read_samples([self.output / row["path"]], players=4)
        self.assertEqual(len(loaded), row["samples"])
        self.assertEqual(len(loaded), report["samples"])
        self.assertEqual({sample["game"] for sample in loaded}, {GAME})
        self.assertEqual(audit["duplicateSamples"], 0)
        self.assertGreater(report["labelSources"].get("accepted", 0), 0)
        self.assertTrue((self.output / "audits" / f"{GAME}.json").exists())

    def test_hash_mismatch_is_excluded_without_publishing_a_shard(self):
        self.write_manifest([{**self.row, "compressedSha256": "0" * 64}])
        report = self.convert()
        self.assertFalse(report["goalReached"])
        self.assertEqual(report["convertedGames"], 0)
        self.assertEqual(len(report["failedGames"]), 1)
        self.assertIn("source hash mismatch", report["failedGames"][0]["error"])
        self.assertEqual(self.output_rows(), [])
        self.assertEqual(list((self.output / "games").iterdir()), [])

    def test_selected_frozen_conversion_never_dispatches_test_and_requires_exact_selection(self):
        from concurrent.futures import ThreadPoolExecutor
        from policy_split import freeze_split
        rows = [self.row, self.source_game(OTHER, honba=1),
                self.source_game("260103-aaaaaaaa-bbbb-4ccc-8ddd-ffffffffffff", honba=2)]
        for row in rows:
            row["eventsSha256"] = hashlib.sha256(("events:" + row["gameId"]).encode()).hexdigest()
        split = freeze_split(rows, [row["gameId"] for row in rows], {}, count=3)
        split_path = self.root / "split.json"
        split_path.write_text(json.dumps(split))
        allowed = set(split["groups"]["train"] + split["groups"]["validation"])
        test_row = next(row for row in rows if row["gameId"] not in allowed)
        (self.source / test_row["path"]).unlink()
        self.write_manifest(rows)
        original = batch.convert_one
        seen = set()

        def guarded(row, *args):
            self.assertIn(row["gameId"], allowed)
            seen.add(row["gameId"])
            return original(row, *args)

        options = {"limit": 2, "workers": 1, "split_file": split_path,
                   "partitions": ("train", "validation")}
        with patch.object(batch, "ProcessPoolExecutor", ThreadPoolExecutor), \
                patch.object(batch, "convert_one", side_effect=guarded):
            report = batch.convert_corpus(self.manifest, self.output, **options)
        self.assertEqual(seen, allowed)
        self.assertEqual({row["gameId"] for row in self.output_rows()}, allowed)
        self.assertTrue(report["goalReached"])
        self.assertEqual(report["selectedPartitions"], ["train", "validation"])
        self.assertEqual(report["frozenSplit"]["fullPartitionCounts"]["test"], 1)
        for changed, message in (({"limit": 3}, "selected frozen split size"),
                                 ({"split_file": None}, "requires a frozen split")):
            with self.assertRaisesRegex(ValueError, message):
                batch.convert_corpus(self.manifest, self.output, **{**options, **changed})
        self.write_manifest([row for row in rows if row["gameId"] in allowed])
        self.assertTrue(batch.convert_corpus(self.manifest, self.output, **options)["goalReached"])
        self.write_manifest([row for row in rows if row["gameId"] != next(iter(allowed))])
        with self.assertRaisesRegex(ValueError, "manifest games"):
            batch.convert_corpus(self.manifest, self.output, **options)

    def test_invalid_game_id_and_duplicate_game_or_content_are_rejected_up_front(self):
        other = self.source_game(OTHER, honba=1)
        invalid_rows = [
            [{**self.row, "gameId": "../../escaped"}],
            [self.row, self.row],
            [self.row, {**other, "gameId": GAME}],
            [self.row, {**other, "compressedSha256": self.row["compressedSha256"]}],
        ]
        for rows in invalid_rows:
            self.write_manifest(rows)
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.convert()
            self.assertFalse(self.output.exists())

    def test_source_path_traversal_and_symlink_escape_are_excluded(self):
        original = (self.source / self.row["path"]).read_bytes()
        outside = self.root / "outside.mjai.json.zst"
        outside.write_bytes(original)
        (self.source / "linked.mjai.json.zst").symlink_to(outside)
        for relative in ("../outside.mjai.json.zst", "linked.mjai.json.zst", str(outside)):
            self.write_manifest([{**self.row, "path": relative}])
            with self.subTest(path=relative):
                report = self.convert()
                self.assertEqual(report["convertedGames"], 0)
                self.assertIn("source path escapes corpus", report["failedGames"][0]["error"])
                self.assertEqual(list((self.output / "games").iterdir()), [])
        self.assertEqual(outside.read_bytes(), original)

    def test_resume_requires_current_converter_source_and_output_hash(self):
        first = self.convert()
        original_rows = self.output_rows()
        original_payload = (self.output / original_rows[0]["path"]).read_bytes()
        resumed = self.convert()
        self.assertEqual(resumed["resumedGames"], 1)
        self.assertEqual(resumed["samples"], first["samples"])
        self.assertEqual(self.output_rows(), original_rows)

        for key, wrong in (("converterSignature", "old-converter"),
                           ("sourceSha256", "0" * 64), ("sha256", "0" * 64),
                           ("path", "../outside.jsonl.zst")):
            rows = deepcopy(original_rows)
            rows[0][key] = wrong
            self.write_output_rows(rows)
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, "existing conversion differs"):
                self.convert()
            self.assertEqual((self.output / original_rows[0]["path"]).read_bytes(), original_payload)
        self.write_output_rows(original_rows)
        with patch.object(batch, "converter_signature", return_value="new-code-signature"):
            with self.assertRaisesRegex(ValueError, "existing conversion differs"):
                self.convert()
        self.write_output_rows(original_rows * 2)
        with self.assertRaisesRegex(ValueError, "existing conversion differs"):
            self.convert()

    def test_modified_saved_shard_is_rejected_before_resume(self):
        self.convert()
        row = self.output_rows()[0]
        target = self.output / row["path"]
        target.write_bytes(target.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, "existing conversion differs"):
            self.convert()

    def test_resume_rejects_changed_counts_or_audit_metadata(self):
        self.convert()
        original = self.output_rows()
        for field in ("samples", "bytes"):
            rows = deepcopy(original)
            rows[0][field] += 1
            self.write_output_rows(rows)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "existing conversion differs"):
                self.convert()
        for field in ("samples", "actions", "labelSources", "excluded"):
            rows = deepcopy(original)
            if field == "samples":
                rows[0]["audit"][field] += 1
            else:
                rows[0]["audit"][field]["tampered"] = 1
            self.write_output_rows(rows)
            with self.subTest(audit_field=field), self.assertRaisesRegex(ValueError, "saved audit differs"):
                self.convert()
        self.write_output_rows(original)
        audit_path = self.output / "audits" / f"{GAME}.json"
        audit_path.write_text(audit_path.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "saved audit differs"):
            self.convert()

    def test_resume_recomputes_action_counts_even_when_audit_files_agree(self):
        self.convert()
        original = self.output_rows()
        for field in ("samples", "actions", "labelSources"):
            rows = deepcopy(original)
            if field == "samples":
                rows[0]["audit"][field] += 1
            else:
                rows[0]["audit"][field]["tampered"] = 1
            audit_data = (json.dumps(rows[0]["audit"]) + "\n").encode()
            (self.output / "audits" / f"{GAME}.json").write_bytes(audit_data)
            rows[0]["auditSha256"] = hashlib.sha256(audit_data).hexdigest()
            self.write_output_rows(rows)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "audit counts differ from samples"):
                self.convert()


if __name__ == "__main__":
    unittest.main()
