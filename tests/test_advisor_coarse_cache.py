"""Exact projected-policy reuse must preserve inputs, ledgers and cancellation."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import advisor
from test_advisor import state, tiles


class CoarsePolicyCacheTests(unittest.TestCase):
    def inputs(self):
        return dict(events=[1, 2, 0, 3, 1, 0], seat=0, sh=2, ukeire=18,
                    value=3900., yaku_factor=.6, ron=(2000., .4), unseen=80,
                    average=(.08, 420.), survival=.97,
                    payments=(1200., 300.), fees=(-800., 1300.))

    def evaluate(self, inputs):
        with patch.object(advisor, "_policy_risks", return_value=([], [], inputs["average"])), \
                patch.object(advisor, "_policy_environment", return_value=(
                    inputs["survival"], inputs["payments"], inputs["fees"])):
            return advisor._coarse_policy([], {"selfSeat": inputs["seat"]},
                                          [inputs["unseen"]], [], inputs["events"],
                                          inputs["sh"], inputs["ukeire"], inputs["value"],
                                          inputs["yaku_factor"], ron=inputs["ron"])

    def test_every_projected_input_separates_exact_immutable_outcomes(self):
        base = self.inputs()
        variants = [base]
        for field, value in (("events", [2, 1, 0, 3, 1, 0]), ("seat", 1),
                             ("sh", 3), ("ukeire", 19), ("value", 3900.00000001),
                             ("yaku_factor", .60000000001),
                             ("ron", (2000.00000001, .4)), ("ron", (2000., .40000000001)),
                             ("average", (.08000000001, 420.)),
                             ("average", (.08, 420.00000001)), ("unseen", 79),
                             ("survival", .97000000001),
                             ("payments", (1200.00000001, 300.)),
                             ("payments", (1200., 300.00000001)),
                             ("fees", (-800.00000001, 1300.)),
                             ("fees", (-800., 1300.00000001))):
            variants.append({**base, field: value})
        token = advisor.TABLES.set(None)
        try:
            expected = [self.evaluate(inputs) for inputs in variants]
        finally:
            advisor.TABLES.reset(token)
        cache = {}
        token = advisor.TABLES.set(cache)
        try:
            with patch.object(advisor, "_policy_residual", wraps=advisor._policy_residual) as residual:
                for index, inputs in enumerate(variants):
                    with self.subTest(inputs=inputs):
                        actual = self.evaluate(inputs)
                        self.assertEqual(actual, expected[index])
                        calls = residual.call_count
                        self.assertIs(self.evaluate(inputs), actual)
                        self.assertEqual(residual.call_count, calls)
                        self.assertEqual(len(cache), index + 1)
                        with self.assertRaises(AttributeError):
                            actual.income = -1.
            # The default ron projection has exactly the same complete key.
            implicit = {**base, "ron": None}
            explicit = {**base, "ron": (base["value"], base["yaku_factor"])}
            self.assertIs(self.evaluate(implicit), self.evaluate(explicit))
        finally:
            advisor.TABLES.reset(token)

    def test_full_advice_and_terminal_ledgers_equal_uncached_coarse_policy(self):
        path = Path(__file__).parent / "fixtures/advisor_cases.json"
        fixtures = json.loads(path.read_text())["cases"]
        snapshots = [state("147m258p369s12345z")]
        for name, hand in (("sanma-kita", "19m2578p369s12344z"),
                           ("ankan", "1111m258p369s1234z")):
            snapshot = deepcopy(next(c["state"] for c in fixtures if c["id"] == name))
            snapshot["hand"] = tiles(hand)
            snapshot["lastDraw"] = snapshot["hand"][-1]
            snapshot["lastAction"]["tile"] = snapshot["lastDraw"]
            snapshots.append(snapshot)
        coarse = advisor._coarse_policy

        def uncached(*args, **kwargs):
            cache = advisor.TABLES.get()
            for key in list(cache):
                if key[0] == "coarse":
                    del cache[key]
            return coarse(*args, **kwargs)

        for snapshot in snapshots:
            with self.subTest(operations=snapshot["operations"]):
                original = deepcopy(snapshot)
                cached = advisor.advise(snapshot)
                with patch.object(advisor, "_coarse_policy", side_effect=uncached) as calculate:
                    expected = advisor.advise(snapshot)
                self.assertGreater(calculate.call_count, 0)
                self.assertEqual(cached["status"], "ready")
                self.assertEqual(expected["status"], "ready")
                if 11 in snapshot["operations"] or 4 in snapshot["operations"]:
                    action = "kita" if 11 in snapshot["operations"] else "ankan"
                    self.assertIn(action, [c["action"] for c in cached["candidates"]])
                cached.pop("elapsedMs")
                expected.pop("elapsedMs")
                self.assertEqual(cached, expected)
                self.assertEqual(snapshot, original)

    def test_each_decision_owns_and_releases_cache_on_all_exits(self):
        outer = {}
        token = advisor.TABLES.set(outer)
        seen = []

        def evaluate(snapshot):
            cache = advisor.TABLES.get()
            self.assertIsNot(cache, outer)
            self.assertEqual(cache, {})
            seen.append(cache)
            self.evaluate(self.inputs())
            self.assertTrue(cache)
            return {"status": "ready"}

        try:
            with patch.object(advisor, "_advise", side_effect=evaluate):
                for _ in range(2):
                    self.assertEqual(advisor.advise(state())["status"], "ready")
                    self.assertIs(advisor.TABLES.get(), outer)
            self.assertIsNot(seen[0], seen[1])
            with patch.object(advisor, "_advise", side_effect=RuntimeError("failed")):
                with self.assertRaisesRegex(RuntimeError, "failed"):
                    advisor.advise(state())
                self.assertIs(advisor.TABLES.get(), outer)
            self.assertEqual(advisor.advise(state(), cancelled=lambda: True)["status"], "unavailable")
            self.assertIs(advisor.TABLES.get(), outer)
            self.assertEqual(outer, {})
        finally:
            advisor.TABLES.reset(token)

    def test_cache_hits_and_empty_horizons_observe_cancellation_and_budget(self):
        for cancelled in (False, True):
            for events in ([], self.inputs()["events"]):
                with self.subTest(cancelled=cancelled, events=events):
                    obsolete, now = False, 0.
                    search_token = advisor._SEARCH.set((1., lambda: obsolete))
                    cache_token = advisor.TABLES.set({})
                    inputs = {**self.inputs(), "events": events}
                    try:
                        with patch.object(advisor.time, "monotonic", side_effect=lambda: now):
                            self.evaluate(inputs)
                            obsolete, now = cancelled, 0. if cancelled else 2.
                            with self.assertRaises(advisor._SearchStopped):
                                self.evaluate(inputs)
                    finally:
                        advisor.TABLES.reset(cache_token)
                        advisor._SEARCH.reset(search_token)


if __name__ == "__main__":
    unittest.main()
