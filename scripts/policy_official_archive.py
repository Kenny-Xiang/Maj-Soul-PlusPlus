#!/usr/bin/env python3
"""Archive complete fetchGameRecord protobuf responses without account access.

Offline ingestion never follows data_url. A collector must explicitly supply
its matching original body; headers or body-only exports do not count as games.
"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import policy_fetch as fetch


MAX_BYTES = fetch.MAX_BYTES
GAME_ID = re.compile(r"\d{6}-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
TILE = re.compile(r"(?:[0-9][mps]|[1-7]z)\Z")
# Official client desktop.matchmode, documented in src/unity_lobby.js.
THRONE_MODES = {15: 1, 16: 2}
RESULTS = {"RecordHule", "RecordNoTile", "RecordLiuJu"}


class StopCollection(RuntimeError):
    """An authentication/rate/error response must stop the caller's collection."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def trusted_data_url(url):
    try:
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port
    except (ValueError, TypeError) as error:
        raise ValueError("Malformed replay data_url") from error
    if (parsed.scheme != "https" or host != "record-v2.maj-soul.com" or port != 5333
            or parsed.username or parsed.password or parsed.fragment):
        raise ValueError(f"Untrusted replay data_url host/port: {host or '<missing>'}:{port or 443}")
    if not parsed.path.startswith("/majsoul/game_record/"):
        raise ValueError("Untrusted replay data_url path")
    return parsed


def download_data_url(url):
    """Explicit collector helper: fixed official origin, no cookies/retries/redirects."""
    trusted_data_url(url)
    opener = urllib.request.build_opener(fetch.NoRedirect)
    try:
        with opener.open(url, timeout=30) as response:
            status = response.getcode()
            if status in (401, 403, 429):
                raise StopCollection(f"Official replay HTTP {status}; collection must stop")
            if status != 200:
                raise ValueError(f"Official replay HTTP {status}")
            data = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403, 429):
            raise StopCollection(f"Official replay HTTP {error.code}; collection must stop") from None
        raise ValueError(f"Official replay HTTP {error.code}") from None
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Official replay body is empty or exceeds the 16 MiB limit")
    return data


def encoded_json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def valid_identifier(identifier):
    if not isinstance(identifier, str) or not GAME_ID.fullmatch(identifier):
        raise ValueError("Invalid Mahjong Soul game UUID")
    try:
        datetime.strptime(identifier[:6], "%y%m%d")
    except ValueError as error:
        raise ValueError("Invalid Mahjong Soul game UUID date") from error
    return identifier


def four_scores(value):
    return isinstance(value, list) and len(value) == 4 and all(type(x) is int for x in value)


def final_draw_riichi_evidence(body, decoder, records, old, delta, header_scores):
    """Validate only recorded, unclaimed riichi deposits awarded to a sole leader."""
    detail = fetch.unwrap(body, decoder)["data"]
    actions = detail.get("actions", [])
    if (detail.get("version") != 210715 or len(actions) < 2 or
            actions[-1].get("type") != 4 or actions[-1].get("game_event") != 2 or
            records[-1].get("sourceActionIndex") != len(actions) - 2 or
            any(a.get("type") == 4 and a.get("game_event") == 2 for a in actions[:-1])):
        raise ValueError("Final drawn score difference lacks an explicit final game-end action")
    first = max(i for i, record in enumerate(records) if record["name"] == "RecordNewRound")
    opening = records[first]["data"]
    pot = opening.get("liqibang")
    if type(pot) is not int or pot < 0 or records[-1]["data"].get("liujumanguan"):
        raise ValueError("Final drawn score difference lacks a normal draw and explicit opening riichi pool")
    current, successes, seen = list(opening["scores"]), [], set()
    for index in range(first + 1, len(records) - 1):
        record = records[index]
        if record["data"].get("scores"):
            raise ValueError("Final drawn hand has an unsupported intermediate score settlement")
        if "liqi" not in record["data"]:
            continue
        paid = record["data"]["liqi"]
        seat, score, next_pot = paid.get("seat", 0), paid.get("score"), paid.get("liqibang")
        declaration = records[index - 1]
        if (paid.get("failed") or type(seat) is not int or seat not in range(4) or seat in seen or
                type(score) is not int or score != current[seat] - 1000 or
                type(next_pot) is not int or next_pot != pot + 1 or
                declaration["name"] != "RecordDiscardTile" or declaration["data"].get("seat", 0) != seat or
                not (declaration["data"].get("is_liqi") or declaration["data"].get("is_wliqi"))):
            raise ValueError("Final drawn hand has inconsistent recorded riichi deposits")
        current[seat], pot = score, next_pot
        seen.add(seat)
        successes.append({"sourceActionIndex": record["sourceActionIndex"],
                          "seat": seat, "score": score, "liqibang": pot})
    settlement = [old[seat] + delta[seat] for seat in range(4)]
    if current != old or sum(delta) != 0 or pot <= 0:
        raise ValueError("Final drawn scores differ from the recorded riichi deposit ledger")
    leaders = [seat for seat in range(4) if settlement[seat] == max(settlement)]
    if len(leaders) != 1:
        raise ValueError("Final drawn riichi allocation requires a unique first-place score")
    leader = leaders[0]
    expected = list(settlement)
    expected[leader] += pot * 1000
    if expected != header_scores:
        raise ValueError("Final drawn scores differ from the exact recorded riichi allocation")
    return {"openingSourceActionIndex": records[first]["sourceActionIndex"],
            "openingScores": opening["scores"], "openingRiichiSticks": opening["liqibang"],
            "successfulRiichi": successes, "remainingRiichiSticks": pot,
            "recipientSeat": leader, "awardPoints": pot * 1000,
            "drawSettlementScores": settlement, "headerScores": header_scores,
            "endActionIndex": len(actions) - 1}


def inspect_response(raw, fmt, decoder, expected_uuid=None, data_url_body=None, body_url=None):
    if fmt not in ("response", "ws-response"):
        raise ValueError("A complete ResGameRecord protobuf response or WebSocket response frame is required")
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Response is empty or exceeds the 16 MiB limit")
    decoder.unknown_fields.clear()
    payload = fetch.load_payload(raw, fmt, decoder)
    error_code = payload.get("error", {}).get("code", 0)
    if error_code:
        raise StopCollection(f"fetchGameRecord error {error_code}; collection must stop")
    head = payload.get("head")
    if not isinstance(head, dict):
        raise ValueError("Complete original response header is required; headless bodies do not count")
    identifier = valid_identifier(head.get("uuid"))
    if expected_uuid is not None and identifier != expected_uuid:
        raise ValueError("Response UUID differs from requested UUID")
    config = head.get("config", {})
    mode_id = config.get("meta", {}).get("mode_id")
    if (config.get("category") != 2 or mode_id not in THRONE_MODES
            or config.get("mode", {}).get("mode") != THRONE_MODES[mode_id]):
        raise ValueError("Official header is not four-player ranked Throne East/South (15/16)")
    accounts, results = head.get("accounts", []), head.get("result", {}).get("players", [])
    for label, players in (("accounts", accounts), ("results", results)):
        if len(players) != 4 or {player.get("seat", 0) for player in players} != {0, 1, 2, 3}:
            raise ValueError(f"Official header requires four distinct player {label}")
    if head.get("robots") or config.get("mode", {}).get("ai"):
        raise ValueError("Robot games are not accepted as ranked four-player games")
    start, end = head.get("start_time", 0), head.get("end_time", 0)
    if not (type(start) is int and type(end) is int and 0 < start < end):
        raise ValueError("Official header lacks completed game times")

    body = payload.get("data", b"")
    source = "inline"
    if body:
        if data_url_body is not None or body_url is not None:
            raise ValueError("External body supplied for an inline-data response")
    else:
        url = payload.get("data_url", "")
        trusted_data_url(url)
        if data_url_body is None or body_url != url:
            raise ValueError("data_url requires its matching original body before this game can count")
        body, source = data_url_body, "data_url"
    if not isinstance(body, bytes) or not body or len(body) > MAX_BYTES:
        raise ValueError("Replay body is empty or exceeds the 16 MiB limit")
    normalized = fetch.normalize({**payload, "data": body}, decoder, identifier)
    records = normalized["records"]
    if records[0]["name"] != "RecordNewRound" or records[-1]["name"] not in RESULTS:
        raise ValueError("Replay does not include complete opening and terminal result records")
    if any(records[0]["data"].get(key, 0) != 0 for key in ("chang", "ju", "ben")):
        raise ValueError("Replay starts after the initial East-one hand")
    rounds, active = 0, False
    for record in records:
        kind, data = record["name"], record["data"]
        if kind == "RecordNewRound":
            if active:
                raise ValueError("Previous round lacks its result")
            dealer = data.get("ju", 0)
            if dealer not in range(4) or not four_scores(data.get("scores")):
                raise ValueError("New round lacks four-player scores/dealer")
            for seat in range(4):
                hand = data.get(f"tiles{seat}", [])
                if len(hand) != (14 if seat == dealer else 13) or any(not TILE.fullmatch(t) for t in hand):
                    raise ValueError("New round lacks complete original four-player hands")
            rounds, active = rounds + 1, True
        elif not active:
            raise ValueError("Replay event occurs outside a round")
        elif kind in RESULTS:
            active = False
    final, riichi_evidence = records[-1], None
    scores = final["data"].get("scores")
    by_seat = {player.get("seat", 0): player.get("part_point_1", 0) for player in results}
    if final["name"] == "RecordHule":
        if not final["data"].get("hules") or not four_scores(scores):
            raise ValueError("Final win record lacks winner/scores")
        if scores != [by_seat[seat] for seat in range(4)]:
            raise ValueError("Final win scores differ from the complete header result")
    elif final["name"] == "RecordNoTile":
        # Official complete replays can explicitly record gameend=false here.
        # Bind the recorded settlement to the completed header instead. Multiple
        # settlements need separate evidence for their aggregation semantics.
        if len(final["data"].get("players", [])) != 4:
            raise ValueError("Final drawn hand lacks four player results")
        if not isinstance(scores, list) or len(scores) != 1:
            raise ValueError("Final drawn hand requires one reconstructable score settlement")
        old, delta = scores[0].get("old_scores"), scores[0].get("delta_scores")
        if not four_scores(old) or not four_scores(delta):
            raise ValueError("Final drawn hand lacks four original and delta scores")
        if [old[seat] + delta[seat] for seat in range(4)] != [by_seat[seat] for seat in range(4)]:
            riichi_evidence = final_draw_riichi_evidence(body, decoder, records, old, delta,
                                                        [by_seat[seat] for seat in range(4)])
    else:
        scores = final["data"].get("gameend", {}).get("scores")
        if not four_scores(scores) or scores != [by_seat[seat] for seat in range(4)]:
            raise ValueError("Final abort lacks matching complete game-end scores")
    metadata = {"gameId": identifier, "sourceFormat": "majsoul-fetchGameRecord-protobuf",
                "responseFormat": fmt, "dataSource": source, "modeId": mode_id, "playerCount": 4,
                "startTime": start, "endTime": end, "roundCount": rounds, "recordCount": len(records),
                "recordTypes": dict(sorted(Counter(r["name"] for r in records).items())),
                "userInputCount": len(normalized["initialUserInputs"]) + sum(len(r.get("userInputs", [])) for r in records),
                "recordsWithOperations": sum(bool(r["data"].get("operations") or r["data"].get("operation")) for r in records),
                "roomEvidence": {"kind": "official-header-config", "category": 2, "modeId": mode_id, "room": "throne"},
                "unknownFields": sorted(decoder.unknown_fields),
                "validationScope": "complete original header, four-player starting hands and round/result boundaries; not full rules replay"}
    if final["name"] == "RecordNoTile":
        metadata["finalDrawScoreValidation"] = "one recorded old_scores plus delta_scores settlement equals header result; no inferred riichi-stick allocation"
        if riichi_evidence is not None:
            metadata["finalDrawScoreValidation"] = "recorded final-hand riichi deposits and exact sole-leader pool allocation equal header result; explicit final game-end action"
            metadata["finalDrawRiichiEvidence"] = riichi_evidence
    return metadata, head, body


class OfficialArchive:
    """Single-writer archive. Only successfully validated complete games are counted."""
    def __init__(self, output, schema_bytes):
        if digest(schema_bytes) != fetch.SCHEMA_SHA256:
            raise ValueError("Schema differs from the pinned official client schema")
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.decoder = fetch.SchemaDecoder(json.loads(schema_bytes))
        self.schema_hash = digest(schema_bytes)
        self._write_exact(self.output / "schema.liqi.json", schema_bytes)
        self.manifest = self.output / "manifest.jsonl"
        self.games, self.body_hashes = {}, {}
        if self.manifest.exists():
            for number, line in enumerate(self.manifest.read_bytes().splitlines(), 1):
                try:
                    row = json.loads(line)
                except ValueError as error:
                    raise ValueError(f"Archive manifest line {number} is incomplete or malformed; restore refused") from error
                identifier = valid_identifier(row["gameId"])
                payloads = {}
                for kind, filename in (("response", "response.bin"), ("data", "data.wrapper.pb"), ("head", "head.json")):
                    descriptor = row["files"][kind]
                    if descriptor["path"] != f"games/{identifier}/{filename}":
                        raise ValueError("Saved archive path differs")
                    path = (self.output / descriptor["path"]).resolve()
                    if not path.is_relative_to(self.output):
                        raise ValueError("Saved archive path escapes output")
                    data = path.read_bytes()
                    if digest(data) != descriptor["sha256"] or len(data) != descriptor["bytes"]:
                        raise ValueError("Saved archive file integrity check failed")
                    payloads[kind] = data
                response = fetch.load_payload(payloads["response"], row["responseFormat"], self.decoder)
                external = row["dataSource"] == "data_url"
                metadata, head, body = inspect_response(payloads["response"], row["responseFormat"], self.decoder,
                    identifier, payloads["data"] if external else None, response.get("data_url") if external else None)
                if (any(row.get(key) != value for key, value in metadata.items()) or
                        row.get("schemaSha256") != self.schema_hash or body != payloads["data"] or
                        encoded_json(head) != payloads["head"]):
                    raise ValueError("Saved archive metadata differs from its original response")
                body_hash = digest(body)
                if identifier in self.games or body_hash in self.body_hashes:
                    raise ValueError("Duplicate game UUID or body SHA256 in saved archive")
                self.games[identifier], self.body_hashes[body_hash] = row, identifier

    @property
    def count(self):
        return len(self.games)

    @staticmethod
    def _sync_directory(path):
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _write_exact(path, data):
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError("Refusing to replace a different saved archive file")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        staged = path.with_suffix(path.suffix + ".part")
        with staged.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        staged.replace(path)
        OfficialArchive._sync_directory(path.parent)
        OfficialArchive._sync_directory(path.parent.parent)

    def add(self, response_bytes, *, fmt="response", expected_uuid=None, data_url_body=None, body_url=None):
        metadata, head, body = inspect_response(response_bytes, fmt, self.decoder, expected_uuid, data_url_body, body_url)
        identifier, body_hash = metadata["gameId"], digest(body)
        if identifier in self.games:
            previous = self.games[identifier]
            if previous["files"]["data"]["sha256"] != body_hash:
                raise ValueError("Same game UUID returned different original replay data")
            return {"status": "duplicate", "gameId": identifier, "uniqueGames": self.count, "record": previous}
        if body_hash in self.body_hashes:
            raise ValueError("Original replay body SHA256 already belongs to a different game UUID")
        row = {**metadata, "schemaSha256": self.schema_hash, "files": {}}
        for kind, filename, data in (("response", "response.bin", response_bytes),
                                      ("data", "data.wrapper.pb", body), ("head", "head.json", encoded_json(head))):
            relative = f"games/{identifier}/{filename}"
            self._write_exact(self.output / relative, data)
            row["files"][kind] = {"path": relative, "sha256": digest(data), "bytes": len(data)}
        with self.manifest.open("ab") as handle:
            handle.write(encoded_json(row))
            handle.flush()
            os.fsync(handle.fileno())
        self._sync_directory(self.output)
        self.games[identifier], self.body_hashes[body_hash] = row, identifier
        return {"status": "saved", "gameId": identifier, "uniqueGames": self.count, "record": row}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--format", choices=("response", "ws-response"), default="response")
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-uuid")
    parser.add_argument("--body-file", type=Path)
    parser.add_argument("--body-url", help="Must exactly match the response data_url; never fetched implicitly")
    args = parser.parse_args()
    try:
        archive = OfficialArchive(args.output, args.schema.read_bytes())
        result = archive.add(args.input.read_bytes(), fmt=args.format, expected_uuid=args.expected_uuid,
                             data_url_body=args.body_file.read_bytes() if args.body_file else None, body_url=args.body_url)
        print(json.dumps({key: result[key] for key in ("status", "gameId", "uniqueGames")}))
    except (ValueError, OSError, KeyError, TypeError, StopCollection) as error:
        parser.exit(2, f"policy_official_archive: {error}\n")


if __name__ == "__main__":
    main()
