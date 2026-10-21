import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from policy_split import freeze_split, read_split


class FrozenSplitTests(unittest.TestCase):
    def setUp(self):
        self.corpus = [{"gameId": f"game-{i}",
                        "compressedSha256": hashlib.sha256(f"compressed-{i}".encode()).hexdigest(),
                        "eventsSha256": hashlib.sha256(f"events-{i}".encode()).hexdigest()}
                       for i in range(50)]
        self.preferred = [row["gameId"] for row in self.corpus[:30]]
        self.excluded = {"game-0": "paired calibration", "game-1": "previous smoke experiment"}

    def test_reserves_calibration_and_replaces_without_changing_count(self):
        split = freeze_split(self.corpus, self.preferred, self.excluded, count=30)
        groups = split["groups"]
        self.assertEqual({name: len(ids) for name, ids in groups.items()},
                         {"train": 24, "validation": 3, "test": 3})
        selected = [game for ids in groups.values() for game in ids]
        self.assertEqual(len(set(selected)), 30)
        self.assertFalse(set(selected) & self.excluded.keys())
        self.assertEqual(split["selection"]["replacementGames"], 2)
        self.assertEqual(split, freeze_split(list(reversed(self.corpus)), list(reversed(self.preferred)),
                                            self.excluded, count=30))

    def test_training_rejects_overlap_missing_games_and_changed_sources(self):
        split = freeze_split(self.corpus, self.preferred, self.excluded, count=30)
        hashes = {game: row["compressedSha256"] for game, row in split["sources"].items()}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "split.json"
            path.write_text(json.dumps(split))
            groups, audit = read_split(path, hashes)
            self.assertEqual(groups, split["groups"])
            self.assertEqual(audit["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ValueError, "source hash"):
                read_split(path, {**hashes, next(iter(hashes)): "0" * 64})
            with self.assertRaisesRegex(ValueError, "manifest games"):
                read_split(path, dict(list(hashes.items())[1:]))
            split["groups"]["test"][0] = split["groups"]["train"][0]
            path.write_text(json.dumps(split))
            with self.assertRaisesRegex(ValueError, "overlaps"):
                read_split(path, hashes)

    def test_semantic_duplicate_and_unknown_selection_are_rejected(self):
        self.corpus[1]["eventsSha256"] = self.corpus[0]["eventsSha256"]
        with self.assertRaisesRegex(ValueError, "duplicate source"):
            freeze_split(self.corpus, self.preferred, self.excluded, count=30)
        with self.assertRaisesRegex(ValueError, "unknown games"):
            freeze_split(self.corpus[2:], self.preferred, {}, count=30)

    def test_selected_partitions_accept_partial_or_full_metadata_but_require_selected_games(self):
        split = freeze_split(self.corpus, self.preferred, self.excluded, count=30)
        names = ("train", "validation")
        selected = {game for name in names for game in split["groups"][name]}
        hashes = {game: row["compressedSha256"] for game, row in split["sources"].items()}
        partial = {game: hashes[game] for game in selected}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "split.json"
            path.write_text(json.dumps(split))
            for supplied in (partial, hashes):
                groups, audit = read_split(path, supplied, partitions=names)
                self.assertEqual(groups, {name: split["groups"][name] for name in names})
                self.assertEqual(audit["selectedPartitions"], list(names))
                self.assertEqual(audit["selectedGames"], 27)
                self.assertEqual(audit["fullPartitionCounts"]["test"], 3)
            for invalid in (dict(list(partial.items())[1:]), {**partial, "unknown": "f" * 64}):
                with self.assertRaisesRegex(ValueError, "manifest games"):
                    read_split(path, invalid, partitions=names)
            for game in (next(iter(selected)), split["groups"]["test"][0]):
                with self.assertRaisesRegex(ValueError, "source hash differs"):
                    read_split(path, {**hashes, game: "f" * 64}, partitions=names)
            for invalid in ((), ("train", "train"), ("unknown",), "train"):
                with self.assertRaisesRegex(ValueError, "known frozen partitions"):
                    read_split(path, hashes, partitions=invalid)
            with self.assertRaisesRegex(ValueError, "manifest games"):
                read_split(path, partial)

    def test_selection_still_validates_unselected_partition_metadata(self):
        split = freeze_split(self.corpus, self.preferred, self.excluded, count=30)
        selected = split["groups"]["train"]
        hashes = {game: split["sources"][game]["compressedSha256"] for game in selected}
        test_game = split["groups"]["test"][0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "split.json"
            for value in ("bad", split["sources"][selected[0]]["eventsSha256"]):
                split["sources"][test_game]["eventsSha256"] = value
                path.write_text(json.dumps(split))
                with self.assertRaisesRegex(ValueError, "frozen source hash"):
                    read_split(path, hashes, partitions=("train",))
            split["groups"]["test"][0] = selected[0]
            path.write_text(json.dumps(split))
            with self.assertRaisesRegex(ValueError, "overlaps"):
                read_split(path, hashes, partitions=("train",))

    def test_expansion_preserves_existing_holdouts_and_source_binding(self):
        old = freeze_split(self.corpus, self.preferred, self.excluded, count=30)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "previous.json"
            path.write_text(json.dumps(old))
            enlarged = freeze_split(self.corpus, self.preferred, self.excluded,
                                    count=40, seed=7, previous=path)
            self.assertEqual({k: len(v) for k, v in enlarged["groups"].items()},
                             {"train": 32, "validation": 4, "test": 4})
            for name, games in old["groups"].items():
                self.assertTrue(set(games) <= set(enlarged["groups"][name]))
            self.assertEqual(enlarged["previousSplit"]["preservedGames"], 30)
            with self.assertRaisesRegex(ValueError, "exclusions"):
                freeze_split(self.corpus, self.preferred, {}, count=40, previous=path)
            with self.assertRaisesRegex(ValueError, "shrink"):
                freeze_split(self.corpus, self.preferred, self.excluded, count=20, previous=path)
            identifier = next(iter(old["sources"]))
            next(row for row in self.corpus if row["gameId"] == identifier)["eventsSha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "event hash"):
                freeze_split(self.corpus, self.preferred, self.excluded, count=40, previous=path)


if __name__ == "__main__":
    unittest.main()
