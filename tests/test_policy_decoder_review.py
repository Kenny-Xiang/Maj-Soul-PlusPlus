"""Independent import/replay contract checks, including an opt-in cached real log.

No test downloads data. The whole-game check runs when policy_fetch's pinned
public source is cached locally; only small hand-authored fixtures are committed.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("policy_fetch_review", ROOT / "scripts/policy_fetch.py")
fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)
sys.path.insert(0, str(ROOT / "src"))
from policy_actions import action_key, legal_actions

NODE = shutil.which("node")
PUBLIC = ROOT / ".local/policy-data/four-player-210815.source.json"


@unittest.skipUnless(NODE, "Node.js is required by the shared live state core")
class DecoderReplayReviewTests(unittest.TestCase):
    def extract(self, game):
        command = "const r=require('./src/policy_replay.cjs');let x='';process.stdin.on('data',d=>x+=d);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(r.extractGame(JSON.parse(x)))));"
        proc = subprocess.run([NODE, "-e", command], cwd=ROOT, input=json.dumps(game),
                              text=True, capture_output=True, check=True)
        return json.loads(proc.stdout)

    def fixture(self):
        return json.loads((ROOT / "tests/fixtures/policy_replay_synthetic.json").read_text())

    def test_normalization_preserves_declined_response_before_accepted_call(self):
        fixture = self.fixture()
        fixture["records"][1]["data"]["operations"].append({"seat": 2, "operation_list": [{"type": 9}]})
        actions = []
        for index, record in enumerate(fixture["records"]):
            actions.append({"type": 1, "result": record})
            if index == 1:
                actions.extend([
                    {"type": 2, "user_input": {"seat": 2, "type": 3, "cpg": {"cancel_operation": True}}},
                    {"type": 3, "user_event": {"seat": 0, "type": 1}},
                    {"type": 2, "user_input": {"seat": 1, "type": 3, "cpg": {"type": 3}}},
                ])
        payload = {"head": {**fixture["head"], "uuid": "synthetic-import-window"},
                   "data": {"name": ".lq.GameDetailRecords", "data": {"version": 210715, "actions": actions}}}
        normalized = fetch.normalize(payload)
        result = self.extract(normalized)
        passes = [s for s in result["samples"] if s["action"]["action"] == "pass"]
        self.assertEqual([(s["seat"], s["labelSource"]) for s in passes], [(2, "explicit")])
        self.assertEqual(result["audit"]["excluded"], {})
        self.assertEqual(normalized["records"][1]["userInputs"][1]["cpg"], {"type": 3})

    def test_wall_count_zero_has_proto_default_after_last_draw(self):
        fixture = self.fixture()
        fixture["records"] = fixture["records"][:2]
        fixture["records"][1]["data"].pop("operations", None)
        fixture["records"].extend([
            {"name": "RecordDealTile", "data": {"seat": 1, "tile": "9s",
             "operation": {"seat": 1, "operation_list": [{"type": 1}]}}},
            {"name": "RecordDiscardTile", "data": {"seat": 1, "tile": "9s", "moqie": True}},
        ])
        result = self.extract(fixture)
        last = result["samples"][-1]
        self.assertEqual(last["state"]["left"], 0)
        self.assertEqual(last["action"]["tile"], "9s")

    def test_opponent_hidden_state_and_result_headers_do_not_change_earlier_sample(self):
        original = self.fixture()
        changed = copy.deepcopy(original)
        changed["head"]["accounts"] = [{"account_id": 99999, "nickname": "SECRET_ACCOUNT"}]
        changed["head"]["result"] = {"players": [{"seat": 0, "part_point_1": 99999}]}
        changed["records"][0]["data"]["paishan"] = "SECRET_WALL"
        changed["records"][0]["data"]["tiles2"].reverse()
        changed["records"][0]["data"]["tiles3"].reverse()
        changed["records"][0]["data"]["tingpai"] = [{"seat": 2, "tiles": ["SECRET_WAIT"]}]
        changed["records"][-1]["data"]["players"] = [{"hand": ["SECRET_HAND"]}]
        base, modified = self.extract(original), self.extract(changed)
        self.assertEqual(base["samples"][0], modified["samples"][0])
        self.assertEqual(base["samples"][1], modified["samples"][1])
        self.assertNotIn("SECRET", json.dumps(modified["samples"]))

    @unittest.skipUnless(PUBLIC.exists(), "Run policy_fetch --public-sample first for the real-game smoke")
    def test_cached_pinned_public_json_to_normalize_extract_legal_candidates(self):
        self.assertEqual(hashlib.sha256(PUBLIC.read_bytes()).hexdigest(),
                         fetch.PUBLIC_SAMPLES["four-player-210815"]["sha256"])
        with tempfile.TemporaryDirectory() as directory:
            normalized = Path(directory) / "normalized.json"
            samples = Path(directory) / "samples.jsonl"
            audit_file = Path(directory) / "audit.json"
            subprocess.run([sys.executable, str(ROOT / "scripts/policy_fetch.py"),
                            "--input", str(PUBLIC), "--output", str(normalized)],
                           cwd=ROOT, capture_output=True, text=True, check=True)
            subprocess.run([NODE, str(ROOT / "scripts/policy_extract.cjs"), str(normalized),
                            "--output", str(samples), "--audit", str(audit_file)],
                           cwd=ROOT, capture_output=True, text=True, check=True)
            records = json.loads(normalized.read_text())
            audit = json.loads(audit_file.read_text())
            rows = [json.loads(line) for line in samples.read_text().splitlines()]
        self.assertEqual((len(records["records"]), len(records["initialUserInputs"])), (828, 4))
        self.assertEqual(sum(len(r.get("userInputs", [])) for r in records["records"]), 534)
        self.assertEqual((audit["rounds"], audit["windows"], audit["emitted"]), (9, 489, 486))
        self.assertEqual(audit["excluded"], {"censored_response": 3, "missing_actor_operations": 17})
        self.assertEqual(audit["labels"], {"accepted": 2, "explicit": 484, "inferred_pass": 0})
        for row in rows:
            with self.subTest(decision=row["decisionId"]):
                choices = legal_actions(row["state"])
                self.assertEqual(sum(action_key(choice) == action_key(row["action"]) for choice in choices), 1)
                self.assertNotIn("userInputs", row["state"])
                self.assertNotIn("_passed", row["state"])
                self.assertNotIn("head", row["state"])


if __name__ == "__main__":
    unittest.main()
