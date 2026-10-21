#!/usr/bin/env python3
"""Verify and pre-encode a sample manifest with bounded per-worker memory."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--players", type=int, choices=(3, 4), required=True)
    parser.add_argument("--encoded-cache", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--split", type=Path, help="Verify and preserve this frozen whole-game split")
    parser.add_argument("--partitions", nargs="+", choices=("train", "validation", "test"),
                        help="Select frozen partitions; requires --split (default: all)")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    if args.partitions is not None and args.split is None:
        parser.error("--partitions requires --split")
    from policy_corpus_training import read_manifest, prepare_game_cache
    from policy_encoded_cache import encoder_signature
    partitions, _, audit = read_manifest(args.manifest, 42, split_file=args.split, partitions=args.partitions)
    rows = [row for group in partitions.values() for row in group]
    started, samples = time.monotonic(), 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        tasks = ((row, args.players, args.encoded_cache) for row in rows)
        for count, result in enumerate(pool.map(prepare_game_cache, tasks, chunksize=10), 1):
            samples += result
            if count % 100 == 0:
                print(json.dumps({"phase": "encoded-cache", "completedGames": count,
                                  "totalGames": len(rows), "samples": samples,
                                  "elapsedSeconds": round(time.monotonic() - started, 1)}), flush=True)
    print(json.dumps({"phase": "encoded-cache-complete", "games": len(rows), "samples": samples,
                      "manifestSha256": audit["manifestSha256"], "encoderSignature": encoder_signature(),
                      "selectedPartitions": audit["selectedPartitions"], "frozenSplit": audit.get("frozenSplit"),
                      "elapsedSeconds": time.monotonic() - started}), flush=True)


if __name__ == "__main__":
    main()
