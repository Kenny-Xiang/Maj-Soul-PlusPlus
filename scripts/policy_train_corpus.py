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
    parser.add_argument("--encoded-cache", type=Path, help="Lossless source-bound per-game feature cache")
    parser.add_argument("--resume", action="store_true", help="Resume OUTPUT.resume.pt with identical source and hyperparameters")
    parser.add_argument("--checkpoint-every-games", type=int, default=1000)
    parser.add_argument("--game-window", type=int, default=1, help="Maximum games to shuffle together into batches")
    parser.add_argument("--final-lr-ratio", type=float, default=1., help="Final cosine learning-rate ratio; 1 keeps a constant rate")
    parser.add_argument("--action-weights", type=json.loads, default={}, help='Recorded-label loss weights, e.g. {"daiminkan":4}')
    parser.add_argument("--opportunity-weights", type=json.loads, default={}, help="Weight all windows offering these action types, including negatives")
    parser.add_argument("--validation-only", action="store_true", help="Do not load or evaluate test games")
    parser.add_argument("--train-game-limit", type=int, help="Fixed train prefix, only for validation-only experiments")
    parser.add_argument("--validation-game-limit", type=int, help="Fixed validation prefix, only for validation-only experiments")
    parser.add_argument("--save-epoch-models", action="store_true", help="Retain each validation-complete epoch for auditable selection")
    args = parser.parse_args()
    if args.threads < 1:
        parser.error("--threads must be positive")
    import torch
    from policy_corpus_training import train_corpus
    torch.set_num_threads(args.threads)
    _, report = train_corpus(args.manifest, args.output, players=args.players, epochs=args.epochs,
                             batch_size=args.batch_size, learning_rate=args.learning_rate,
                             seed=args.seed, device=args.device, max_games=args.max_games, split_file=args.split,
                             encoded_cache=args.encoded_cache, resume=args.resume,
                             checkpoint_every_games=args.checkpoint_every_games, game_window=args.game_window,
                             final_lr_ratio=args.final_lr_ratio, action_weights=args.action_weights,
                             opportunity_weights=args.opportunity_weights,
                             validation_only=args.validation_only, train_game_limit=args.train_game_limit,
                             validation_game_limit=args.validation_game_limit, save_epoch_models=args.save_epoch_models)
    print(json.dumps({"model": str(args.output), "report": str(args.output.with_suffix(".report.json")),
                      "purpose": report["purpose"], "selectedGames": report["dataAudit"]["selectedGames"],
                      "gameCounts": report["dataAudit"]["selectedGameCounts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
