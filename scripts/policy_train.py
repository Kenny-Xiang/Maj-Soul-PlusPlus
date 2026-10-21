#!/usr/bin/env python3
"""Train a small, mode-specific policy from validated policy_extract JSONL."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("samples", nargs="+", type=Path)
    parser.add_argument("--players", type=int, choices=(3, 4), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", choices=("cpu", "mps", "cuda"), default="cpu")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--smoke", action="store_true", help="all games in training, no held-out score; model cannot drive autoplay")
    args = parser.parse_args()
    import torch
    from policy_training import read_samples
    if args.threads < 1:
        parser.error("--threads must be positive")
    torch.set_num_threads(args.threads)
    started = time.monotonic()
    samples, audit = read_samples(args.samples, args.players)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=args.output.parent, prefix=".policy-", suffix=".npz", delete=False) as temporary:
        staged = Path(temporary.name)
    try:
        _train_and_verify(args, samples, audit, staged, started)
    finally:
        staged.unlink(missing_ok=True)


def _train_and_verify(args, samples, audit, staged, started):
    import torch
    from policy_training import train
    from policy_model import PolicyModel
    model, report = train(samples, {"channels": 64, "blocks": 3, "hidden": 256},
                          players=args.players, epochs=args.epochs, batch_size=args.batch_size,
                          learning_rate=args.learning_rate, seed=args.seed, device=args.device,
                          smoke=args.smoke, output=staged, report={"dataAudit": audit})
    # Verify the actual exported artifact against the training runtime.
    import numpy as np
    deployed = PolicyModel(staged)
    model.eval()
    error, matching = 0., True
    for sample in samples[:32]:
        inputs = [torch.as_tensor(sample[key][None], device=args.device) for key in ("planes", "globals", "actions")]
        mask = torch.ones((1, len(sample["actions"])), dtype=torch.bool, device=args.device)
        with torch.no_grad():
            expected = model(*inputs, mask).cpu().numpy()[0]
        actual = deployed.logits(sample["planes"], sample["globals"], sample["actions"])
        error = max(error, float(np.max(np.abs(actual - expected))))
        matching = matching and int(actual.argmax()) == int(expected.argmax())
    if error > 1e-4 or not matching:
        raise ValueError(f"export parity failed: max error={error}, argmax agreement={matching}")
    report.update({"exportParity": {"samples": min(32, len(samples)), "maxAbsError": error,
                                     "argmaxAgreement": matching},
                   "modelSha256": deployed.sha256, "elapsedSeconds": time.monotonic() - started})
    report_path = args.output.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    os.replace(staged, args.output)
    print(json.dumps({"model": str(args.output), "report": str(report_path),
                      "purpose": report["purpose"], "samples": len(samples)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
