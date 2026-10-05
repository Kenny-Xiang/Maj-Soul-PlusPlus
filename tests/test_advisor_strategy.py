"""Future decisions must purchase their wins and partition terminal mass."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import advisor
from advisor_policy import TABLES, Outcome, fold_table, ready_table
from test_advisor import state, tiles
from test_advisor_phase import quiet_state


class StrategyTests(unittest.TestCase):
    def test_remote_hand_can_choose_real_fold_instead_of_cheap_early_deal_in(self):
        s = quiet_state("147m147p147s12345z", 5)
        self.assertEqual(advisor.advise(s)["best"]["tile"], "4p")
        s["riichi"][1] = True
        s["scores"][1] -= 1000
        s["riichiSticks"] = 1
        c = advisor.advise(s)["best"]
        self.assertEqual(c["tile"], "1s")
        self.assertEqual(c["dealInProbability"], 0)
        self.assertEqual(c["futureFoldProbability"], 1)
        self.assertEqual(c["winProbability"], 0)
        self.assertNotIn("efficiencyReward", c["scoreBreakdown"])

    def test_dama_pays_for_future_discards_and_has_exclusive_endings(self):
        s = state("123m123p123s45s77z1z")
        s["riichi"][1] = True
        original = deepcopy(s)
        c = next(c for c in advisor.advise(s)["candidates"] if c["tile"] == "1z")
        self.assertGreater(c["futureDiscardDealInLoss"], 0)
        self.assertGreater(c["expectedOpponentTsumoLoss"], 0)
        self.assertAlmostEqual(sum(c["terminalProbabilities"].values()), 1)
        self.assertEqual(s, original)

    def test_draw_income_is_conditioned_on_surviving_and_actual_readiness(self):
        s = state("123m123p123s45s77z1z")
        s["left"] = 0
        s["riichi"][1:] = [True, True, True]
        c = next(c for c in advisor.advise(s)["candidates"] if c["tile"] == "1z")
        self.assertEqual(c["expectedDrawPayment"], 0)
        self.assertNotIn("lateTenpaiReward", c["scoreBreakdown"])

    def test_fold_sacrifices_win_income_and_tenpai_fee_in_the_same_branch(self):
        args = ((0, 1), 0, (.2, 1600.), [(.8, 0., .5, 4000.), (.2, 8000., 0., 0.)],
                [(0., 0.)], (.5, 4000.), 1., (0., 0.), (-1000., 1000.), 1.15)
        dama = ready_table(*args, False, lambda: None)[0]
        locked = ready_table(*args, True, lambda: None)[0]
        self.assertAlmostEqual(dama.fold, .8)
        self.assertEqual(dama.loss, 0)
        self.assertAlmostEqual(dama.win, .2)
        self.assertAlmostEqual(dama.draw_income, -800)
        self.assertGreater(locked.win, dama.win)
        self.assertGreater(locked.loss, dama.loss)
        self.assertEqual(locked.fold, 0)
        for outcome in (dama, locked):
            self.assertAlmostEqual(outcome.win + outcome.deal + outcome.tsumo + outcome.other + outcome.draw, 1)

    def test_fold_cannot_reuse_the_single_safe_physical_tile(self):
        result = fold_table((0, 0), 0, [(0., 0.)], (1., 8000.), 1., (0., 0.), -1000., lambda: None)[0][0]
        self.assertEqual(result.deal, 1)
        self.assertEqual(result.loss, 8000)
        self.assertEqual(result.draw_income, 0)

    def test_draw_fees_use_the_number_of_other_ready_players(self):
        for players, expectations in ((4, [(0, 3000), (-1000, 1500), (-1500, 1000), (-3000, 0)]),
                                      (3, [(0, 2000), (-1000, 1000), (-2000, 0)])):
            for ready, expected in enumerate(expectations):
                opponents = [{"tenpai": float(i < ready)} for i in range(players - 1)]
                self.assertEqual(advisor._draw_payments(opponents, players), expected)

    def test_exhausted_effective_tiles_do_not_waive_future_discard_risk(self):
        s = state("123456m78p12s55z1z")
        s["left"] = 4
        s["riichi"] = [False, True, True, True]
        s["rivers"][2] = [{"tile": tile} for tile in ("6p", "9p", "3s") for _ in range(4)]
        remaining = advisor.unseen_counts(s)
        opponents = advisor._opponents(s, remaining)
        outcome = advisor._one_shanten_outcome([], sum(remaining), opponents, (1, 2, 3, 0), s)
        self.assertGreater(outcome.loss, 0)
        self.assertGreater(outcome.deal, 0)
        self.assertEqual(outcome.win, 0)

    def test_policy_cache_is_decision_local_and_cancellation_restores_context(self):
        first = state("123m123p123s45s77z1z")
        second = deepcopy(first)
        second["riichi"][1] = True
        expected = advisor.advise(second)
        advisor.advise(first)
        self.assertEqual(advisor.advise(first, cancelled=lambda: True)["status"], "unavailable")
        actual = advisor.advise(second)
        expected.pop("elapsedMs")
        actual.pop("elapsedMs")
        self.assertEqual(actual, expected)
        self.assertIsNone(advisor._POLICY_RISKS.get())
        self.assertIsNone(TABLES.get())

    def test_cached_policy_matches_fresh_public_prices_and_safety(self):
        evaluate = advisor._advise

        def uncached(snapshot):
            risk = advisor._POLICY_RISKS.set(None)
            tables = TABLES.set(None)
            try:
                return evaluate(snapshot)
            finally:
                TABLES.reset(tables)
                advisor._POLICY_RISKS.reset(risk)

        for ready in (False, True):
            s = state("123m123p123s45s77z1z")
            s["left"] = 12
            s["riichi"][1] = ready
            s["riichiStep"][1] = 20 if ready else None
            s["rivers"][1] = [{"tile": "9p", "step": 20}]
            cached = advisor.advise(s)
            with patch.object(advisor, "_advise", side_effect=uncached):
                fresh = advisor.advise(s)
            for result in (cached, fresh):
                self.assertEqual(result["status"], "ready")
                result.pop("elapsedMs")
            self.assertEqual(cached, fresh)

    def test_coarse_progress_also_charges_ineffective_draws(self):
        s = state("147m147p147s12345z")
        remaining = advisor.unseen_counts(s)
        opponents = advisor._opponents(s, remaining)
        with patch.object(advisor, "_policy_risks", return_value=([], [], (.2, 1600.))), patch.object(
                advisor, "_policy_environment", return_value=(1., (0., 0.), (-1000., 1000.))):
            outcome = advisor._coarse_policy(s["hand"], s, remaining, opponents, (0, 0), 3, 10, 1000, 1)
        self.assertAlmostEqual(outcome.deal, .36)
        self.assertAlmostEqual(outcome.loss, 2880)
        self.assertEqual(outcome.win, 0)

    def test_risk_cache_counts_cover_sequences_orphans_and_tanki_denominator(self):
        sanma = state("123p123s789s45p77z4z", players=3)
        sanma["riichi"][1] = True
        four = state("123m123p123s45s77z1z")
        four["melds"][1] = [{"type": 1, "tiles": tiles(t)} for t in ("444m", "666m", "888p", "333z")]
        for s in (sanma, four):
            remaining = advisor.unseen_counts(s)
            opponents = advisor._opponents(s, remaining)
            token = advisor._POLICY_RISKS.set({})
            try:
                for drawn, count in enumerate(remaining):
                    if not count:
                        continue
                    after = list(remaining)
                    after[drawn] -= 1
                    for tile in advisor.TILES:
                        self.assertEqual(advisor._danger(tile, after, opponents),
                                         advisor._uncached_danger(tile, after, opponents))
            finally:
                advisor._POLICY_RISKS.reset(token)


if __name__ == "__main__":
    unittest.main()
