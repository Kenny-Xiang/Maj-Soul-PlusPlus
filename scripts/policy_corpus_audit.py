#!/usr/bin/env python3
"""Audit and retain complete three- or four-player MJAI games from local tar archives.

The publisher's room classification is provenance, not independently verified
player ranks. Converted MJAI does not contain Mahjong Soul operation lists.
"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import uuid

import zstandard


MAX_COMPRESSED_BYTES = 16 * 1024 * 1024
MAX_DECODED_BYTES = 32 * 1024 * 1024
SUFFIX = ".mjai.json.zst"
ID_PATTERN = re.compile(r"\d{6}-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
TILE_PATTERN = re.compile(r"(?:[1-9][mps]|5[mps]r|[ESWNPFC])\Z")
SANMA_REMOVED_TILES = frozenset({"2m", "3m", "4m", "5m", "5mr", "6m", "7m", "8m"})
ACTOR_EVENTS = {"tsumo", "dahai", "chi", "pon", "daiminkan", "ankan",
                "kakan", "reach", "reach_accepted", "hora"}
EVENT_TYPES = ACTOR_EVENTS | {"start_game", "start_kyoku", "end_kyoku",
                             "end_game", "dora", "ryukyoku"}


class InvalidGame(ValueError):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def game_id(member_name):
    member = PurePosixPath(member_name)
    if member.is_absolute() or ".." in member.parts or not member.name.endswith(SUFFIX):
        raise InvalidGame("invalid_member_name")
    value = member.name[:-len(SUFFIX)].replace("_", "-").lower()
    if not ID_PATTERN.fullmatch(value):
        raise InvalidGame("invalid_game_id")
    try:
        datetime.strptime(value[:6], "%y%m%d")
        uuid.UUID(value[7:])
    except ValueError as error:
        raise InvalidGame("invalid_game_id") from error
    return value


def integer(value, minimum=None, maximum=None):
    return (type(value) is int and (minimum is None or value >= minimum)
            and (maximum is None or value <= maximum))


def tile(value, players=4):
    return (isinstance(value, str) and TILE_PATTERN.fullmatch(value) is not None
            and not (players == 3 and value in SANMA_REMOVED_TILES))


def validate_game(compressed, players=4):
    if type(players) is not int or players not in (3, 4):
        raise ValueError("players must be 3 or 4")
    if len(compressed) > MAX_COMPRESSED_BYTES:
        raise InvalidGame("compressed_size_limit")
    try:
        frame_size = zstandard.get_frame_parameters(compressed).content_size
        if frame_size != zstandard.CONTENTSIZE_UNKNOWN and frame_size > MAX_DECODED_BYTES:
            raise InvalidGame("decoded_size_limit")
        raw = zstandard.ZstdDecompressor().decompress(
            compressed, max_output_size=MAX_DECODED_BYTES + 1, allow_extra_data=False)
    except zstandard.ZstdError as error:
        raise InvalidGame("invalid_zstandard") from error
    if len(raw) > MAX_DECODED_BYTES:
        raise InvalidGame("decoded_size_limit")
    try:
        lines = raw.decode("utf-8").splitlines()
        events = [json.loads(line) for line in lines]
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise InvalidGame("invalid_json_lines") from error
    if not events or any(not isinstance(event, dict) for event in events):
        raise InvalidGame("invalid_events")
    if events[0].get("type") != "start_game" or events[-1].get("type") != "end_game":
        raise InvalidGame("missing_game_boundary")
    names = events[0].get("names")
    if not isinstance(names, list) or len(names) != players or any(not isinstance(n, str) for n in names):
        raise InvalidGame("not_three_players" if players == 3 else "not_four_players")

    rounds = 0
    in_round = False
    terminal = False
    types = Counter()
    actor_events = ACTOR_EVENTS | ({"kita"} if players == 3 else set())
    event_types = EVENT_TYPES | actor_events
    for index, event in enumerate(events):
        kind = event.get("type")
        if not isinstance(kind, str) or kind not in event_types:
            raise InvalidGame("unknown_event_type")
        if players == 3 and kind == "chi":
            raise InvalidGame("chi_in_three_player_game")
        types[kind] += 1
        if kind == "start_game":
            if index != 0:
                raise InvalidGame("duplicate_start_game")
            continue
        if kind == "end_game":
            if index != len(events) - 1 or in_round or rounds == 0:
                raise InvalidGame("invalid_end_game")
            continue
        if kind == "start_kyoku":
            if in_round:
                raise InvalidGame("nested_round")
            hands = event.get("tehais")
            if (not isinstance(hands, list) or len(hands) != players
                    or any(not isinstance(hand, list) or len(hand) != 13
                           or not all(tile(pai, players) for pai in hand) for hand in hands)):
                raise InvalidGame("incomplete_initial_hands")
            if (not integer(event.get("oya"), 0, players - 1)
                    or not integer(event.get("kyoku"), 1, players)
                    or not integer(event.get("honba"), 0)
                    or not integer(event.get("kyotaku"), 0)
                    or not isinstance(event.get("bakaze"), str)
                    or event["bakaze"] not in {"E", "S", "W", "N"}
                    or not tile(event.get("dora_marker"), players)):
                raise InvalidGame("invalid_round_metadata")
            scores = event.get("scores")
            if not isinstance(scores, list) or len(scores) != players or not all(integer(s) for s in scores):
                raise InvalidGame("invalid_scores")
            known = Counter(pai.rstrip("r") for hand in hands for pai in hand)
            known[event["dora_marker"].rstrip("r")] += 1
            if max(known.values()) > 4:
                raise InvalidGame("impossible_initial_tile_count")
            rounds += 1
            in_round, terminal = True, False
            continue
        if not in_round:
            raise InvalidGame("event_outside_round")
        if kind == "end_kyoku":
            if not terminal:
                raise InvalidGame("missing_round_result")
            in_round = False
            continue
        if terminal and kind not in {"hora", "dora", "reach_accepted"}:
            raise InvalidGame("action_after_round_result")
        if kind in actor_events and not integer(event.get("actor"), 0, players - 1):
            raise InvalidGame("invalid_actor")
        if "target" in event and not integer(event["target"], 0, players - 1):
            raise InvalidGame("invalid_target")
        if kind in {"chi", "pon", "daiminkan", "hora"} and "target" not in event:
            raise InvalidGame("missing_target")
        for field in ("pai", "dora_marker"):
            if field in event and not tile(event[field], players):
                raise InvalidGame("invalid_tile")
        # RiichiEnv accepts three-player MJAI {type: "kita", actor: 0}.
        # Preserve that event verbatim; an optional explicit tile must be North.
        if kind == "kita" and "pai" in event and event["pai"] != "N":
            raise InvalidGame("invalid_kita_tile")
        if kind in {"tsumo", "dahai", "chi", "pon", "daiminkan", "kakan"} and "pai" not in event:
            raise InvalidGame("missing_tile")
        if kind == "dora" and "dora_marker" not in event:
            raise InvalidGame("missing_tile")
        consumed_length = {"chi": 2, "pon": 2, "daiminkan": 3, "ankan": 4, "kakan": 3}.get(kind)
        if consumed_length is not None:
            consumed = event.get("consumed")
            if (not isinstance(consumed, list) or len(consumed) != consumed_length
                    or not all(tile(pai, players) for pai in consumed)):
                raise InvalidGame("invalid_consumed_tiles")
        if kind == "dahai" and type(event.get("tsumogiri")) is not bool:
            raise InvalidGame("invalid_tsumogiri")
        if "deltas" in event and (not isinstance(event["deltas"], list)
                                  or len(event["deltas"]) != players
                                  or not all(integer(s) for s in event["deltas"])):
            raise InvalidGame("invalid_score_deltas")
        if kind in {"hora", "ryukyoku"}:
            terminal = True

    canonical = "\n".join(json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                          for event in events).encode("utf-8")
    return {"players": players, "roundCount": rounds, "eventCount": len(events),
            "eventTypes": dict(sorted(types.items())), "decodedBytes": len(raw),
            "decodedSha256": sha256(raw), "eventsSha256": sha256(canonical),
            "compressedSha256": sha256(compressed), "compressedBytes": len(compressed)}


def audit_archives(archives, output, limit, source_url, publisher_room="throne", *, players=4):
    if limit < 1:
        raise ValueError("limit must be positive")
    if type(players) is not int or players not in (3, 4):
        raise ValueError("players must be 3 or 4")
    output = Path(output)
    games_dir = output / "data" / "games"
    games_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.jsonl"
    seen_ids, seen_hashes = set(), set()
    if manifest_path.exists():
        for line in manifest_path.read_text().splitlines():
            row = json.loads(line)
            identifier = row["gameId"]
            expected_path = f"data/games/{identifier}{SUFFIX}"
            if game_id(identifier + SUFFIX) != identifier or row["path"] != expected_path:
                raise ValueError("Invalid existing manifest path")
            checked = validate_game((output / expected_path).read_bytes(), players)
            if any(row.get(key) != value for key, value in checked.items()):
                raise ValueError("Existing manifest does not match saved game")
            if identifier in seen_ids or checked["eventsSha256"] in seen_hashes:
                raise ValueError("Existing manifest contains duplicate games")
            seen_ids.add(identifier)
            seen_hashes.add(checked["eventsSha256"])
    resumed = len(seen_ids)
    rejected = Counter()
    examples = []
    archive_reports = []
    visited = 0
    with manifest_path.open("a", encoding="utf-8") as manifest:
        for archive in map(Path, archives):
            if len(seen_ids) >= limit:
                break
            archive_info = {"name": archive.name, "sha256": file_sha256(archive),
                            "bytes": archive.stat().st_size, "fullyScanned": False}
            archive_reports.append(archive_info)
            with tarfile.open(archive, "r|*") as contents:
                for member in contents:
                    if len(seen_ids) >= limit:
                        break
                    if member.isdir():
                        continue
                    visited += 1
                    try:
                        if not member.isfile():
                            raise InvalidGame("non_regular_member")
                        identifier = game_id(member.name)
                        if identifier in seen_ids:
                            raise InvalidGame("duplicate_game_id")
                        if member.size > MAX_COMPRESSED_BYTES:
                            raise InvalidGame("compressed_size_limit")
                        compressed = contents.extractfile(member).read()
                        checked = validate_game(compressed, players)
                        if checked["eventsSha256"] in seen_hashes:
                            raise InvalidGame("duplicate_content")
                    except InvalidGame as error:
                        reason = str(error)
                        rejected[reason] += 1
                        if len(examples) < 20:
                            examples.append({"archive": archive.name, "member": member.name, "reason": reason})
                        continue
                    relative = f"data/games/{identifier}{SUFFIX}"
                    target = output / relative
                    if target.exists() and target.read_bytes() != compressed:
                        raise ValueError(f"Refusing to overwrite different existing game: {identifier}")
                    temporary = target.with_suffix(".part")
                    temporary.write_bytes(compressed)
                    temporary.replace(target)
                    row = {"schemaVersion": 1, "format": "mjai-jsonl-zstandard", "gameId": identifier,
                           "date": datetime.strptime(identifier[:6], "%y%m%d").date().isoformat(),
                           "path": relative, **checked, "officialOperationLists": False,
                           "source": {"url": source_url, "archive": archive.name,
                                      "archiveSha256": archive_info["sha256"], "member": member.name},
                           "roomEvidence": {"kind": "archive-publisher", "room": publisher_room,
                                            "independentlyVerified": False},
                           "individualPlayerRanks": None}
                    manifest.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                    manifest.flush()
                    seen_ids.add(identifier)
                    seen_hashes.add(checked["eventsSha256"])
                else:
                    archive_info["fullyScanned"] = True
    report = {"schemaVersion": 1, "format": "mjai-jsonl-zstandard", "targetGames": limit,
              "players": players,
              "uniqueCompleteGames": len(seen_ids), "resumedGames": resumed,
              "newGames": len(seen_ids) - resumed, "visitedMembers": visited,
              "goalReached": len(seen_ids) >= limit, "excluded": dict(sorted(rejected.items())),
              "excludedExamples": examples, "archives": archive_reports,
              "validationScope": f"game and round boundaries, {players} complete initial hands, tiles and seat indices; not full rules replay",
              "officialOperationLists": False,
              "roomEvidence": "Publisher archive classification only; individual ranks not verified"}
    temporary = output / "report.json.part"
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(output / "report.json")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--players", type=int, choices=(3, 4), default=4,
                        help="Required player count; three-player games are never inferred from padded four-player data")
    parser.add_argument("--source-url", required=True, help="Pinned publisher URL recorded as provenance; not fetched")
    parser.add_argument("--publisher-room", default="throne", help="Publisher's room classification, not player-rank evidence")
    args = parser.parse_args()
    report = audit_archives(args.archives, args.output, args.limit, args.source_url,
                            args.publisher_room, players=args.players)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["goalReached"] else 2


if __name__ == "__main__":
    sys.exit(main())
