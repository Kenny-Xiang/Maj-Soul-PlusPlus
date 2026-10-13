#!/usr/bin/env python3
"""Freeze whole-game partitions, reserving previously inspected calibration games."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from policy_split import freeze_split


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--preferred-manifest", type=Path, required=True)
    parser.add_argument("--excluded", type=Path, required=True, help="JSON gameId to exclusion reason")
    parser.add_argument("--count", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = lambda path: [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    result = freeze_split(rows(args.corpus), [r["gameId"] for r in rows(args.preferred_manifest)],
                          json.loads(args.excluded.read_text()), count=args.count, seed=args.seed)
    data = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        if args.output.read_text() != data:
            raise ValueError("existing frozen split differs; choose a new output path")
    else:
        with args.output.open("x") as stream:
            stream.write(data)
    print(json.dumps({"output": str(args.output), "counts": {k: len(v) for k, v in result["groups"].items()},
                      "excludedGames": len(result["excluded"]), **result["selection"]}))


if __name__ == "__main__":
    main()
