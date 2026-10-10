#!/usr/bin/env python3
"""Inspect a trained policy on a visible-state JSON or one extracted sample."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("state", type=Path, help="snapshot JSON, extracted JSONL, or sample JSON")
    parser.add_argument("--line", type=int, default=1, help="1-based JSONL decision to inspect")
    args = parser.parse_args()
    if args.line < 1:
        parser.error("--line must be positive")
    text = args.state.read_text()
    if args.state.suffix == ".jsonl":
        rows = [line for line in text.splitlines() if line.strip()]
        if args.line > len(rows):
            parser.error("--line exceeds sample count")
        text = rows[args.line - 1]
    item = json.loads(text)
    state = item.get("state", item)
    from policy_model import PolicyAdvisor
    result = PolicyAdvisor({state["playerCount"]: args.model})(state)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
