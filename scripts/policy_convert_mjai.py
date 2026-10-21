#!/usr/bin/env python3
"""Convert an audited MJAI corpus into per-game, training-ready sample shards."""
import argparse
import bz2
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET

import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from policy_mjai import ENGINE_VERSION, extract_game
from policy_split import read_split
from policy_match_metadata import load_metadata
from policy_metadata import TENHOU_GAME_ID, validate_match_metadata


def digest(data):
    return hashlib.sha256(data).hexdigest()


def converter_signature():
    names = ["scripts/policy_convert_mjai.py", "src/policy_mjai.py", "src/policy_mjai_state.py",
             "src/policy_actions.py", "src/policy_features.py", "src/policy_metadata.py",
             "scripts/policy_match_metadata.py"]
    return digest(b"".join((ROOT / name).read_bytes() for name in names) + ENGINE_VERSION.encode())


def tenhou_source(row, database_root):
    """Normalize the audited research manifest without disguising its source."""
    identifier = row["gameId"]
    match = TENHOU_GAME_ID.fullmatch(identifier)
    if not match or row.get("players") != 3:
        raise ValueError("invalid Tenhou sanma game ID or player count")
    if database_root is None:
        raise ValueError("Tenhou conversion requires --tenhou-db-root to verify XML and disconnects")
    name = row.get("sourceDb", "")
    if not re.fullmatch(r"pathofhouou-\d{4}\.db", name):
        raise ValueError("invalid Tenhou source database name")
    database_root = Path(database_root).resolve()
    path = (database_root / name).resolve()
    if not path.is_relative_to(database_root) or not path.is_file():
        raise ValueError("missing or escaped Tenhou source database")
    compressed_hash = row["audit"]["compressedSha256"]
    if row.get("compressedSha256", compressed_hash) != compressed_hash:
        raise ValueError("inconsistent Tenhou compressed source hash")
    go_type = int(match[1], 16)
    metadata = validate_match_metadata({
        "schemaVersion": 1, "sourcePlatform": "tenhou", "gameId": identifier,
        "playerCount": 3, "goType": go_type, "roundCount": 2 if go_type & 8 else 1,
        "sourceCompressedSha256": compressed_hash,
        "provenance": {"kind": "tenhou-xml-header", "archive": str(path),
                       "xmlSha256": row["sourceXmlSha256"]}}, identifier, compressed_hash)
    return {**row, "compressedSha256": compressed_hash, "matchMetadata": metadata}


def verify_tenhou_xml(row, events):
    """Require original XML evidence; BYE was omitted by the MJAI importer."""
    metadata = row["matchMetadata"]
    path = Path(metadata["provenance"]["archive"])
    with sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True) as database:
        result = database.execute("SELECT log_content FROM logs WHERE log_id=?", (row["gameId"],)).fetchone()
    if result is None:
        raise ValueError("Tenhou XML game is missing")
    raw = bz2.decompress(result[0])
    if digest(raw) != metadata["provenance"]["xmlSha256"]:
        raise ValueError("Tenhou XML source hash mismatch")
    root = ET.fromstring(raw)
    if root.tag != "mjloggm" or root.get("ver") != "2.3":
        raise ValueError("Unsupported Tenhou XML version")
    # Excluding the whole match also covers reconnects, without trying to
    # decide which forced actions were human choices in an incomplete log.
    if root.find("BYE") is not None:
        raise ValueError("Tenhou game contains disconnect BYE; human labels unverified")
    go, users = root.find("GO"), root.find("UN")
    header = events[0].get("_tenhou", {})
    if (go is None or users is None or dict(go.attrib) != header.get("GO") or
            dict(users.attrib) != header.get("UN") or go.get("type") != str(metadata["goType"])):
        raise ValueError("Tenhou XML header differs from MJAI")
    ranks = [int(value) for value in users.get("dan", "").split(",")]
    if len(ranks) != 4 or users.get("n3") or not all(16 <= rank <= 20 for rank in ranks[:3]):
        raise ValueError("Tenhou players lack verified 7-dan-or-higher ranks")


def convert_one(row, source_root, output, signature):
    identifier = row["gameId"]
    try:
        source = (Path(source_root) / row["path"]).resolve()
        if not source.is_relative_to(Path(source_root).resolve()):
            raise ValueError("source path escapes corpus")
        compressed = source.read_bytes()
        if digest(compressed) != row["compressedSha256"]:
            raise ValueError("source hash mismatch")
        raw = zstandard.ZstdDecompressor().decompress(compressed, max_output_size=32 * 1024 * 1024,
                                                     allow_extra_data=False)
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        if row.get("sourcePlatform") == "tenhou":
            verify_tenhou_xml(row, events)
        samples, audit = extract_game(events, identifier, match_metadata=row.get("matchMetadata"))
        if not samples:
            raise ValueError("no verified training samples")
        text = "".join(json.dumps(s, ensure_ascii=False, separators=(",", ":")) + "\n" for s in samples)
        data = zstandard.ZstdCompressor(level=3).compress(text.encode())
        relative = f"games/{identifier}.jsonl.zst"
        target = Path(output) / relative
        staged = target.with_suffix(".part")
        staged.write_bytes(data)
        staged.replace(target)
        audit_path = Path(output) / "audits" / f"{identifier}.json"
        audit_data = (json.dumps(audit, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        audit_path.write_bytes(audit_data)
        return {"gameId": identifier, "path": relative, "samples": len(samples), "sha256": digest(data),
                "bytes": len(data), "sourceSha256": row["compressedSha256"],
                "converterSignature": signature, "audit": audit, "auditSha256": digest(audit_data),
                "roomEvidence": row.get("roomEvidence"), "matchMetadata": row.get("matchMetadata")}
    except (ValueError, KeyError, TypeError, IndexError, OSError, zstandard.ZstdError,
            sqlite3.Error, ET.ParseError) as error:
        return {"gameId": identifier, "error": f"{type(error).__name__}: {error}"}


def validate_saved(row, source, output, signature):
    """Bind resumed statistics to the saved shard and separate audit artifact."""
    try:
        identifier = row["gameId"]
        if (row.get("converterSignature") != signature or
                row["sourceSha256"] != source["compressedSha256"] or
                row["path"] != f"games/{identifier}.jsonl.zst" or
                row.get("roomEvidence") != source.get("roomEvidence") or
                row.get("matchMetadata") != source.get("matchMetadata")):
            raise ValueError("saved provenance differs")
        data = (output / row["path"]).read_bytes()
        if len(data) != row["bytes"] or digest(data) != row["sha256"]:
            raise ValueError("saved shard differs")
        max_size = 128 * 1024 * 1024
        size = zstandard.get_frame_parameters(data).content_size
        if size != zstandard.CONTENTSIZE_UNKNOWN and size > max_size:
            raise ValueError("saved shard exceeds per-game size limit")
        raw = zstandard.ZstdDecompressor().decompress(data, max_output_size=max_size, allow_extra_data=False)
        samples = [json.loads(line) for line in raw.splitlines() if line.strip()]
        if not samples or len(samples) != row["samples"] or any(s["gameId"] != identifier for s in samples):
            raise ValueError("saved sample count or game identity differs")
        audit_data = (output / "audits" / f"{identifier}.json").read_bytes()
        audit = json.loads(audit_data)
        if digest(audit_data) != row["auditSha256"] or audit != row["audit"]:
            raise ValueError("saved audit differs")
        if (audit["gameId"] != identifier or audit["samples"] != len(samples) or
                audit["actions"] != dict(Counter(s["action"]["action"] for s in samples)) or
                audit["labelSources"] != dict(Counter(s["labelSource"] for s in samples))):
            raise ValueError("saved audit counts differ from samples")
    except (ValueError, KeyError, TypeError, IndexError, OSError, zstandard.ZstdError) as error:
        raise ValueError(f"existing conversion differs; use a new output directory: {error}") from error


def convert_corpus(manifest, output, limit, workers, metadata_file=None, split_file=None,
                   tenhou_db_root=None, partitions=None):
    if partitions is not None and split_file is None:
        raise ValueError("partition selection requires a frozen split")
    if version("riichienv") != ENGINE_VERSION:
        raise ValueError(f"conversion requires riichienv=={ENGINE_VERSION}")
    if limit < 1 or not 1 <= workers <= 8:
        raise ValueError("limit must be positive; workers must be 1..8")
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    payload = manifest.read_bytes()
    source_rows = [json.loads(line) for line in payload.splitlines() if line.strip()]
    source_rows = [tenhou_source(row, tenhou_db_root) if row.get("sourcePlatform") == "tenhou"
                   else row for row in source_rows]
    sources = {row.get("sourcePlatform", "majsoul") for row in source_rows}
    if not sources <= {"tenhou", "majsoul"} or len(sources) > 1:
        raise ValueError("convert each source and player-count corpus separately")
    by_id, hashes = {}, set()
    for row in source_rows:
        identifier = row["gameId"]
        if (row.get("sourcePlatform") != "tenhou" and
                not re.fullmatch(r"\d{6}-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", identifier)):
            raise ValueError("invalid Mahjong Soul game ID")
        if identifier in by_id or row["compressedSha256"] in hashes:
            raise ValueError("duplicate source game or content")
        by_id[identifier] = row
        hashes.add(row["compressedSha256"])
    if metadata_file and "tenhou" in sources:
        raise ValueError("--metadata is for Mahjong Soul headers; Tenhou uses verified XML")
    metadata = load_metadata(metadata_file, source_rows) if metadata_file else {}
    source_rows = [{**row, "matchMetadata": metadata.get(row["gameId"], row.get("matchMetadata"))}
                   for row in source_rows]
    by_id = {row["gameId"]: row for row in source_rows}
    split_audit = None
    if split_file is not None:
        frozen_ids = set(json.loads(Path(split_file).read_text())["sources"])
        groups, split_audit = read_split(split_file,
            {game: by_id[game]["compressedSha256"] for game in frozen_ids & by_id.keys()}, partitions)
        selected_ids = {game for group in groups.values() for game in group}
        if limit != len(selected_ids):
            raise ValueError("conversion limit must equal the selected frozen split size")
        source_rows = [row for row in source_rows if row["gameId"] in selected_ids]
        by_id = {row["gameId"]: row for row in source_rows}
    output.mkdir(parents=True, exist_ok=True)
    (output / "games").mkdir(exist_ok=True)
    (output / "audits").mkdir(exist_ok=True)
    result_manifest = output / "manifest.jsonl"
    saved, signature = {}, converter_signature()
    if result_manifest.exists():
        for line in result_manifest.read_text().splitlines():
            row = json.loads(line)
            if row["gameId"] in saved or row["gameId"] not in by_id:
                raise ValueError("existing conversion differs; use a new output directory")
            validate_saved(row, by_id[row["gameId"]], output, signature)
            saved[row["gameId"]] = row
    todo = sorted((r for r in source_rows if r["gameId"] not in saved),
                  key=lambda row: digest(("mjai-corpus-v1:" + row["gameId"]).encode()))
    cursor, failed, started, resumed = 0, [], time.monotonic(), len(saved)
    with result_manifest.open("a") as stream, ProcessPoolExecutor(max_workers=workers) as pool:
        pending = {}
        while len(saved) < limit and (cursor < len(todo) or pending):
            while cursor < len(todo) and len(pending) < workers * 2 and len(saved) + len(pending) < limit:
                row = todo[cursor]
                cursor += 1
                future = pool.submit(convert_one, row, str(manifest.parent), str(output), signature)
                pending[future] = row["gameId"]
            if not pending:
                break
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                del pending[future]
                row = future.result()
                if "error" in row:
                    failed.append(row)
                    continue
                saved[row["gameId"]] = row
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
                if len(saved) % 100 == 0:
                    print(json.dumps({"convertedGames": len(saved), "target": limit,
                                      "failedGames": len(failed), "elapsedSeconds": round(time.monotonic() - started, 1)}), flush=True)
    actions, exclusions, labels = Counter(), Counter(), Counter()
    for row in saved.values():
        actions.update(row["audit"]["actions"])
        exclusions.update(row["audit"]["excluded"])
        labels.update(row["audit"]["labelSources"])
    report = {"targetGames": limit, "convertedGames": len(saved), "resumedGames": resumed,
              "goalReached": len(saved) >= limit, "sourceGames": len(source_rows),
              "samples": sum(row["samples"] for row in saved.values()),
              "compressedBytes": sum(row["bytes"] for row in saved.values()),
              "sourceManifestSha256": digest(payload), "converterSignature": signature,
              "frozenSplit": split_audit,
              "selectedPartitions": split_audit["selectedPartitions"] if split_audit else None,
              "matchMetadata": {"knownGames": sum(row.get("matchMetadata") is not None for row in saved.values()),
                                "unknownGames": sum(row.get("matchMetadata") is None for row in saved.values()),
                                "fileSha256": digest(Path(metadata_file).read_bytes()) if metadata_file else None},
              "engineVersion": ENGINE_VERSION, "workers": workers,
              "sourcePlatform": next(iter(sources), None),
              "elapsedSeconds": time.monotonic() - started, "failedGames": failed,
              "actions": dict(actions), "labelSources": dict(labels), "excludedWindows": dict(exclusions),
              "limitations": ["Operation masks are reconstructed with riichienv, not official server masks.",
                              "Only verified first-through-third daiminkan suffixes are recovered; other kan suffixes remain excluded.",
                              "Competing claims and unresolved responses are censored.",
                              "Potential rob-North suffixes are excluded; no speculative pass labels are added.",
                              "Mahjong Soul match length stays unknown without verified header metadata.",
                              "Tenhou ranks and GO rules are verified against XML; matches with BYE are excluded.",
                              "Mahjong Soul throne classification comes from the archive publisher."]}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("convertedGames", "samples", "goalReached", "elapsedSeconds")}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--metadata", type=Path, help="Verified per-game official-header metadata sidecar")
    parser.add_argument("--split", type=Path, help="Convert exactly the games in this frozen split")
    parser.add_argument("--partitions", nargs="+", choices=("train", "validation", "test"),
                        help="Select frozen partitions; requires --split (default: all)")
    parser.add_argument("--tenhou-db-root", type=Path, help="Directory containing original Path of Houou SQLite files")
    args = parser.parse_args()
    report = convert_corpus(args.manifest, args.output, args.limit, args.workers, args.metadata,
                            args.split, args.tenhou_db_root, args.partitions)
    raise SystemExit(0 if report["goalReached"] else 2)


if __name__ == "__main__":
    main()
