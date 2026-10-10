"""Synthetic archive regressions; no downloaded corpus is needed."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

try:
    import zstandard
except ImportError:
    zstandard = None


if zstandard is not None:
    SPEC = importlib.util.spec_from_file_location(
        "policy_corpus_audit", Path(__file__).resolve().parents[1] / "scripts" / "policy_corpus_audit.py")
    audit = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(audit)


GAME_ID = "260101-11111111-2222-4333-8444-555555555555"
OTHER_ID = "260102-aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
THIRD_ID = "260103-12345678-1234-4123-8123-123456789abc"


def events():
    tiles = [f"{n}{suit}" for suit in "mps" for n in range(1, 10)] + list("ESWNPFC")
    tiles = [pai for pai in tiles for _ in range(4)]
    return [
        {"type": "start_game", "names": ["one", "two", "three", "four"]},
        {"type": "start_kyoku", "tehais": [tiles[i * 13:(i + 1) * 13] for i in range(4)],
         "bakaze": "E", "kyoku": 1, "honba": 0, "kyotaku": 0, "oya": 0,
         "dora_marker": "9s", "scores": [25000] * 4},
        {"type": "tsumo", "actor": 0, "pai": "N"},
        {"type": "dahai", "actor": 0, "pai": "N", "tsumogiri": True},
        {"type": "ryukyoku", "deltas": [0] * 4},
        {"type": "end_kyoku"},
        {"type": "end_game"},
    ]


def compressed(value=None, pretty=False):
    value = events() if value is None else value
    separators = (",", ":") if not pretty else None
    raw = "\n".join(json.dumps(event, separators=separators) for event in value).encode() + b"\n"
    return zstandard.ZstdCompressor().compress(raw)


def member_name(identifier):
    return "majsoul-throne-2026/" + identifier.replace("-", "_") + ".mjai.json.zst"


def make_archive(path, members):
    with tarfile.open(path, "w") as archive:
        for name, content in members:
            member = tarfile.TarInfo(name)
            if content is None:
                member.type = tarfile.SYMTYPE
                member.linkname = "/tmp/not-a-real-game"
                archive.addfile(member)
            else:
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))


@unittest.skipIf(zstandard is None, "optional zstandard dependency is not installed")
class CorpusAuditTests(unittest.TestCase):
    def test_game_id_normalization_and_invalid_paths(self):
        self.assertEqual(audit.game_id(member_name(GAME_ID)), GAME_ID)
        for name in ("../" + member_name(GAME_ID), "/" + member_name(GAME_ID),
                     member_name(GAME_ID.replace("260101", "260231")), "foo.mjai.json.zst"):
            with self.subTest(name=name), self.assertRaises(audit.InvalidGame):
                audit.game_id(name)

    def test_complete_game_round_counts_and_multi_ron(self):
        value = events()
        value[4] = {"type": "hora", "actor": 1, "target": 0, "deltas": [-8000, 8000, 0, 0]}
        value.insert(5, {"type": "hora", "actor": 2, "target": 0})
        value[-1:-1] = copy.deepcopy(value[1:-1])
        result = audit.validate_game(compressed(value))
        self.assertEqual(result["roundCount"], 2)
        self.assertEqual(result["eventTypes"]["hora"], 4)
        self.assertEqual(result["players"], 4)
        self.assertEqual(result["eventCount"], len(value))

    def test_missing_boundaries_result_hands_and_bad_seats_are_rejected(self):
        mutations = [
            lambda rows: rows.pop(0),
            lambda rows: rows.pop(),
            lambda rows: rows.pop(-2),
            lambda rows: rows.pop(-3),
            lambda rows: rows[0].update(names=["a"] * 3),
            lambda rows: rows[1]["tehais"][1].pop(),
            lambda rows: rows[1]["tehais"][1].__setitem__(0, "?"),
            lambda rows: rows[1].update(oya=4),
            lambda rows: rows[2].update(actor=-1),
            lambda rows: rows[2].update(actor=True),
            lambda rows: rows[3].update(tsumogiri=1),
            lambda rows: rows.insert(5, {"type": "tsumo", "actor": 0, "pai": "E"}),
            lambda rows: rows.insert(6, {"type": "future_extension"}),
            lambda rows: rows[2].update(type=[]),
            lambda rows: rows[1].update(bakaze=[]),
            lambda rows: rows.insert(6, {"type": "start_game", "names": ["a"] * 4}),
        ]
        for mutate in mutations:
            value = events()
            mutate(value)
            with self.subTest(mutation=mutate), self.assertRaises(audit.InvalidGame):
                audit.validate_game(compressed(value))

    def test_corruption_and_invalid_json_are_rejected(self):
        with_checksum = zstandard.ZstdCompressor(write_checksum=True).compress(
            "\n".join(json.dumps(event) for event in events()).encode())
        for payload in (b"not zstandard", zstandard.ZstdCompressor().compress(b"not json"),
                        zstandard.ZstdCompressor().compress(b"[]\n"),
                        with_checksum[:-1], with_checksum + b"junk", with_checksum * 2):
            with self.subTest(payload=payload), self.assertRaises(audit.InvalidGame):
                audit.validate_game(payload)

    def test_archive_counts_games_not_rounds_and_deduplicates_id_and_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar"
            broken = events()[:-1]
            make_archive(archive, [
                (member_name(GAME_ID), compressed()),
                (member_name(GAME_ID), compressed()),
                (member_name(OTHER_ID), compressed(pretty=True)),
                (member_name(THIRD_ID), compressed(broken)),
                ("../" + member_name(THIRD_ID), compressed()),
                ("symlink", None),
            ])
            report = audit.audit_archives([archive], root / "corpus", 10000, "https://example.test/pinned")
            self.assertEqual(report["uniqueCompleteGames"], 1)
            self.assertFalse(report["goalReached"])
            self.assertTrue(report["archives"][0]["fullyScanned"])
            self.assertEqual(report["excluded"], {"duplicate_game_id": 1, "duplicate_content": 1,
                                                   "missing_game_boundary": 1, "invalid_member_name": 1,
                                                   "non_regular_member": 1})
            rows = [json.loads(line) for line in (root / "corpus/manifest.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertNotIn("names", rows[0])
            self.assertIsNone(rows[0]["individualPlayerRanks"])
            self.assertFalse(rows[0]["officialOperationLists"])
            self.assertEqual(rows[0]["roomEvidence"]["kind"], "archive-publisher")
            self.assertEqual((root / "corpus" / rows[0]["path"]).read_bytes(), compressed())
            self.assertFalse((root / member_name(THIRD_ID)).exists())

    def test_limit_and_resume_verify_saved_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar"
            second = events()
            second[1]["honba"] = 1
            make_archive(archive, [(member_name(GAME_ID), compressed()),
                                   (member_name(OTHER_ID), compressed(second))])
            first = audit.audit_archives([archive], root / "corpus", 1, "https://example.test/pinned")
            self.assertTrue(first["goalReached"])
            self.assertFalse(first["archives"][0]["fullyScanned"])
            resumed = audit.audit_archives([archive], root / "corpus", 2, "https://example.test/pinned")
            self.assertEqual(resumed["resumedGames"], 1)
            self.assertEqual(resumed["newGames"], 1)
            self.assertEqual(resumed["uniqueCompleteGames"], 2)
            saved = root / f"corpus/data/games/{GAME_ID}.mjai.json.zst"
            saved.write_bytes(compressed(second))
            with self.assertRaises(ValueError):
                audit.audit_archives([archive], root / "corpus", 2, "https://example.test/pinned")


if __name__ == "__main__":
    unittest.main()
