"""Source-backed three-player action labels and visible-state boundaries."""
from copy import deepcopy
import bz2
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_policy_mjai_review import riichienv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
FIXTURE = Path(__file__).parent / "fixtures" / "tenhou_sanma_actions.json"


@unittest.skipIf(riichienv is None, "install conversion dependencies for sanma checks")
class SanmaMjaiTests(unittest.TestCase):
    def setUp(self):
        self.games = json.loads(FIXTURE.read_text())["games"]

    def extract(self, game):
        from policy_mjai import extract_game
        return extract_game(game["events"], game["gameId"], match_metadata=game["matchMetadata"])

    def test_real_games_cover_calls_all_kan_types_kita_and_exact_masks(self):
        from policy_actions import action_key, legal_actions
        from policy_features import encode_state
        found, origins = set(), set()
        for game in self.games:
            samples, audit = self.extract(game)
            self.assertEqual(audit["ruleEngineGameMode"], "3p-red-half")
            self.assertEqual(audit["ruleEngineRules"], "tenhou")
            self.assertEqual(audit["excluded"].get("label_not_in_reconstructed_mask", 0), 0)
            for sample in samples:
                state = sample["state"]
                found.add(sample["action"]["action"])
                self.assertEqual(state["playerCount"], 3)
                self.assertEqual(len(state["scores"]), 3)
                self.assertEqual(len(state["rivers"]), 3)
                self.assertEqual(state["match"], {"playerCount": 3, "roundCount": 2,
                                                   "sourcePlatform": "tenhou"})
                self.assertIn(action_key(sample["action"]), {action_key(a) for a in legal_actions(state)})
                planes, scalars = encode_state(state)
                self.assertEqual(float(scalars[24]), 0.)  # absent fourth seat
                if sample["action"]["action"] == "kita":
                    origins.add(sample["action"]["moqie"])
                    self.assertEqual(sample["action"]["consumed"], ["4z"])
        self.assertTrue({"discard", "riichi", "pon", "ankan", "daiminkan", "shouminkan",
                         "kita", "ron", "pass"} <= found)
        self.assertNotIn("chi", found)
        self.assertEqual(origins, {False, True})

    def test_north_replacement_draws_reopen_decisions_and_consume_wall(self):
        samples, _ = self.extract(self.games[0])
        self.assertTrue(any(s["state"]["north"][s["seat"]] > 0 for s in samples))
        first = samples[0]["state"]
        self.assertEqual(first["left"], 54)
        self.assertEqual(first["lastAction"]["name"], "ActionNewRound")
        self.assertFalse(samples[0]["action"].get("moqie", False))

    def test_kita_replacement_supplies_rinshan_yaku_but_next_normal_draw_does_not(self):
        from policy_actions import legal_actions
        game = deepcopy(self.games[0])
        events = json.loads((FIXTURE.parent / "sanma_kita_rinshan.json").read_text())
        events[0]["_tenhou"] = game["events"][0]["_tenhou"]
        events[11]["_tenhou"] = {"tsumogiri": True}
        game["events"] = events + [{"type": "hora", "actor": 1, "target": 1},
                                   {"type": "end_kyoku"}, {"type": "end_game"}]
        won, _ = self.extract(game)
        win = next(s for s in won if s["state"]["lastStep"] == 12 and s["seat"] == 1)
        self.assertEqual(win["action"]["action"], "tsumo")
        self.assertIn("tsumo", {a["action"] for a in legal_actions(win["state"])})
        # The open terminal pon precludes tanyao; only the replacement draw
        # supplies a yaku. Passing it cannot grant rinshan to a later draw.
        game["events"] = events + [
            {"type": "dahai", "actor": 1, "pai": "9s", "tsumogiri": True},
            {"type": "tsumo", "actor": 2, "pai": "P"},
            {"type": "dahai", "actor": 2, "pai": "P", "tsumogiri": True},
            {"type": "tsumo", "actor": 0, "pai": "F"},
            {"type": "dahai", "actor": 0, "pai": "F", "tsumogiri": True},
            {"type": "tsumo", "actor": 1, "pai": "9s"},
            {"type": "dahai", "actor": 1, "pai": "9s", "tsumogiri": True},
            {"type": "ryukyoku", "deltas": [0, 0, 0]},
            {"type": "end_kyoku"}, {"type": "end_game"}]
        passed, audit = self.extract(game)
        normal = next(s for s in passed if s["state"]["lastStep"] == 18 and s["seat"] == 1)
        self.assertNotIn("tsumo", {a["action"] for a in legal_actions(normal["state"])})
        self.assertEqual(audit["excluded"].get("label_not_in_reconstructed_mask", 0), 0)

    def test_kita_without_physical_source_evidence_is_censored(self):
        game = deepcopy(self.games[0])
        baseline, _ = self.extract(game)
        count = 0
        for event in game["events"]:
            if event["type"] == "kita":
                event["_tenhou"].pop("tsumogiri")
                count += 1
        samples, audit = self.extract(game)
        self.assertFalse(any(s["action"]["action"] == "kita" for s in samples))
        self.assertGreater(audit["excluded"].get("unresolved_action", 0), 0)
        self.assertLess(len(samples), len(baseline))
        self.assertGreater(count, 0)

    def test_hidden_hands_names_and_future_scores_do_not_affect_first_window(self):
        game = deepcopy(self.games[0])
        baseline, _ = self.extract(game)
        first = next(s for s in baseline if s["state"]["lastStep"] == 2)
        game["events"][0]["names"] = ["hidden-a", "hidden-b", "hidden-c"]
        actor = first["seat"]
        others = [s for s in range(3) if s != actor]
        hands = game["events"][1]["tehais"]
        hands[others[0]], hands[others[1]] = hands[others[1]], hands[others[0]]
        game["events"] = game["events"][:4] + [
            {"type": "ryukyoku", "deltas": [12345, -23456, 11111]},
            {"type": "end_kyoku"}, {"type": "end_game", "scores": [-999, 888, 777]}]
        changed, _ = self.extract(game)
        self.assertEqual(first, next(s for s in changed if s["state"]["lastStep"] == 2))
        self.assertNotIn("_tenhou", json.dumps(first))
        self.assertNotIn("tehais", json.dumps(first))

    def test_source_metadata_and_player_count_are_required(self):
        from policy_mjai import extract_game
        game = self.games[0]
        with self.assertRaisesRegex(ValueError, "source-bound Tenhou"):
            extract_game(game["events"], game["gameId"])
        for name, value in (("goType", 177), ("modeId", 26), ("playerCount", 4)):
            broken = deepcopy(game)
            broken["matchMetadata"][name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.extract(broken)
        broken = deepcopy(game)
        broken["events"][0]["_tenhou"]["xml_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "header differs"):
            self.extract(broken)

    def test_tenhou_rule_preset_is_used_instead_of_mjsoul(self):
        from policy_mjai import RiichiEnv
        with patch("policy_mjai.RiichiEnv", wraps=RiichiEnv) as engine:
            self.extract(self.games[0])
        rule = engine.call_args.kwargs["rule"]
        self.assertFalse(rule.allows_ron_on_ankan_for_kokushi_musou)
        self.assertTrue(rule.sanchaho_is_draw)

    def test_original_xml_hash_header_ranks_and_disconnects_are_checked(self):
        import policy_convert_mjai as batch
        import xml.etree.ElementTree as ET
        game = deepcopy(self.games[0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pathofhouou-2016.db"
            database = sqlite3.connect(path)
            database.execute("CREATE TABLE logs (log_id TEXT PRIMARY KEY, log_content BLOB)")
            root = ET.Element("mjloggm", ver="2.3")
            ET.SubElement(root, "GO", game["events"][0]["_tenhou"]["GO"])
            users = ET.SubElement(root, "UN", game["events"][0]["_tenhou"]["UN"])

            def write_xml():
                data = ET.tostring(root)
                database.execute("INSERT OR REPLACE INTO logs VALUES (?, ?)",
                                 (game["gameId"], bz2.compress(data)))
                database.commit()
                metadata = deepcopy(game["matchMetadata"])
                metadata["provenance"].update(archive=str(path), xmlSha256=hashlib.sha256(data).hexdigest())
                return {"gameId": game["gameId"], "matchMetadata": metadata}

            row = write_xml()
            batch.verify_tenhou_xml(row, game["events"])
            row["matchMetadata"]["provenance"]["xmlSha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                batch.verify_tenhou_xml(row, game["events"])
            users.set("dan", "15,16,16,0")
            row = write_xml()
            changed = deepcopy(game["events"])
            changed[0]["_tenhou"]["UN"]["dan"] = users.get("dan")
            with self.assertRaisesRegex(ValueError, "7-dan"):
                batch.verify_tenhou_xml(row, changed)
            ET.SubElement(root, "BYE", who="1")
            row = write_xml()
            with self.assertRaisesRegex(ValueError, "disconnect BYE"):
                batch.verify_tenhou_xml(row, game["events"])
            database.close()


if __name__ == "__main__":
    unittest.main()
