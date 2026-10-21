"""Synthetic tests and an optional cached official replay regression; no network."""
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import policy_official_archive as archive


GAME = "260101-11111111-2222-4333-8444-555555555555"
OTHER = "260102-aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
URL = "https://record-v2.maj-soul.com:5333/majsoul/game_record/11111111-2222-4333-8444-555555555555"


def varint(value):
    if value < 0:
        value &= (1 << 64) - 1
    output = bytearray()
    while value >= 128:
        output.append((value & 127) | 128)
        value >>= 7
    return bytes(output + bytes([value]))


def field(number, value):
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode()
    return varint((number << 3) | 2) + varint(len(value)) + value


def fixture_schema():
    def message(*fields):
        return {"fields": {name: {"id": number, "type": kind, **({"rule": "repeated"} if repeated else {})}
                           for name, number, kind, repeated in fields}}
    types = {
        "Wrapper": message(("name", 1, "string", False), ("data", 2, "bytes", False)),
        "Error": message(("code", 1, "uint32", False)),
        "ResGameRecord": message(("error", 1, "Error", False), ("head", 3, "RecordGame", False),
                                  ("data", 4, "bytes", False), ("data_url", 5, "string", False)),
        "RecordGame": message(("uuid", 1, "string", False), ("start_time", 2, "uint32", False),
                               ("end_time", 3, "uint32", False), ("config", 5, "GameConfig", False),
                               ("accounts", 11, "AccountInfo", True), ("result", 12, "GameEndResult", False)),
        "AccountInfo": message(("seat", 2, "uint32", False)),
        "GameConfig": message(("category", 1, "uint32", False), ("mode", 2, "GameMode", False),
                               ("meta", 3, "GameMetaData", False)),
        "GameMode": message(("mode", 1, "uint32", False)),
        "GameMetaData": message(("mode_id", 2, "uint32", False)),
        "GameEndResult": message(("players", 1, "PlayerResult", True)),
        "PlayerResult": message(("seat", 1, "uint32", False), ("part_point_1", 3, "int32", False)),
        "GameDetailRecords": message(("records", 1, "bytes", True), ("version", 2, "uint32", False),
                                     ("actions", 3, "GameAction", True)),
        "GameAction": message(("type", 2, "uint32", False), ("result", 3, "bytes", False),
                              ("game_event", 6, "uint32", False)),
        "RecordNewRound": message(("chang", 1, "uint32", False), ("ju", 2, "uint32", False),
            ("ben", 3, "uint32", False), ("scores", 5, "int32", True), ("liqibang", 6, "uint32", False),
            *((f"tiles{seat}", 7 + seat, "string", True) for seat in range(4))),
        "RecordDiscardTile": message(("seat", 1, "uint32", False), ("is_liqi", 3, "bool", False)),
        "RecordDealTile": message(("seat", 1, "uint32", False), ("liqi", 5, "LiQiSuccess", False)),
        "LiQiSuccess": message(("seat", 1, "uint32", False), ("score", 2, "int32", False),
                               ("liqibang", 3, "uint32", False), ("failed", 4, "bool", False)),
        "RecordHule": message(("hules", 1, "HuleInfo", True), ("scores", 5, "int32", True)),
        "HuleInfo": message(("seat", 4, "uint32", False)),
        "RecordNoTile": message(("players", 2, "NoTilePlayerInfo", True),
                                ("scores", 3, "NoTileScoreInfo", True), ("gameend", 4, "bool", False)),
        "NoTilePlayerInfo": message(),
        "NoTileScoreInfo": message(("old_scores", 2, "int32", True), ("delta_scores", 3, "int32", True)),
        "RecordLiuJu": message(("gameend", 2, "GameEnd", False)),
        "GameEnd": message(("scores", 1, "int32", True)),
    }
    return json.dumps({"nested": {"lq": {"nested": types}}}).encode()


def wrapper(name, body):
    return field(1, ".lq." + name) + field(2, body)


def replay_body(complete=True, missing_hand=False, final_scores=25000, final="RecordHule", gameend=True, modern=False,
                draw_scores=None):
    tiles = [f"{rank}{suit}" for suit in "mps" for rank in range(1, 10) for _ in range(4)]
    new_round = b"".join(field(5, 25000) for _ in range(4))
    offset = 0
    for seat in range(4):
        count = 14 if seat == 0 else 13
        if not (missing_hand and seat == 3):
            new_round += b"".join(field(7 + seat, tile) for tile in tiles[offset:offset + count])
        offset += count
    records = [wrapper("RecordNewRound", new_round)]
    if complete:
        if final == "RecordHule":
            result = field(1, field(4, 0)) + b"".join(field(5, final_scores) for _ in range(4))
        elif final == "RecordNoTile":
            result = b"".join(field(2, b"") for _ in range(4)) + field(4, int(gameend))
            for old, delta in ([([25000] * 4, [0] * 4)] if draw_scores is None else draw_scores):
                result += field(3, b"".join(field(2, score) for score in old) +
                                b"".join(field(3, score) for score in delta))
        else:
            result = field(2, b"".join(field(1, final_scores) for _ in range(4))) if gameend else b""
        records.append(wrapper(final, result))
    detail = (field(2, 210715) + b"".join(field(3, field(2, 1) + field(3, record)) for record in records)
              if modern else b"".join(field(1, record) for record in records))
    return wrapper("GameDetailRecords", detail)


def response(identifier=GAME, mode_id=16, body=None, data_url=None, accounts=4, end=200, result_scores=None):
    config = field(1, 2) + field(2, field(1, 1 if mode_id == 15 else 2)) + field(3, field(2, mode_id))
    head = field(1, identifier) + field(2, 100) + field(3, end) + field(5, config)
    head += b"".join(field(11, field(2, seat)) for seat in range(accounts))
    result = b"".join(field(1, field(1, seat) + field(3, score))
                      for seat, score in enumerate([25000] * 4 if result_scores is None else result_scores))
    head += field(12, result)
    return field(3, head) + (field(5, data_url) if data_url else field(4, replay_body() if body is None else body))


def riichi_draw_response(opening=(21600, 48600, 600, 29200), opening_pot=0,
                         successes=((0, 20600, 1),), old=(20600, 48600, 600, 29200),
                         delta=(1500, 1500, -1500, -1500), head=(22100, 51100, -900, 27700),
                         end_event=2, declared=True, failed=False):
    tiles = [f"{rank}{suit}" for suit in "mps" for rank in range(1, 10) for _ in range(4)]
    new_round = b"".join(field(5, score) for score in opening)
    if opening_pot is not None:
        new_round += field(6, opening_pot)
    offset = 0
    for seat in range(4):
        count = 14 if seat == 0 else 13
        new_round += b"".join(field(7 + seat, tile) for tile in tiles[offset:offset + count])
        offset += count
    records = [wrapper("RecordNewRound", new_round)]
    for seat, score, pot in successes:
        records.append(wrapper("RecordDiscardTile", field(1, seat) + field(3, int(declared))))
        paid = field(1, seat) + field(2, score) + field(3, pot) + field(4, int(failed))
        records.append(wrapper("RecordDealTile", field(1, (seat + 1) % 4) + field(5, paid)))
    settlement = b"".join(field(2, score) for score in old) + b"".join(field(3, score) for score in delta)
    records.append(wrapper("RecordNoTile", b"".join(field(2, b"") for _ in range(4)) +
                           field(3, settlement) + field(4, 0)))
    actions = b"".join(field(3, field(2, 1) + field(3, record)) for record in records)
    if end_event is not None:
        actions += field(3, field(2, 4) + field(6, end_event))
    return response(body=wrapper("GameDetailRecords", field(2, 210715) + actions), result_scores=head)


class OfficialArchiveTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.schema = fixture_schema()
        self.pin = patch.object(archive.fetch, "SCHEMA_SHA256", hashlib.sha256(self.schema).hexdigest())
        self.pin.start()
        self.addCleanup(self.pin.stop)

    def opened(self, name="archive"):
        return archive.OfficialArchive(self.root / name, self.schema)

    def test_original_response_body_header_and_schema_are_preserved_byte_exactly(self):
        store = self.opened()
        raw = response() + field(99, b"unknown-field-preserved")
        with patch.object(archive, "download_data_url") as download:
            result = store.add(raw, expected_uuid=GAME)
        download.assert_not_called()
        self.assertEqual(result["status"], "saved")
        self.assertEqual(store.count, 1)
        row = result["record"]
        for kind, expected in (("response", raw), ("data", replay_body())):
            descriptor = row["files"][kind]
            self.assertEqual((store.output / descriptor["path"]).read_bytes(), expected)
            self.assertEqual(descriptor["sha256"], hashlib.sha256(expected).hexdigest())
        head = json.loads((store.output / row["files"]["head"]["path"]).read_bytes())
        self.assertEqual(head["uuid"], GAME)
        self.assertEqual((store.output / "schema.liqi.json").read_bytes(), self.schema)
        self.assertEqual(row["roundCount"], 1)
        self.assertEqual(row["modeId"], 16)
        self.assertIn("lq.ResGameRecord:99", row["unknownFields"])
        resumed = self.opened()
        self.assertEqual(resumed.count, 1)
        self.assertEqual(resumed.add(raw)["status"], "duplicate")
        self.assertEqual(len(resumed.manifest.read_text().splitlines()), 1)

    def test_websocket_frame_and_throne_east_are_supported(self):
        store = self.opened()
        raw = b"\x03\x34\x12" + field(2, response(mode_id=15))
        row = store.add(raw, fmt="ws-response")["record"]
        self.assertEqual(row["modeId"], 15)
        self.assertEqual((store.output / row["files"]["response"]["path"]).read_bytes(), raw)
        self.assertEqual(self.opened().count, 1)

    def test_data_url_does_not_count_until_matching_raw_body_is_supplied(self):
        store = self.opened()
        raw = response(data_url=URL)
        with patch.object(archive, "download_data_url") as download:
            for options in ({}, {"data_url_body": replay_body(), "body_url": URL + "?different=1"}):
                with self.assertRaisesRegex(ValueError, "matching original body"):
                    store.add(raw, **options)
                self.assertEqual(store.count, 0)
            result = store.add(raw, data_url_body=replay_body(), body_url=URL)
        download.assert_not_called()
        row = result["record"]
        self.assertEqual(row["dataSource"], "data_url")
        self.assertEqual((store.output / row["files"]["response"]["path"]).read_bytes(), raw)
        self.assertEqual((store.output / row["files"]["data"]["path"]).read_bytes(), replay_body())
        self.assertEqual(self.opened().count, 1)

    def test_wrong_room_incomplete_game_headless_and_uuid_mismatch_never_count(self):
        store = self.opened()
        invalid = [response(mode_id=12), response(mode_id=25), response(accounts=3), response(end=0),
                   response(body=replay_body(False)), response(body=replay_body(missing_hand=True)),
                   response(body=replay_body(final_scores=26000)), field(4, replay_body()),
                   response(body=wrapper("GameDetailRecords", b""))]
        for raw in invalid:
            with self.subTest(raw=raw[:10]), self.assertRaises(ValueError):
                store.add(raw)
            self.assertEqual(store.count, 0)
        with self.assertRaisesRegex(ValueError, "requested UUID"):
            store.add(response(), expected_uuid=OTHER)
        with self.assertRaisesRegex(ValueError, "complete ResGameRecord"):
            store.add(replay_body(), fmt="wrapper")
        self.assertFalse(store.manifest.exists())

    def test_duplicate_body_under_another_uuid_is_rejected(self):
        store = self.opened()
        store.add(response())
        with self.assertRaisesRegex(ValueError, "different game UUID"):
            store.add(response(identifier=OTHER))
        with self.assertRaisesRegex(ValueError, "Same game UUID"):
            store.add(response(body=replay_body() + field(99, b"different-body")))
        self.assertEqual(store.count, 1)

    def test_modern_actions_and_schema_specific_draw_or_abort_endings(self):
        for index, final in enumerate(("RecordHule", "RecordNoTile", "RecordLiuJu")):
            with self.subTest(final=final):
                store = self.opened(f"ending-{index}")
                if final == "RecordLiuJu":
                    with self.assertRaisesRegex(ValueError, "Final"):
                        store.add(response(body=replay_body(final=final, gameend=False, modern=True)))
                result = store.add(response(body=replay_body(final=final, modern=True)))
                self.assertEqual(result["record"]["recordCount"], 2)
                self.assertEqual(result["record"]["recordTypes"][final], 1)
                self.assertEqual(self.opened(f"ending-{index}").count, 1)

    def test_final_draw_can_have_false_gameend_but_must_match_header_scores(self):
        store = self.opened()
        result = store.add(response(body=replay_body(final="RecordNoTile", gameend=False, modern=True)))
        self.assertEqual(result["record"]["recordTypes"]["RecordNoTile"], 1)
        self.assertIn("equals header result", result["record"]["finalDrawScoreValidation"])
        self.assertEqual(self.opened().count, 1)

    def test_final_draw_missing_malformed_multiple_or_mismatched_scores_never_count(self):
        store = self.opened()
        valid = ([25000] * 4, [0] * 4)
        invalid = [[], [([], [0] * 4)], [([25000] * 4, [])],
                   [([25000] * 3, [0] * 4)], [([25000] * 4, [0] * 3)],
                   [valid, valid], [([25000] * 4, [1500, 1500, -1500, -1500])]]
        for scores in invalid:
            for marker in (False, True):
                with self.subTest(scores=scores, gameend=marker), self.assertRaisesRegex(ValueError, "Final drawn"):
                    store.add(response(body=replay_body(final="RecordNoTile", gameend=marker, draw_scores=scores)))
                self.assertEqual(store.count, 0)

    def test_final_draw_recorded_riichi_pool_is_awarded_only_to_the_sole_leader(self):
        store = self.opened()
        raw = riichi_draw_response()
        row = store.add(raw)["record"]
        evidence = row["finalDrawRiichiEvidence"]
        self.assertEqual(evidence["awardPoints"], 1000)
        self.assertEqual(evidence["recipientSeat"], 1)
        self.assertEqual(evidence["successfulRiichi"], [{"sourceActionIndex": 2, "seat": 0, "score": 20600, "liqibang": 1}])
        self.assertEqual((store.output / row["files"]["response"]["path"]).read_bytes(), raw)
        self.assertEqual(self.opened().games[GAME], row)

    def test_final_draw_checks_every_deposit_and_retains_recorded_opening_pool(self):
        row = self.opened().add(riichi_draw_response(
            opening=(20600, 47600, 600, 29200), opening_pot=2,
            successes=((0, 19600, 3), (1, 46600, 4)), old=(19600, 46600, 600, 29200),
            head=(21100, 52100, -900, 27700)))["record"]
        evidence = row["finalDrawRiichiEvidence"]
        self.assertEqual(evidence["openingRiichiSticks"], 2)
        self.assertEqual(len(evidence["successfulRiichi"]), 2)
        self.assertEqual(evidence["remainingRiichiSticks"], 4)
        self.assertEqual(evidence["awardPoints"], 4000)

    def test_final_draw_unsupported_allocations_or_missing_ledger_evidence_never_count(self):
        store = self.opened()
        invalid = [
            {"head": (22100, 52100, -900, 27700)},
            {"head": (23100, 50100, -900, 27700)},
            {"head": (22600, 50600, -900, 27700)},
            {"opening": (49600, 48600, 600, 1200), "successes": ((0, 48600, 1),),
             "old": (48600, 48600, 600, 1200), "head": (50100, 51100, -900, -300)},
            {"end_event": None}, {"end_event": 1}, {"successes": ()}, {"opening_pot": None},
            {"successes": ((0, 20500, 1),)}, {"successes": ((0, 20600, 2),)},
            {"successes": ((0, 20600, 1), (0, 19600, 2))}, {"declared": False}, {"failed": True},
            {"old": (20700, 48600, 600, 29200)}, {"delta": (1600, 1500, -1500, -1500)}]
        for options in invalid:
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "Final drawn"):
                store.add(riichi_draw_response(**options))
            self.assertEqual(store.count, 0)

    def test_interrupted_file_write_and_partial_manifest_never_count_as_complete(self):
        store = self.opened()
        real_write = store._write_exact

        def interrupted(path, data):
            if path.name == "data.wrapper.pb":
                raise OSError("synthetic interruption")
            real_write(path, data)

        with patch.object(store, "_write_exact", side_effect=interrupted), self.assertRaises(OSError):
            store.add(response())
        self.assertEqual(store.count, 0)
        self.assertFalse(store.manifest.exists())
        self.assertEqual(store.add(response())["uniqueGames"], 1)
        with store.manifest.open("ab") as handle:
            handle.write(b'{"gameId":')
        with self.assertRaisesRegex(ValueError, "manifest line 2 is incomplete or malformed"):
            self.opened()

    def test_resume_rejects_corrupted_bytes_counts_paths_and_duplicate_rows(self):
        store = self.opened()
        row = store.add(response())["record"]
        original = archive.encoded_json(row)
        data_path = store.output / row["files"]["data"]["path"]
        data_path.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.opened()
        data_path.write_bytes(replay_body())
        for change in (lambda value: value.update(recordCount=999),
                       lambda value: value["files"]["head"].update(path="../outside.json")):
            changed = json.loads(original)
            change(changed)
            store.manifest.write_bytes(archive.encoded_json(changed))
            with self.assertRaises(ValueError):
                self.opened()
        store.manifest.write_bytes(original * 2)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.opened()

    def test_authentication_errors_stop_collection_and_schema_pin_is_required(self):
        store = self.opened()
        with self.assertRaisesRegex(archive.StopCollection, "1004"):
            store.add(field(1, field(1, 1004)))
        self.assertEqual(store.count, 0)
        with self.assertRaisesRegex(ValueError, "pinned"):
            archive.OfficialArchive(self.root / "wrong-schema", b"{}")

    def test_untrusted_data_urls_are_rejected_before_network_without_query_leaks(self):
        urls = ["http://record-v2.maj-soul.com:5333/majsoul/game_record/x",
                "https://record-v2.maj-soul.com/majsoul/game_record/x",
                "https://record-v2.maj-soul.com.evil.test:5333/majsoul/game_record/x?secret=TOKEN",
                "https://user:password@record-v2.maj-soul.com:5333/majsoul/game_record/x",
                "https://record-v2.maj-soul.com:5333/account/login"]
        with patch.object(archive.urllib.request, "build_opener") as opener:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(ValueError) as raised:
                    archive.download_data_url(url)
                self.assertNotIn("TOKEN", str(raised.exception))
                self.assertNotIn("password", str(raised.exception))
        opener.assert_not_called()

    def test_mocked_http_size_rate_authentication_and_redirect_controls(self):
        fake = MagicMock()
        fake.getcode.return_value = 200
        fake.read.return_value = b"original-body"
        fake.__enter__.return_value = fake
        opener = MagicMock()
        opener.open.return_value = fake
        with patch.object(archive.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(archive.download_data_url(URL), b"original-body")
            fake.read.assert_called_with(archive.MAX_BYTES + 1)
            with patch.object(archive, "MAX_BYTES", 3), self.assertRaisesRegex(ValueError, "limit"):
                archive.download_data_url(URL)
            for status in (401, 403, 429):
                opener.open.side_effect = urllib.error.HTTPError(URL, status, "stop", {}, io.BytesIO())
                with self.subTest(status=status), self.assertRaises(archive.StopCollection):
                    archive.download_data_url(URL)
        with self.assertRaisesRegex(ValueError, "Redirect refused"):
            archive.fetch.NoRedirect().redirect_request(None, None, 302, "moved", {}, "https://evil.test")


class CachedOfficialReplayTests(unittest.TestCase):
    def test_actual_final_draw_riichi_pool_is_preserved_and_restored(self):
        root = Path(__file__).resolve().parents[1]
        source = root / ".local/policy-official/bridge-spool/edad164bd84a14e40cefdd9909a195b8.ndjson"
        schema = root / ".local/policy-data/liqi-0.11.243.w.json"
        if not source.exists() or not schema.exists():
            self.skipTest("Optional locally cached official riichi-pool replay is unavailable")
        item = json.loads(source.read_bytes().splitlines()[15])
        raw = base64.b64decode(item["wsResponseBase64"], validate=True)
        self.assertEqual(archive.digest(raw), "c36677ae41d47ff36554da1acd50432e484194c9dc923751bfe9ad42c02cb961")
        with tempfile.TemporaryDirectory() as folder:
            store = archive.OfficialArchive(folder, schema.read_bytes())
            row = store.add(raw, fmt="ws-response", expected_uuid=item["gameId"])["record"]
            evidence = row["finalDrawRiichiEvidence"]
            self.assertEqual((evidence["recipientSeat"], evidence["awardPoints"], evidence["endActionIndex"]), (1, 1000, 2078))
            self.assertEqual(evidence["successfulRiichi"], [{"sourceActionIndex": 2030, "seat": 0, "score": 20600, "liqibang": 1}])
            self.assertEqual(row["unknownFields"], [])
            self.assertEqual((store.output / row["files"]["response"]["path"]).read_bytes(), raw)
            self.assertEqual(archive.OfficialArchive(folder, schema.read_bytes()).games[item["gameId"]], row)

    def test_existing_official_archive_metadata_remains_restore_compatible(self):
        source = Path(__file__).resolve().parents[1] / ".local/policy-official/archive"
        if not (source / "manifest.jsonl").exists():
            self.skipTest("Optional existing official archive is unavailable")
        original = {row["gameId"]: row for row in map(json.loads, (source / "manifest.jsonl").read_text().splitlines())}
        with tempfile.TemporaryDirectory() as folder:
            copied = Path(folder) / "archive"
            shutil.copytree(source, copied)
            resumed = archive.OfficialArchive(copied, (copied / "schema.liqi.json").read_bytes())
            self.assertEqual(resumed.games, original)

    def test_actual_final_draw_with_false_gameend_is_preserved_and_restored(self):
        root = Path(__file__).resolve().parents[1]
        batch = root / ".local/policy-official/batches/majsoul-official-1791647044634-3.ndjson"
        schema = root / ".local/policy-data/liqi-0.11.243.w.json"
        if not batch.exists() or not schema.exists():
            self.skipTest("Optional locally cached official probe is unavailable")
        identifier = "260101-02013eef-db4a-4040-834c-d887aeb23722"
        item = next(json.loads(line) for line in batch.read_bytes().splitlines()
                    if json.loads(line).get("gameId") == identifier)
        raw = base64.b64decode(item["wsResponseBase64"], validate=True)
        self.assertEqual(archive.digest(raw), "dd297e854454d1145291c28732c190e39bb74356f5981c3348b6addf162cefba")
        with tempfile.TemporaryDirectory() as folder:
            store = archive.OfficialArchive(folder, schema.read_bytes())
            payload = archive.fetch.load_payload(raw, "ws-response", store.decoder)
            normalized = archive.fetch.normalize(payload, store.decoder, identifier)
            final = normalized["records"][-1]
            self.assertEqual(final["name"], "RecordNoTile")
            self.assertIs(final["data"]["gameend"], False)
            self.assertEqual(final["data"]["scores"], [{
                "old_scores": [6500, 43900, 21700, 27900],
                "delta_scores": [1500, 1500, -1500, -1500]}])
            row = store.add(raw, fmt="ws-response", expected_uuid=identifier)["record"]
            self.assertEqual(row["roundCount"], 11)
            self.assertEqual(row["recordCount"], 1015)
            self.assertEqual((store.output / row["files"]["response"]["path"]).read_bytes(), raw)
            self.assertEqual((store.output / row["files"]["data"]["path"]).read_bytes(), payload["data"])
            self.assertEqual(archive.OfficialArchive(folder, schema.read_bytes()).count, 1)


if __name__ == "__main__":
    unittest.main()
