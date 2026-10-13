#!/usr/bin/env python3
"""Train from per-game sample shards with disjoint game splits and bounded RAM."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--players", type=int, choices=(3, 4), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", choices=("cpu", "mps", "cuda"), default="cpu")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--max-games", type=int, help="Deterministic game subset for a limited pipeline check")
    parser.add_argument("--split", type=Path, help="Frozen source-bound whole-game partitions")
    args = parser.parse_args()
    if args.threads < 1:
        parser.error("--threads must be positive")
    import torch
    from policy_corpus_training import train_corpus
    torch.set_num_threads(args.threads)
    _, report = train_corpus(args.manifest, args.output, players=args.players, epochs=args.epochs,
                             batch_size=args.batch_size, learning_rate=args.learning_rate,
                             seed=args.seed, device=args.device, max_games=args.max_games, split_file=args.split)
    print(json.dumps({"model": str(args.output), "report": str(args.output.with_suffix(".report.json")),
                      "purpose": report["purpose"], "selectedGames": report["dataAudit"]["selectedGames"],
                      "gameCounts": report["dataAudit"]["selectedGameCounts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
