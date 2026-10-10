#!/usr/bin/env python3
"""Convert an audited MJAI corpus into per-game, training-ready sample shards."""
import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
import sys
import time

import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from policy_mjai import ENGINE_VERSION, extract_game


def digest(data):
    return hashlib.sha256(data).hexdigest()


def converter_signature():
    names = ["scripts/policy_convert_mjai.py", "src/policy_mjai.py", "src/policy_mjai_state.py",
             "src/policy_actions.py", "src/policy_features.py"]
    return digest(b"".join((ROOT / name).read_bytes() for name in names) + ENGINE_VERSION.encode())


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
        samples, audit = extract_game(events, identifier)
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
                "roomEvidence": row.get("roomEvidence")}
    except (ValueError, KeyError, TypeError, IndexError, OSError, zstandard.ZstdError) as error:
        return {"gameId": identifier, "error": f"{type(error).__name__}: {error}"}


def validate_saved(row, source, output, signature):
    """Bind resumed statistics to the saved shard and separate audit artifact."""
    try:
        identifier = row["gameId"]
        if (row.get("converterSignature") != signature or
                row["sourceSha256"] != source["compressedSha256"] or
                row["path"] != f"games/{identifier}.jsonl.zst" or
                row.get("roomEvidence") != source.get("roomEvidence")):
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


def convert_corpus(manifest, output, limit, workers):
    if version("riichienv") != ENGINE_VERSION:
        raise ValueError(f"conversion requires riichienv=={ENGINE_VERSION}")
    if limit < 1 or not 1 <= workers <= 8:
        raise ValueError("limit must be positive; workers must be 1..8")
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    payload = manifest.read_bytes()
    source_rows = [json.loads(line) for line in payload.splitlines() if line.strip()]
    by_id, hashes = {}, set()
    for row in source_rows:
        identifier = row["gameId"]
        if not re.fullmatch(r"\d{6}-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", identifier):
            raise ValueError("invalid Mahjong Soul game ID")
        if identifier in by_id or row["compressedSha256"] in hashes:
            raise ValueError("duplicate source game or content")
        by_id[identifier] = row
        hashes.add(row["compressedSha256"])
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
              "engineVersion": ENGINE_VERSION, "workers": workers,
              "elapsedSeconds": time.monotonic() - started, "failedGames": failed,
              "actions": dict(actions), "labelSources": dict(labels), "excludedWindows": dict(exclusions),
              "limitations": ["Operation masks are reconstructed with riichienv, not official server masks.",
                              "Windows after any kan are excluded until the next hand.",
                              "Competing claims and unresolved responses are censored.",
                              "Four-player MJAI only; east/half match length is unknown.",
                              "Throne classification comes from the archive publisher, not individual rank metadata."]}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("convertedGames", "samples", "goalReached", "elapsedSeconds")}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    report = convert_corpus(args.manifest, args.output, args.limit, args.workers)
    raise SystemExit(0 if report["goalReached"] else 2)


if __name__ == "__main__":
    main()
