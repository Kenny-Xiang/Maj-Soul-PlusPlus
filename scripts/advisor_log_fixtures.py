#!/usr/bin/env python3
"""Export public decision snapshots from a local log for advisor_compare.py.

The default corpus matches windows whose recorded recommendation was an
ordinary discard. --all-discard-windows also includes windows where an optional
riichi, kita, or kan was recommended. Selection never uses later game outcomes.
Keep complete local exports outside Git; commit only targeted regression cases.
"""
import argparse
import hashlib
import json
from pathlib import Path

from advisor_compare import load_cases


PUBLIC_FIELDS = """phase selfSeat hand handComplete historyComplete baseline
lastStep lastDraw left doras scores north riichi riichiPending doubleRiichi
doubleRiichiPending riichiStep riichiSticks furiten canAct canDiscard noCallsYet
canDoubleRiichi operations forbiddenDiscards playerCount replacementWin""".split()


def public_state(state):
    """Allowlist public engine inputs; discard identities and transport metadata."""
    result = {key: state[key] for key in PUBLIC_FIELDS if key in state}
    for key, fields in (("lastAction", ("name", "seat", "tile", "type", "step")),
                        ("round", ("chang", "ju", "ben", "isFinal", "isExtension"))):
        value = state.get(key)
        result[key] = {field: value[field] for field in fields if field in value} if value else value
    if state.get("match"):
        result["match"] = {field: state["match"][field] for field in
                           ("source", "category", "modeId", "room", "levelId", "levelIds", "playerCount", "roundCount")
                           if field in state["match"]}
    for key, fields in (("rivers", ("tile", "moqie", "riichi", "called", "step")),
                        ("melds", ("type", "tiles", "froms"))):
        result[key] = [[{field: value[field] for field in fields if field in value}
                        for value in group] for group in state.get(key, [])]
    result["operationDetails"] = [{field: value[field] for field in ("type", "combination") if field in value}
                                  for value in state.get("operationDetails", [])]
    return result


def log_cases(path, all_discard_windows=False):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    advice = {row["adviceKey"]: row["advice"] for row in rows if row.get("kind") == "advice"}
    cases = []
    for row in rows:
        if row.get("kind") != "turn":
            continue
        state = row["state"]
        operations = state.get("operations", [])
        if (not state.get("canAct") or not state.get("canDiscard") or 1 not in operations or
                any(operation in operations for operation in (8, 9))):
            continue
        recorded = advice.get(f"{row.get('session')}:{row.get('serial')}", {})
        if not all_discard_windows and (recorded.get("best") or {}).get("action") != "discard":
            continue
        cases.append({"id": f"log-{len(cases) + 1}-serial-{row['serial']}",
                      "tags": ["recorded", "discard-window"], "notes": "Local public-state replay; no outcome labels.",
                      "expectedStatus": "ready", "state": public_state(state)})
    if not cases:
        raise ValueError("No executable discard windows matched the requested log selection")
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, help="Local JSONL log; never uploaded")
    parser.add_argument("--fixtures", type=Path, action="append", default=[],
                        help="Also include an existing fixture file; repeat to combine sets")
    parser.add_argument("--all-discard-windows", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.log is None and not args.fixtures:
        parser.error("at least one --log or --fixtures input is required")
    cases = log_cases(args.log, args.all_discard_windows) if args.log else []
    for path in args.fixtures:
        cases.extend(load_cases(path))
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        parser.error("inputs contain duplicate case IDs")
    document = {"schemaVersion": 1, "cases": cases}
    if args.log:
        document["logSelection"] = {"sha256": hashlib.sha256(args.log.read_bytes()).hexdigest(),
                                    "allDiscardWindows": args.all_discard_windows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output.resolve()), "caseCount": len(cases)}))


if __name__ == "__main__":
    main()
