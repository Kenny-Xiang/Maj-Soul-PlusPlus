"""Offline bridge HTTP-handler and real synthetic archive tests; no server is started."""
from email.message import Message
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import policy_official_bridge as bridge
from test_policy_official_archive import GAME, OTHER, URL, field, fixture_schema, replay_body, response
from test_policy_official_batch import exported


class Request(bridge.BridgeHandler):
    def __init__(self, state, path, body=b"", headers=None):
        self.server = SimpleNamespace(bridge=state)
        self.path, self.rfile, self.wfile = path, io.BytesIO(body), io.BytesIO()
        self.headers = Message()
        for key, value in {"Origin": bridge.ORIGIN, "Authorization": "Bearer " + state.capability,
                           **(headers or {})}.items():
            self.headers[key] = value
        self.code, self.response_headers = None, {}

    def send_response(self, code):
        self.code = code

    def send_header(self, key, value):
        self.response_headers[key] = value

    def end_headers(self):
        pass

    def result(self):
        return json.loads(self.wfile.getvalue())


def game_line(identifier=GAME, **options):
    body = replay_body() + field(99, identifier)
    raw = b"\x03\x01\x00" + field(2, response(identifier=identifier, body=body, **options))
    return exported(raw, identifier=identifier, clientVersion="WebGL_2022-0.16.283")


class OfficialBridgeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.queue = self.root / "queue.txt"
        self.queue.write_text(GAME + "\n" + OTHER + "\n")
        self.schema = self.root / "schema.json"
        self.schema.write_bytes(fixture_schema())
        for name, target, value in (("SCHEMA_SHA256", bridge.batch.archive.fetch, hashlib.sha256(self.schema.read_bytes()).hexdigest()),
                                    ("QUEUE_SHA256", bridge, hashlib.sha256(self.queue.read_bytes()).hexdigest())):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.state = self.opened()

    def opened(self):
        return bridge.ArchiveBridge(self.queue, self.schema, self.root / "archive", self.root / "spool", self.root / "status.json")

    def post(self, data, collector_error="", state=None):
        state = state or self.state
        active = state.next_batch()
        request = Request(state, "/batch", data, {"Content-Type": "application/x-ndjson",
            "Content-Length": str(len(data)), "X-Batch-Id": active["batchId"], "X-Collector-Error": collector_error})
        request.do_POST()
        return request

    def test_complete_batch_spools_original_first_then_acks_real_durable_files(self):
        raw = game_line() + game_line(OTHER)
        original = bridge.batch.ingest
        def checked(stream, store, fetch_data_urls):
            files = list((self.root / "spool").glob("*.ndjson"))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].read_bytes(), raw)
            self.assertTrue(fetch_data_urls)
            return original(stream, store, fetch_data_urls)
        with patch.object(bridge.batch, "ingest", side_effect=checked):
            request = self.post(raw)
        result = request.result()
        self.assertEqual(request.code, 200)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["durableGameIds"], [GAME, OTHER])
        self.assertEqual(result["uniqueGames"], 2)
        self.assertEqual(result["spoolSha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.opened().store.count, 2)
        status = json.loads((self.root / "status.json").read_text())
        self.assertEqual(status["uniqueGames"], 2)
        self.assertIn("updatedAt", status)
        self.assertNotIn(self.state.capability, json.dumps(status))
        self.assertNotIn("wsResponseBase64", json.dumps(status))

    def test_partial_prefix_acks_saved_game_and_never_advances_after_collector_stop(self):
        request = self.post(game_line(), "Official socket closed")
        result = request.result()
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["durableGameIds"], [GAME])
        self.assertEqual(result["uniqueGames"], 1)
        self.assertEqual(self.state.next_batch()["gameIds"], [])
        self.assertIsNotNone(self.state.pending)

    def test_partial_prefix_without_error_also_latches_stop(self):
        result = self.post(game_line()).result()
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["durableGameIds"], [GAME])
        self.assertIn("Incomplete batch", result["error"])

    def test_server_error_and_malformed_suffix_keep_only_preceding_durable_ids(self):
        error_frame = b"\x03\x02\x00" + field(2, field(1, field(1, 1004)))
        suffix = exported(error_frame, identifier=OTHER, serverCode=1004)
        result = self.post(game_line() + suffix).result()
        self.assertEqual(result["durableGameIds"], [GAME])
        self.assertEqual(result["status"], "stopped")
        self.assertIn("1004", result["error"])
        self.assertEqual(self.opened().store.count, 1)
        resumed = self.opened()
        result = self.post(b"{broken\n", state=resumed).result()
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["durableGameIds"], [])

    def test_wrong_queue_order_is_never_archived(self):
        result = self.post(game_line(OTHER)).result()
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["durableGameIds"], [])
        self.assertEqual(self.state.store.count, 0)

    def test_data_url_failure_stops_without_retry_or_ack(self):
        raw = b"\x03\x01\x00" + field(2, response(data_url=URL))
        with patch.object(bridge.batch.archive, "download_data_url", side_effect=ValueError("HTTP 429")) as download:
            result = self.post(exported(raw)).result()
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["durableGameIds"], [])
        download.assert_called_once_with(URL)

    def test_target_uses_durable_count_and_resume_skips_only_verified_games(self):
        with patch.object(bridge, "TARGET_GAMES", 1):
            self.assertEqual(self.state.next_batch()["gameIds"], [GAME])
            result = self.post(game_line()).result()
            self.assertEqual(result["status"], "complete")
            self.assertEqual(self.state.next_batch()["gameIds"], [])
        resumed = self.opened()
        self.assertNotEqual(resumed.capability, self.state.capability)
        self.assertEqual(len(resumed.capability), 64)
        self.assertEqual(resumed.next_batch()["gameIds"], [OTHER])
        row = resumed.store.games[GAME]
        (resumed.store.output / row["files"]["data"]["path"]).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.opened()

    def test_fixed_queue_hash_and_fifty_game_batch_limit(self):
        self.queue.write_text(self.queue.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.opened()
        ids = [f"260101-{number:08x}-2222-4333-8444-555555555555" for number in range(51)]
        self.queue.write_text("\n".join(ids) + "\n")
        with patch.object(bridge, "QUEUE_SHA256", hashlib.sha256(self.queue.read_bytes()).hexdigest()):
            state = self.opened()
            first = state.next_batch()
            self.assertEqual(len(first["gameIds"]), 50)
            self.assertEqual(state.next_batch()["batchId"], first["batchId"])

    def test_fixed_origin_capability_and_standard_private_network_preflight(self):
        request = Request(self.state, "/batch", headers={"Authorization": "", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type, x-batch-id, x-collector-error",
            "Access-Control-Request-Private-Network": "true"})
        request.do_OPTIONS()
        self.assertEqual(request.code, 200)
        self.assertEqual(request.response_headers["Access-Control-Allow-Origin"], bridge.ORIGIN)
        self.assertEqual(request.response_headers["Access-Control-Allow-Private-Network"], "true")
        self.assertNotIn("Access-Control-Allow-Credentials", request.response_headers)
        self.assertFalse(self.state.error)
        for headers in ({"Origin": "https://evil.example"}, {"Origin": "null"}, {"Authorization": "bad"}, {"Authorization": "Bearer 雀魂"}):
            request = Request(self.state, "/next", headers=headers)
            request.do_GET()
            self.assertEqual(request.code, 403)
            self.assertEqual(request.result()["durableGameIds"], [])
        self.assertEqual(self.state.status()["status"], "stopped")

    def test_oversized_truncated_and_timeout_uploads_stop_without_ack(self):
        active = self.state.next_batch()
        request = Request(self.state, "/batch", b"x", {"Content-Type": "application/x-ndjson",
            "Content-Length": str(bridge.MAX_POST_BYTES + 1), "X-Batch-Id": active["batchId"]})
        request.do_POST()
        self.assertEqual(request.code, 400)
        self.assertFalse(list((self.root / "spool").iterdir()))
        for timeout in (False, True):
            state = self.opened()
            active = state.next_batch()
            request = Request(state, "/batch", b"partial", {"Content-Type": "application/x-ndjson",
                "Content-Length": "100", "X-Batch-Id": active["batchId"]})
            if timeout:
                class TimedOut:
                    def read(self, _):
                        raise TimeoutError("synthetic upload timeout")
                request.rfile = TimedOut()
            request.do_POST()
            self.assertEqual(request.code, 400)
            self.assertEqual(request.result()["durableGameIds"], [])
            self.assertEqual(state.store.count, 0)
            self.assertTrue((self.root / "spool" / (active["batchId"] + ".ndjson.part")).exists())
            self.assertEqual(state.status()["status"], "stopped")
        self.assertEqual(bridge.BridgeHandler.timeout, 60)

    def test_spool_fsync_failure_never_calls_ingest(self):
        self.state.next_batch()
        with patch.object(bridge.os, "fsync", side_effect=OSError("synthetic fsync failure")), \
                patch.object(bridge.batch, "ingest") as ingest:
            result = self.post(game_line()).result()
        ingest.assert_not_called()
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["durableGameIds"], [])


if __name__ == "__main__":
    unittest.main()
