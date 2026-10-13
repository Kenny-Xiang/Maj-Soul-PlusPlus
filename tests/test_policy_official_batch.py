"""Synthetic collector-envelope tests; no credentials or network access."""
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import policy_official_batch as batch
from test_policy_official_archive import GAME, OTHER, URL, field, fixture_schema, replay_body, response


def exported(raw=None, identifier=GAME, **changes):
    raw = b"\x03\x01\x00" + field(2, response()) if raw is None else raw
    item = {"gameId": identifier, "clientVersion": "web-0.11.243", "serverCode": 0,
            "responseBytes": len(raw), "wsResponseBase64": base64.b64encode(raw).decode()}
    item.update(changes)
    return json.dumps(item).encode() + b"\n"


class OfficialBatchTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.schema = fixture_schema()
        self.pin = patch.object(batch.archive.fetch, "SCHEMA_SHA256", hashlib.sha256(self.schema).hexdigest())
        self.pin.start()
        self.addCleanup(self.pin.stop)
        self.store = batch.archive.OfficialArchive(self.root, self.schema)

    def test_inline_original_is_saved_and_acknowledged_after_archive_add(self):
        line = exported()
        with patch.object(batch.archive, "download_data_url") as download:
            result = batch.ingest(io.BytesIO(line), self.store)
        download.assert_not_called()
        self.assertEqual(result["durableGameIds"], [GAME])
        self.assertEqual(result["savedGames"], 1)
        self.assertEqual(result["uniqueGames"], 1)
        expected = base64.b64decode(json.loads(line)["wsResponseBase64"])
        self.assertEqual((self.root / f"games/{GAME}/response.bin").read_bytes(), expected)

    def test_observed_official_webgl_version_and_legacy_web_are_accepted_exactly(self):
        for version in ("WebGL_2022-0.16.283", "web-0.11.252"):
            with self.subTest(version=version):
                item, _ = batch.decode_item(exported(clientVersion=version))
                self.assertEqual(item["clientVersion"], version)
        for version in ("WebGL_2021-0.16.283", "WebGL_2022-0.16", "WebGL_2022-0.16.283.R4.0.47",
                        "WebGL_2022-0.16.283\n", " WebGL_2022-0.16.283", "4.0.47", None, 123):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "client version"):
                batch.decode_item(exported(clientVersion=version))

    def test_resume_verifies_files_and_deduplicates_durable_uuids(self):
        batch.ingest(io.BytesIO(exported()), self.store)
        resumed = batch.archive.OfficialArchive(self.root, self.schema)
        result = batch.ingest(io.BytesIO(exported() * 2), resumed)
        self.assertEqual(result["durableGameIds"], [GAME])
        self.assertEqual(result["duplicateGames"], 2)
        self.assertEqual(result["uniqueGames"], 1)
        (self.root / f"games/{GAME}/data.wrapper.pb").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "integrity"):
            batch.archive.OfficialArchive(self.root, self.schema)

    def test_external_body_requires_explicit_fetch_and_uses_original_bytes(self):
        raw = b"\x03\x01\x00" + field(2, response(data_url=URL))
        line = exported(raw)
        with patch.object(batch.archive, "download_data_url", return_value=replay_body()) as download:
            refused = batch.ingest(io.BytesIO(line), self.store)
            self.assertEqual(refused["status"], "stopped")
            download.assert_not_called()
            result = batch.ingest(io.BytesIO(line), self.store, True)
            download.assert_called_once_with(URL)
        self.assertEqual(result["durableGameIds"], [GAME])
        self.assertEqual((self.root / f"games/{GAME}/data.wrapper.pb").read_bytes(), replay_body())
        resumed = batch.archive.OfficialArchive(self.root, self.schema)
        with patch.object(batch.archive, "download_data_url") as download:
            duplicate = batch.ingest(io.BytesIO(line), resumed, True)
        download.assert_not_called()
        self.assertEqual(duplicate["duplicateGames"], 1)

    def test_envelope_errors_never_acknowledge_or_download(self):
        changes = [{"gameId": "bad"}, {"clientVersion": ""}, {"responseBytes": True},
                   {"responseBytes": 1}, {"responseBytes": 100}, {"serverCode": True},
                   {"serverCode": -1}, {"wsResponseBase64": "%%%"}, {"wsResponseBase64": "AwE=\n"},
                   {"serverCode": 1004}]
        with patch.object(batch.archive, "download_data_url") as download:
            for change in changes:
                with self.subTest(change=change):
                    result = batch.ingest(io.BytesIO(exported(**change)), self.store, True)
                    self.assertEqual(result["status"], "stopped")
                    self.assertEqual(result["durableGameIds"], [])
            for line in (b"{}\n", b"null\n", b"[]\n", b"\n", b"{bad\n"):
                self.assertEqual(batch.ingest(io.BytesIO(line), self.store)["status"], "stopped")
        download.assert_not_called()

    def test_authentication_error_stops_before_subsequent_rows(self):
        raw = b"\x03\x01\x00" + field(2, field(1, field(1, 1004)))
        result = batch.ingest(io.BytesIO(exported(raw, serverCode=1004) + exported()), self.store, True)
        self.assertEqual(result["failedLine"], 1)
        self.assertEqual(result["durableGameIds"], [])
        self.assertIn("1004", result["error"])
        self.assertEqual(self.store.count, 0)

    def test_partial_batch_only_acknowledges_preceding_complete_games(self):
        result = batch.ingest(io.BytesIO(exported() + b"{bad\n" + exported()), self.store)
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["failedLine"], 2)
        self.assertEqual(result["durableGameIds"], [GAME])
        self.assertEqual(result["processedResponses"], 1)

    def test_http_failures_are_not_retried_or_acknowledged(self):
        raw = b"\x03\x01\x00" + field(2, response(data_url=URL))
        errors = [urllib.error.URLError("connection failed"), ValueError("HTTP 500"),
                  batch.archive.StopCollection("HTTP 429")]
        for error in errors:
            with self.subTest(error=error), patch.object(batch.archive, "download_data_url", side_effect=error) as download:
                result = batch.ingest(io.BytesIO(exported(raw) * 2), self.store, True)
                self.assertEqual(result["status"], "stopped")
                self.assertEqual(result["durableGameIds"], [])
                download.assert_called_once_with(URL)

    def test_foreign_url_and_mismatched_uuid_never_reach_download(self):
        for payload in (response(data_url="https://evil.test/body"), response(identifier=OTHER, data_url=URL)):
            raw = b"\x03\x01\x00" + field(2, payload)
            with patch.object(batch.archive, "download_data_url") as download:
                result = batch.ingest(io.BytesIO(exported(raw)), self.store, True)
                self.assertEqual(result["status"], "stopped")
                self.assertEqual(result["durableGameIds"], [])
                download.assert_not_called()

    def test_failure_to_fsync_manifest_does_not_acknowledge(self):
        original = batch.archive.os.fsync
        with self.store.manifest.open("ab"):
            pass
        def failed(descriptor):
            import os
            if os.fstat(descriptor).st_ino == self.store.manifest.stat().st_ino:
                raise OSError("synthetic durable write failure")
            return original(descriptor)
        with patch.object(batch.archive.os, "fsync", side_effect=failed):
            result = batch.ingest(io.BytesIO(exported()), self.store)
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["durableGameIds"], [])


if __name__ == "__main__":
    unittest.main()
