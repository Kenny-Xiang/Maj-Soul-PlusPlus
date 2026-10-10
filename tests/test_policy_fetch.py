"""Offline regressions for replay ingestion; fixtures are synthetic."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "policy_fetch", Path(__file__).resolve().parents[1] / "scripts" / "policy_fetch.py")
fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)


def varint(value):
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    return bytes(out + bytes([value]))


def field(number, value):
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode()
    return varint((number << 3) | 2) + varint(len(value)) + value


def schema():
    def message(fields):
        return {"fields": {name: {"id": number, "type": kind, **extra}
                           for name, number, kind, extra in fields}}
    return {"nested": {"lq": {"nested": {
        "Wrapper": message([("name", 1, "string", {}), ("data", 2, "bytes", {})]),
        "GameDetailRecords": message([("records", 1, "bytes", {"rule": "repeated"}),
                                       ("version", 2, "uint32", {}),
                                       ("actions", 3, "GameAction", {"rule": "repeated"})]),
        "GameAction": message([("result", 3, "bytes", {}), ("user_input", 4, "GameUserInput", {})]),
        "GameUserInput": message([("seat", 1, "uint32", {}), ("cpg", 11, "GameChiPengGang", {})]),
        "GameChiPengGang": message([("cancel_operation", 3, "bool", {})]),
        "ResGameRecord": message([("data", 4, "bytes", {})]),
        "RecordNewRound": message([("ju", 1, "uint32", {}),
                                    ("scores", 2, "int32", {"rule": "repeated"})]),
    }}}}


class ReplayFetchTests(unittest.TestCase):
    def test_resultless_inputs_stay_in_previous_decision_window(self):
        payload = {"head": {"uuid": "synthetic"}, "data": {
            "name": ".lq.GameDetailRecords", "data": {"version": 210715, "actions": [
                {"user_input": {"seat": 0, "type": 7}},
                {"result": {"name": ".lq.RecordNewRound", "data": {"ju": 0}}},
                {"passed": 25, "user_input": {"seat": 0, "operation": {"tile": "1m"}}},
                {"user_input": {"seat": 1, "cpg": {"cancel_operation": True}}},
                {"result": {"name": ".lq.RecordDiscardTile", "data": {"tile": "1m"}}},
            ]}}}
        result = fetch.normalize(payload)
        self.assertEqual(result["gameId"], "synthetic")
        self.assertEqual(len(result["initialUserInputs"]), 1)
        self.assertEqual(len(result["records"][0]["userInputs"]), 2)
        self.assertTrue(result["records"][0]["userInputs"][1]["cpg"]["cancel_operation"])
        self.assertNotIn("userInputs", result["records"][1])
        self.assertEqual(result["records"][0]["userInputs"][0]["_passed"], 25)

    def test_legacy_base64_wrappers_packed_signed_scores_and_presence(self):
        decoder = fetch.SchemaDecoder(schema())
        # Omitted ju must stay absent; a negative int32 uses a 10-byte varint.
        body = field(2, varint(25000) + varint((1 << 64) - 1000))
        record = field(1, ".lq.RecordNewRound") + field(2, body)
        detail = field(1, record)
        wrapper = field(1, ".lq.GameDetailRecords") + field(2, detail)
        result = fetch.normalize({"head": {"uuid": "old"},
                                  "data": base64.b64encode(wrapper).decode()}, decoder)
        self.assertEqual(result["records"][0]["data"]["scores"], [25000, -1000])
        self.assertNotIn("ju", result["records"][0]["data"])
        self.assertNotIn("operations", result["records"][0]["data"])

    def test_unknown_fields_are_reported_and_malformed_bytes_rejected(self):
        decoder = fetch.SchemaDecoder(schema())
        self.assertEqual(decoder.decode("lq.RecordNewRound", field(99, 2)), {})
        self.assertEqual(decoder.unknown_fields, {"lq.RecordNewRound:99"})
        for data in (b"\x80", b"\x12\x05ab", b"\x00\x00"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                decoder.decode("lq.RecordNewRound", data)

    def test_binary_response_frame_keeps_resultless_input(self):
        decoder = fetch.SchemaDecoder(schema())
        record = field(1, ".lq.RecordNewRound") + field(2, field(1, 0))
        detail = field(2, 210715) + field(3, field(3, record))
        detail += field(3, field(4, field(1, 1) + field(11, field(3, 1))))
        wrapped = field(1, ".lq.GameDetailRecords") + field(2, detail)
        frame = b"\x03\x01\x00" + field(2, field(4, wrapped))
        payload = fetch.load_payload(frame, "ws-response", decoder)
        result = fetch.normalize(payload, decoder, "binary-test")
        self.assertEqual(result["records"][0]["data"]["ju"], 0)
        self.assertTrue(result["records"][0]["userInputs"][0]["cpg"]["cancel_operation"])

    def test_no_implicit_data_url_fetch(self):
        with patch.object(fetch, "download") as download, self.assertRaisesRegex(ValueError, "explicitly"):
            fetch.normalize({"data": "", "data_url": "https://example.com/private"})
        download.assert_not_called()

    def test_canonical_decoded_input_keeps_explicit_empty_operations(self):
        payload = {"gameId": "canonical", "head": {}, "records": [
            {"name": "RecordDealTile", "data": {"operations": []},
             "userInputs": [{"seat": 0, "operation": {"type": 11}}]},
        ]}
        result = fetch.normalize(payload)
        self.assertEqual(result["records"], payload["records"])

    def test_missing_game_id_and_unknown_version_rejected(self):
        with self.assertRaisesRegex(ValueError, "game UUID"):
            fetch.normalize([{"name": "RecordNewRound", "data": {}}])
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            fetch.normalize({"gameId": "future", "version": 999, "actions": []})
        with self.assertRaisesRegex(ValueError, "no result"):
            fetch.normalize({"gameId": "truncated", "version": 210715,
                             "actions": [{"type": 1}]})

    def test_cannot_override_known_game_id_and_break_grouping(self):
        payload = {"head": {"uuid": "one-real-game"}, "records": [{"name": "RecordNewRound", "data": {}}]}
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            fetch.normalize(payload, game_id="different-id-for-same-game")

    def test_local_header_can_supply_metadata_to_headless_input(self):
        with tempfile.TemporaryDirectory() as directory:
            inp, head, out = (Path(directory) / name for name in ("input.json", "head.json", "out.json"))
            inp.write_text(json.dumps([{"name": "RecordNewRound", "data": {}}]))
            head.write_text(json.dumps({"uuid": "headless-game", "config": {"category": 2}}))
            fetch.main(["--input", str(inp), "--head-json", str(head), "--output", str(out)])
            result = json.loads(out.read_text())
            self.assertEqual(result["gameId"], "headless-game")
            self.assertEqual(result["source"]["head"]["sha256"], fetch.sha256(head.read_bytes()))

    def test_cli_writes_provenance_without_network_for_decoded_json(self):
        payload = {"gameId": "local", "records": [{"name": "RecordNewRound", "data": {}}]}
        with tempfile.TemporaryDirectory() as directory:
            inp, out = Path(directory) / "in.json", Path(directory) / "out.json"
            inp.write_text(json.dumps(payload))
            with patch.object(fetch, "download") as download:
                fetch.main(["--input", str(inp), "--output", str(out)])
            download.assert_not_called()
            result = json.loads(out.read_text())
            self.assertEqual(result["source"]["sha256"], fetch.sha256(inp.read_bytes()))
            self.assertEqual(result["source"]["kind"], "local-user-input")

    def test_wrong_schema_hash_rejected_before_decoding(self):
        with tempfile.TemporaryDirectory() as directory:
            inp = Path(directory) / "schema.json"
            inp.write_text("{}")
            with self.assertRaises(SystemExit):
                fetch.main(["--input", str(inp), "--schema", str(inp),
                            "--output", str(Path(directory) / "out.json")])

    def test_explicit_data_url_must_match_response_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            inp = Path(directory) / "response.json"
            inp.write_text(json.dumps({"data_url": "https://example.com/actual"}))
            with patch.object(fetch, "download") as download, self.assertRaises(SystemExit):
                fetch.main(["--input", str(inp), "--data-url", "https://example.com/other",
                            "--output", str(Path(directory) / "out.json")])
            download.assert_not_called()

    def test_download_hash_checked_before_writing_public_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(fetch, "download", return_value=b"not-the-pinned-replay"), self.assertRaises(SystemExit):
                fetch.main(["--public-sample", "four-player-210815", "--cache-dir", directory,
                            "--output", str(Path(directory) / "out.json")])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_only_https_without_embedded_credentials(self):
        for url in ("file:///etc/passwd", "http://example.com/x", "https://name:secret@example.com"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                fetch.download(url)


if __name__ == "__main__":
    unittest.main()
