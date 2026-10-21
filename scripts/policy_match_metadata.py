#!/usr/bin/env python3
"""Bind MJAI match length to verified local original official replay headers.

This tool does no network access. Unmatched games remain explicitly unknown.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from policy_metadata import THRONE_ROUND_COUNTS, validate_match_metadata
from policy_official_archive import OfficialArchive, valid_identifier


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verified_archive(path):
    path = Path(path).resolve()
    if not (path / "manifest.jsonl").is_file():
        raise ValueError("Official archive manifest is missing")
    return OfficialArchive(path, (path / "schema.liqi.json").read_bytes())


def metadata_record(archive, source):
    """The archive constructor has checked every header against its raw response."""
    identifier = valid_identifier(source["gameId"])
    row = archive.games[identifier]
    result = {"schemaVersion": 1, "gameId": identifier,
              "sourceCompressedSha256": source["compressedSha256"],
              "playerCount": 4, "modeId": row["modeId"],
              "roundCount": THRONE_ROUND_COUNTS[row["modeId"]],
              "provenance": {"kind": "official-header-config", "archive": str(archive.output),
                             "headSha256": row["files"]["head"]["sha256"],
                             "responseSha256": row["files"]["response"]["sha256"],
                             "schemaSha256": row["schemaSha256"]}}
    return validate_match_metadata(result, identifier, source["compressedSha256"])


def source_index(rows):
    result = {}
    for row in rows:
        identifier = valid_identifier(row["gameId"])
        if identifier in result:
            raise ValueError("Duplicate source game ID")
        result[identifier] = row
    return result


def load_metadata(path, source_rows):
    """Load sidecar rows with UUID/source hashes and original-response verification.

    Returns {gameId: match_metadata}. Absence from this map means unknown.
    Rechecking original evidence also prevents a modified sidecar mode from
    silently changing rules when resuming conversion.
    """
    sources, archives, result = source_index(source_rows), {}, {}
    for line in Path(path).read_bytes().splitlines():
        if not line.strip():
            continue
        metadata = validate_match_metadata(json.loads(line))
        identifier = metadata["gameId"]
        if identifier in result or identifier not in sources:
            raise ValueError("Duplicate or unmatched match metadata game ID")
        source = sources[identifier]
        validate_match_metadata(metadata, identifier, source["compressedSha256"])
        archive_path = metadata["provenance"]["archive"]
        if archive_path not in archives:
            archives[archive_path] = verified_archive(archive_path)
        archive = archives[archive_path]
        if identifier not in archive.games or metadata != metadata_record(archive, source):
            raise ValueError("Match metadata differs from its original official response")
        result[identifier] = metadata
    return result


def build_metadata(official_archive, corpus_manifest, output):
    payload = Path(corpus_manifest).read_bytes()
    sources = source_index(json.loads(line) for line in payload.splitlines() if line.strip())
    archive = verified_archive(official_archive)
    rows = [metadata_record(archive, sources[identifier]) for identifier in sorted(sources)
            if identifier in archive.games]
    data = b"".join((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
                    for row in rows)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.read_bytes() != data:
        raise ValueError("Existing metadata differs; choose a new output file")
    output.write_bytes(data)
    report = {"sourceGames": len(sources), "knownMatchGames": len(rows),
              "unknownMatchGames": len(sources) - len(rows),
              "modeIds": dict(Counter(row["modeId"] for row in rows)),
              "sourceManifestSha256": digest(payload), "metadataSha256": digest(data),
              "officialArchiveGames": archive.count,
              "networkRequests": 0, "inferredFromFutureEvents": False}
    output.with_suffix(".report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-archive", type=Path, required=True)
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_metadata(args.official_archive, args.corpus_manifest, args.output)))


if __name__ == "__main__":
    main()
