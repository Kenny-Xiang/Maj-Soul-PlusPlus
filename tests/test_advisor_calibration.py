"""Synthetic integrity tests, deliberately NOT game-record calibration evidence."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from test_advisor import state


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("advisor_calibration", ROOT / "scripts/advisor_calibration.py")
calibration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(calibration)


def dataset(directory):
    snapshot = state()
    snapshot["rivers"][1] = [{"tile": "9p", "step": 39, "moqie": False, "called": False}]
    targets = sorted(set(snapshot["hand"]))
    labels = [{"seat": seat, "tenpai": seat == 1,
               "tiles": {tile: {"legalRon": seat == 1 and tile == "1z",
                                "lossPoints": 2000 if seat == 1 and tile == "1z" else 0}
                         for tile in targets}} for seat in (1, 2, 3)]
    matches = []
    for index, day in enumerate((1, 3, 5)):
        replay = directory / f"synthetic-{index}.json"
        replay.write_text(json.dumps({"synthetic": True, "index": index}))
        matches.append({"id": f"match-{index}", "startedAt": f"2026-01-0{day}T10:00:00Z",
                        "endedAt": f"2026-01-0{day}T11:00:00Z",
                        "replay": {"path": replay.name, "sha256": calibration.sha256(replay)},
                        "decisions": [{"roundId": "0-0-0", "step": 40, "at": f"2026-01-0{day}T10:30:00Z",
                                       "publicState": deepcopy(snapshot), "opponents": deepcopy(labels)}]})
    return {"schemaVersion": 1, "source": {"kind": "synthetic-test", "exporter": "unit-test",
            "labeler": "invented-test-values", "ruleset": "majsoul-standard",
            "labelMethod": "omniscient-state-before-discard"}, "matches": matches}


class CalibrationExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.data = dataset(self.directory)

    def test_existing_recording_cannot_supply_calibration_labels(self):
        report = calibration.audit()
        self.assertEqual(report["status"], "not-calibrated-no-labelled-dataset")
        self.assertEqual(report["recording"]["openingEvents"], 0)
        self.assertEqual(report["recording"]["terminalEvents"], 0)
        self.assertGreater(report["recording"]["hiddenDraws"], 0)

    def test_three_conditional_layers_use_distinct_denominators(self):
        original = deepcopy(self.data)
        extracted = calibration.extract(self.data, self.directory)
        rows = extracted["rows"]
        tile_count = len(set(state()["hand"]))
        self.assertEqual(sum(r["layer"] == "tenpai" for r in rows), 9)
        self.assertEqual(sum(r["layer"] == "ronGivenTenpai" for r in rows), 3 * tile_count)
        self.assertEqual(sum(r["layer"] == "paymentGivenRon" for r in rows), 3)
        self.assertEqual(sum(r["layer"] == "dealIn" for r in rows), 9 * tile_count)
        self.assertEqual(self.data, original)
        feature = next(r["features"] for r in rows if r["opponentSeat"] == 1)
        self.assertEqual(feature["tedashiCount"], 1)
        self.assertEqual(feature["river"][0]["step"], 39)

    def test_hidden_and_future_result_fields_do_not_reach_predictor(self):
        class Spy:
            MODEL = "spy"

            def unseen_counts(self, public):
                self.seen = public
                return ()

            def _opponents(self, public, remaining):
                return []

            def _danger(self, tile, remaining, enemies):
                return 0, 0, [{"seat": i, "tenpaiProbability": .2,
                              "conditionalRonProbability": .1, "lossPoints": 2000} for i in (1, 2, 3)]

        raw = self.data["matches"][0]["decisions"][0]["publicState"]
        raw["opponentHands"] = [["5z"]]
        raw["futureScores"] = [1, 2, 3, 4]
        raw["round"]["winner"] = 1
        raw["rivers"][1][0]["nextHiddenDraw"] = "5z"
        spy = Spy()
        calibration.extract(self.data, self.directory, spy)
        for match in self.data["matches"][1:]:
            match["decisions"][0]["publicState"] = deepcopy(raw)
        calibration.extract(self.data, self.directory, spy)
        self.assertNotIn("opponentHands", spy.seen)
        self.assertNotIn("futureScores", spy.seen)
        self.assertNotIn("winner", spy.seen["round"])
        self.assertNotIn("nextHiddenDraw", spy.seen["rivers"][1][0])

    def test_bad_sources_future_steps_and_missing_negative_labels_rejected(self):
        alterations = [
            lambda d: d["source"].update(labelMethod="terminal-winners-only"),
            lambda d: d["matches"][0]["replay"].update(sha256="0" * 64),
            lambda d: d["matches"][0]["decisions"][0]["publicState"]["rivers"][1][0].update(step=41),
            lambda d: d["matches"][0]["decisions"][0]["publicState"].update(historyComplete=False),
            lambda d: d["matches"][0]["decisions"][0]["publicState"].pop("doras"),
            lambda d: d["matches"][0]["decisions"][0]["opponents"][1]["tiles"].pop("1z"),
            lambda d: d["matches"][0]["decisions"][0]["opponents"][0].update(tenpai=False),
            lambda d: d["matches"][0]["decisions"][0]["opponents"][0]["tiles"]["1z"].update(lossPoints=float("nan")),
            lambda d: d["matches"][0]["decisions"].append(deepcopy(d["matches"][0]["decisions"][0])),
        ]
        for alteration in alterations:
            with self.subTest(alteration=alteration):
                changed = deepcopy(self.data)
                alteration(changed)
                with self.assertRaises(ValueError):
                    calibration.extract(changed, self.directory)

    def test_duplicate_replay_cannot_leak_into_different_match(self):
        self.data["matches"][1]["replay"] = deepcopy(self.data["matches"][0]["replay"])
        with self.assertRaisesRegex(ValueError, "multiple match IDs"):
            calibration.extract(self.data, self.directory)

    def test_sanma_has_two_opponents_and_red_tile_keeps_identity(self):
        for match in self.data["matches"]:
            decision = match["decisions"][0]
            public = state("123p123s789s40p77z1z", players=3)
            decision["publicState"] = public
            decision["opponents"] = [{"seat": i, "tenpai": False,
                "tiles": {tile: {"legalRon": False, "lossPoints": 0} for tile in set(public["hand"])}}
                for i in (1, 2)]
        rows = calibration.extract(self.data, self.directory)["rows"]
        self.assertEqual(sum(r["layer"] == "tenpai" for r in rows), 6)
        self.assertTrue(any(r.get("tile") == "0p" for r in rows))


class CalibrationEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        directory = Path(self.temporary.name)
        self.extracted = calibration.extract(dataset(directory), directory)
        self.cutoffs = ("2026-01-02T00:00:00Z", "2026-01-04T00:00:00Z")

    def test_time_and_match_splits_are_disjoint_and_test_labels_never_fit(self):
        before = calibration.evaluate(self.extracted, *self.cutoffs)
        for row in self.extracted["rows"]:
            if row["matchId"] != "match-0":
                row["outcome"] = 9876 if row["layer"] == "paymentGivenRon" else 1 - row["outcome"]
        after = calibration.evaluate(self.extracted, *self.cutoffs)
        self.assertEqual(before["fittedOnTrainOnly"], after["fittedOnTrainOnly"])
        self.assertEqual(before["split"]["matches"], {"match-0": "train", "match-1": "validation", "match-2": "test"})
        self.assertEqual(before["status"], "synthetic-pipeline-check")
        self.assertNotEqual(before["evaluation"]["test"], after["evaluation"]["test"])

    def test_match_crossing_a_time_boundary_is_excluded_whole(self):
        self.extracted["matches"]["match-0"]["endedAt"] = "2026-01-02T00:00:01Z"
        report = calibration.evaluate(self.extracted, *self.cutoffs)
        self.assertEqual(report["split"]["excludedBoundaryMatches"], ["match-0"])
        self.assertEqual(report["evaluation"]["train"]["layers"]["tenpai"]["baseline"]["count"], 0)

    def test_probability_scores_and_payment_errors_have_known_values(self):
        rows = [{"prediction": .25, "outcome": 0}, {"prediction": .75, "outcome": 1}]
        metrics = calibration.probability_metrics(rows, 2)
        self.assertAlmostEqual(metrics["brier"], .0625)
        self.assertAlmostEqual(metrics["ece"], .25)
        self.assertEqual(metrics["positives"], 1)
        payments = calibration.metrics([{"prediction": 1000, "outcome": 2000},
                                        {"prediction": 4000, "outcome": 2000}], "paymentGivenRon", 2)
        self.assertEqual(payments["mae"], 1500)
        self.assertEqual(payments["bias"], 500)

    def test_structural_probabilities_stay_fixed_and_empty_bins_fall_back(self):
        fitted = calibration.fit([{"layer": "tenpai", "prediction": .2, "outcome": 1}], 10)
        for probability in (0, 1, .8):
            row = {"layer": "tenpai", "prediction": probability, "outcome": 0}
            self.assertEqual(calibration.adjusted(row, fitted, 10)["prediction"], probability)
        self.assertEqual(calibration.metrics([], "paymentGivenRon", 10), {"count": 0})
        self.assertEqual(calibration.probability_metrics([{"prediction": 0, "outcome": 1}], 10)["deterministicContradictions"], 1)


if __name__ == "__main__":
    unittest.main()
