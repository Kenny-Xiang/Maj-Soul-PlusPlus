"""Match rules must be explicit, source-bound, and recheckable against originals."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import policy_match_metadata as metadata
from policy_metadata import validate_match_metadata
from test_policy_official_archive import GAME, OTHER, fixture_schema, response


class MatchMetadataTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        schema = fixture_schema()
        schema_patch = patch("policy_official_archive.fetch.SCHEMA_SHA256", hashlib.sha256(schema).hexdigest())
        schema_patch.start()
        self.addCleanup(schema_patch.stop)
        self.archive = metadata.OfficialArchive(self.root / "official", schema)
        self.archive.add(response(), expected_uuid=GAME)
        self.source = {"gameId": GAME, "compressedSha256": "1" * 64,
                       "roundCount": 17, "roomEvidence": {"room": "throne"}}
        self.other = {"gameId": OTHER, "compressedSha256": "2" * 64, "roundCount": 12}
        self.manifest = self.root / "corpus.jsonl"
        self.manifest.write_text("".join(json.dumps(row) + "\n" for row in (self.source, self.other)))
        self.output = self.root / "metadata.jsonl"

    def build(self):
        return metadata.build_metadata(self.archive.output, self.manifest, self.output)

    def test_verified_south_does_not_use_played_hand_count_and_missing_stays_unknown(self):
        report = self.build()
        rows = metadata.load_metadata(self.output, [self.source, self.other])
        self.assertEqual(rows[GAME]["modeId"], 16)
        self.assertEqual(rows[GAME]["roundCount"], 2)
        self.assertNotIn(OTHER, rows)
        self.assertEqual(report["knownMatchGames"], 1)
        self.assertEqual(report["unknownMatchGames"], 1)
        self.assertEqual(report["networkRequests"], 0)
        self.assertIsNone(validate_match_metadata(None, OTHER))
        self.assertEqual(report, self.build())

    def test_east_mode_maps_to_one_round_set(self):
        east = metadata.OfficialArchive(self.root / "east", (self.archive.output / "schema.liqi.json").read_bytes())
        east.add(response(identifier=OTHER, mode_id=15), expected_uuid=OTHER)
        metadata.build_metadata(east.output, self.manifest, self.output)
        rows = metadata.load_metadata(self.output, [self.source, self.other])
        self.assertEqual(rows[OTHER]["modeId"], 15)
        self.assertEqual(rows[OTHER]["roundCount"], 1)

    def test_inconsistent_metadata_and_foreign_uuid_or_source_are_rejected(self):
        self.build()
        row = json.loads(self.output.read_text())
        for field, value in (("roundCount", 1), ("modeId", 26), ("playerCount", 3),
                             ("modeId", True), ("roundCount", True), ("provenance", {})):
            changed = {**row, field: value}
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_match_metadata(changed, GAME, self.source["compressedSha256"])
        with self.assertRaisesRegex(ValueError, "game ID differs"):
            validate_match_metadata(row, OTHER)
        with self.assertRaisesRegex(ValueError, "source hash differs"):
            metadata.load_metadata(self.output, [{**self.source, "compressedSha256": "f" * 64}])
        copied = validate_match_metadata(row)
        copied["provenance"]["headSha256"] = "0" * 64
        self.assertNotEqual(copied, row)

    def test_valid_looking_mode_change_is_rejected_against_original_response(self):
        self.build()
        row = json.loads(self.output.read_text())
        row.update(modeId=15, roundCount=1)
        self.output.write_text(json.dumps(row) + "\n")
        with self.assertRaisesRegex(ValueError, "original official response"):
            metadata.load_metadata(self.output, [self.source, self.other])
        with self.assertRaisesRegex(ValueError, "Existing metadata differs"):
            self.build()

    def test_modified_original_header_is_rejected(self):
        self.build()
        path = self.archive.output / self.archive.games[GAME]["files"]["head"]["path"]
        head = json.loads(path.read_bytes())
        head["config"]["meta"]["mode_id"] = 15
        path.write_text(json.dumps(head))
        with self.assertRaisesRegex(ValueError, "integrity check failed"):
            metadata.load_metadata(self.output, [self.source, self.other])

    def test_duplicate_or_unmatched_metadata_is_rejected(self):
        self.build()
        original = self.output.read_bytes()
        self.output.write_bytes(original * 2)
        with self.assertRaisesRegex(ValueError, "Duplicate or unmatched"):
            metadata.load_metadata(self.output, [self.source, self.other])
        self.output.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "Duplicate or unmatched"):
            metadata.load_metadata(self.output, [self.other])


if __name__ == "__main__":
    unittest.main()
