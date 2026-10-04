"""Extract inbound ActionPrototype notifications from an exported capture.

Usage: python3 extract_actions.py capture.json extracted-actions.json
Only reads local files; no network access or browser control.
"""

import json
import sys
from pathlib import Path

from decode_sample import parse_fields


def extract(frames):
    actions = []
    for frame in frames:
        payload = bytes.fromhex(frame["hex"])
        if not payload or payload[0] != 1:
            continue
        wrapper = parse_fields(payload[1:])
        if wrapper.get(1, [b""])[0] != b".lq.ActionPrototype":
            continue
        action = parse_fields(wrapper[2][0])
        actions.append({
            "time": frame["time"],
            "step": action.get(1, [0])[0],
            "name": action[2][0].decode("utf-8"),
            "data": action.get(3, [b""])[0].hex(),
        })
    return actions


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: extract_actions.py capture.json output.json")
    result = extract(json.loads(Path(sys.argv[1]).read_text()))
    # Exclusive creation prevents overwriting an existing evidence file.
    with Path(sys.argv[2]).open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(f"Extracted {len(result)} ActionPrototype notifications")
