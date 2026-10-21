#!/usr/bin/env python3
"""Single-writer loopback archive bridge; never opens a browser or requests games.

The page must obtain normal browser permission for loopback access. This server
uses standard fixed-origin CORS/PNA responses; it cannot bypass that permission.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
from pathlib import Path
import secrets
import sys

import policy_official_batch as batch


ORIGIN = "https://game.maj-soul.com"
QUEUE_SHA256 = "69c33a9a57ec96f436526d6d2ea6333e9cd3b5d0c99d7ec6204cc26780671897"
TARGET_GAMES = 10000
MAX_POST_BYTES = 96 * 1024 * 1024
ALLOWED_HEADERS = {"authorization", "content-type", "x-batch-id", "x-collector-error"}
ERRORS = (ValueError, OSError, KeyError, TypeError, batch.archive.StopCollection)


def write_status(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(path.suffix + ".part")
    with staged.open("wb") as handle:
        handle.write(batch.archive.encoded_json(value))
        handle.flush()
        os.fsync(handle.fileno())
    staged.replace(path)
    batch.archive.OfficialArchive._sync_directory(path.parent)


class ArchiveBridge:
    def __init__(self, queue, schema, archive, spool, status_file):
        raw_queue = Path(queue).read_bytes()
        if hashlib.sha256(raw_queue).hexdigest() != QUEUE_SHA256:
            raise ValueError("Public UUID queue SHA256 differs from the pinned queue")
        self.queue = [batch.archive.valid_identifier(line) for line in raw_queue.decode("ascii").splitlines()]
        if len(set(self.queue)) != len(self.queue):
            raise ValueError("Public UUID queue contains duplicate identifiers")
        self.store = batch.archive.OfficialArchive(archive, Path(schema).read_bytes())
        if not set(self.store.games).issubset(self.queue):
            raise ValueError("Existing archive contains games outside the pinned queue")
        self.spool, self.status_file = Path(spool), Path(status_file)
        self.spool.mkdir(parents=True, exist_ok=True)
        self.capability = secrets.token_hex(32)
        self.pending, self.error, self.last_batch = None, "", None
        self.publish()

    def status(self):
        return {"status": "stopped" if self.error else "complete" if self.store.count >= TARGET_GAMES else "ready",
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "uniqueGames": self.store.count, "targetGames": TARGET_GAMES,
                "queueSha256": QUEUE_SHA256, "queueSize": len(self.queue),
                "pendingBatchId": self.pending["batchId"] if self.pending else None,
                "lastBatch": self.last_batch, "error": self.error}

    def publish(self):
        write_status(self.status_file, self.status())

    def stop(self, error):
        self.error = self.error or str(error).replace("\r", " ").replace("\n", " ")[:512]
        try:
            self.publish()
        except OSError:
            # A storage failure still latches the in-memory stop; no subsequent batch is accepted.
            pass

    def next_batch(self):
        if self.status()["status"] != "ready":
            return {**self.status(), "batchId": None, "gameIds": []}
        if not self.pending:
            remaining = min(50, TARGET_GAMES - self.store.count)
            ids = [game for game in self.queue if game not in self.store.games][:remaining]
            if not ids:
                self.stop("Pinned public queue exhausted before the target")
                return {**self.status(), "batchId": None, "gameIds": []}
            self.pending = {"batchId": secrets.token_hex(16), "gameIds": ids}
            self.publish()
        return {**self.status(), **self.pending}

    def accept_batch(self, stream, size, batch_id, collector_error=""):
        if self.error or self.store.count >= TARGET_GAMES:
            raise ValueError("Collection is stopped or complete")
        if not self.pending or batch_id != self.pending["batchId"]:
            raise ValueError("POST must match the currently pending batch")
        if not 0 <= size <= MAX_POST_BYTES:
            raise ValueError("Batch body exceeds the fixed size limit")
        if len(collector_error) > 512 or any(ord(c) < 32 or ord(c) > 126 for c in collector_error):
            raise ValueError("Collector error must be at most 512 printable ASCII characters")
        staged = self.spool / (batch_id + ".ndjson.part")
        saved = self.spool / (batch_id + ".ndjson")
        # Save the entire supplied body first. A truncated upload remains as .part evidence.
        checksum = hashlib.sha256()
        with staged.open("xb") as handle:
            try:
                remaining = size
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Truncated batch upload; stopped without retry")
                    handle.write(chunk)
                    checksum.update(chunk)
                    remaining -= len(chunk)
            finally:
                if not handle.closed:
                    handle.flush()
                    os.fsync(handle.fileno())
        if saved.exists():
            raise ValueError("Refusing to replace an already spooled batch")
        staged.replace(saved)
        batch.archive.OfficialArchive._sync_directory(self.spool)
        result = {"batchId": batch_id, "durableGameIds": [], "processedResponses": 0,
                  "savedGames": 0, "duplicateGames": 0, "spoolFile": str(saved), "spoolBytes": size,
                  "spoolSha256": checksum.hexdigest()}
        expected = self.pending["gameIds"]
        try:
            with saved.open("rb") as handle:
                while line := handle.readline(batch.MAX_LINE_BYTES + 1):
                    index = result["processedResponses"]
                    item, _ = batch.decode_item(line)
                    if index >= len(expected) or item["gameId"] != expected[index]:
                        raise ValueError("Response UUIDs must be the ordered prefix of the pending public batch")
                    one = batch.ingest(io.BytesIO(line), self.store, fetch_data_urls=True)
                    for key in ("processedResponses", "savedGames", "duplicateGames"):
                        result[key] += one[key]
                    result["durableGameIds"].extend(one["durableGameIds"])
                    if one["status"] != "complete":
                        raise ValueError(one["error"])
            if collector_error:
                raise ValueError("Collector stopped: " + collector_error)
            if result["processedResponses"] != len(expected):
                raise ValueError("Incomplete batch prefix; stopped without advancing the queue")
        except ERRORS as error:
            self.stop(error)
        result.update(status=self.status()["status"], uniqueGames=self.store.count, error=self.error)
        self.last_batch = {key: value for key, value in result.items() if key != "durableGameIds"}
        if not self.error:
            self.pending = None
        try:
            self.publish()
        except OSError as error:
            self.stop(error)
            result.update(status="stopped", error=self.error)
        return result


class BridgeHandler(BaseHTTPRequestHandler):
    timeout = 60  # StreamRequestHandler.setup applies this to the accepted socket, including rfile.read.

    def log_message(self, *_):
        pass  # Never log request headers, capabilities, replay bodies, or base64.

    def log_error(self, *_):
        self.bridge.stop("HTTP transport or request failure")

    @property
    def bridge(self):
        return self.server.bridge

    def reply(self, code, value, cors=False, preflight=False):
        data = batch.archive.encoded_json(value)
        self.send_response(code)
        if cors:
            self.send_header("Access-Control-Allow-Origin", ORIGIN)
            self.send_header("Vary", "Origin")
        if preflight:
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", ", ".join(sorted(ALLOWED_HEADERS)))
            if self.headers.get("Access-Control-Request-Private-Network") == "true":
                self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def reject(self, code, message):
        self.bridge.stop(message)
        self.reply(code, {"status": "stopped", "durableGameIds": [], "error": message},
                   cors=getattr(self, "headers", {}).get("Origin") == ORIGIN)

    def send_error(self, code, message=None, explain=None):
        self.reject(code, "HTTP request rejected")

    def authorized(self, preflight=False):
        for key in ("Origin", "Authorization", "Content-Length", "X-Batch-Id", "X-Collector-Error"):
            if len(self.headers.get_all(key, [])) > 1:
                self.reject(400, "Duplicate request header")
                return False
        if self.headers.get("Origin") != ORIGIN:
            self.reject(403, "Origin is not the official game origin")
            return False
        authorization = self.headers.get("Authorization", "")
        if not preflight and (not authorization.isascii() or not secrets.compare_digest(
                authorization, "Bearer " + self.bridge.capability)):
            self.reject(403, "Invalid per-run archive capability")
            return False
        return True

    def do_OPTIONS(self):
        if not self.authorized(preflight=True):
            return
        requested = {h.strip().lower() for h in self.headers.get("Access-Control-Request-Headers", "").split(",") if h.strip()}
        if (self.path not in ("/health", "/next", "/batch") or
                self.headers.get("Access-Control-Request-Method") not in ("GET", "POST") or
                not requested.issubset(ALLOWED_HEADERS)):
            self.reject(400, "Unsupported CORS preflight")
            return
        self.reply(200, {"status": "preflight"}, cors=True, preflight=True)

    def do_GET(self):
        if not self.authorized():
            return
        try:
            if self.path == "/health":
                value = self.bridge.status()
            elif self.path == "/next":
                value = self.bridge.next_batch()
            else:
                self.reject(404, "Unknown archive endpoint")
                return
            self.reply(200, value, cors=True)
        except ERRORS as error:
            self.reject(500, str(error)[:512])

    def do_POST(self):
        if not self.authorized():
            return
        try:
            if self.path != "/batch":
                self.reject(404, "Unknown archive endpoint")
                return
            if self.headers.get("Transfer-Encoding") or self.headers.get_content_type() != "application/x-ndjson":
                self.reject(400, "Only bounded application/x-ndjson uploads are accepted")
                return
            size_text = self.headers.get("Content-Length", "")
            if not size_text.isascii() or not size_text.isdigit():
                self.reject(411, "An explicit Content-Length is required")
                return
            result = self.bridge.accept_batch(self.rfile, int(size_text), self.headers.get("X-Batch-Id", ""),
                                               self.headers.get("X-Collector-Error", ""))
            # Application-level stop results still carry acknowledgements for preceding durable games.
            self.reply(200, result, cors=True)
        except ERRORS as error:
            self.reject(400, str(error)[:512])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("queue", "schema", "archive", "spool", "status-file", "capability-file"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    try:
        bridge = ArchiveBridge(args.queue, args.schema, args.archive, args.spool, args.status_file)
        with HTTPServer(("127.0.0.1", args.port), BridgeHandler) as server:
            server.bridge = bridge
            args.capability_file.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(args.capability_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as handle:
                handle.write(bridge.capability + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}",
                              "capabilityFile": str(args.capability_file), **bridge.status()}), flush=True)
            server.serve_forever()
    except ERRORS as error:
        parser.exit(2, f"policy_official_bridge: {error}\n")


if __name__ == "__main__":
    main()
