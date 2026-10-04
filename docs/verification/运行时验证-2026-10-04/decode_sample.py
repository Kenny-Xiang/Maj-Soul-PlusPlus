"""Decode the captured sample locally; this script does not connect to the game.

Action-data deobfuscation reference:
https://github.com/Apricot-S/majsoulrpa/blob/main/src/majsoulrpa/screens/match/_action.py
Field-number reference:
https://github.com/Apricot-S/majsoulrpa/blob/main/src/majsoulrpa/assets/protocol/liqi.proto
"""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KEYS = (132, 94, 78, 66, 57, 162, 31, 96, 28)


def varint(data, pos):
    value = shift = 0
    while pos < len(data) and shift < 70:
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
        shift += 7
    raise ValueError("Invalid or truncated varint")


def parse_fields(data):
    result, pos = {}, 0
    while pos < len(data):
        tag, pos = varint(data, pos)
        field, wire = tag >> 3, tag & 7
        if not field:
            raise ValueError("Invalid field number")
        if wire == 0:
            value, pos = varint(data, pos)
        elif wire in (1, 2, 5):
            if wire == 2:
                length, pos = varint(data, pos)
            else:
                length = 8 if wire == 1 else 4
            if pos + length > len(data):
                raise ValueError("Truncated field")
            value = data[pos : pos + length]
            pos += length
        else:
            raise ValueError(f"Unsupported wire type: {wire}")
        result.setdefault(field, []).append(value)
    return result


def decode(action):
    data = bytes.fromhex(action["data"])
    plain = bytes(
        value ^ (((23 ^ len(data)) + 5 * i + KEYS[i % 9]) & 255)
        for i, value in enumerate(data)
    )
    fields = parse_fields(plain)
    event = {
        "time": datetime.fromtimestamp(
            action["time"] / 1000, ZoneInfo("Asia/Shanghai")
        ).isoformat(),
        "step": action["step"],
        "action": action["name"],
        "seat": fields.get(1, [0])[0],
    }
    if action["name"] in ("ActionDealTile", "ActionDiscardTile"):
        event["tile"] = fields[2][0].decode() if 2 in fields else None
    if action["name"] == "ActionDealTile":
        event["left_tile_count"] = fields.get(3, [0])[0]
        event["doras"] = [x.decode() for x in fields.get(6, [])]
    elif action["name"] == "ActionDiscardTile":
        event["moqie"] = bool(fields.get(5, [0])[0])
        event["is_liqi"] = bool(fields.get(3, [0])[0])
    elif action["name"] == "ActionChiPengGang":
        event["type"] = fields.get(2, [0])[0]
        event["tiles"] = [x.decode() for x in fields.get(3, [])]
        event["froms"] = []
        for packed in fields.get(4, []):
            if isinstance(packed, int):
                event["froms"].append(packed)
                continue
            pos = 0
            while pos < len(packed):
                seat, pos = varint(packed, pos)
                event["froms"].append(seat)
    elif action["name"] == "ActionBaBei":
        event["moqie"] = bool(fields.get(9, [0])[0])
    return event


if __name__ == "__main__":
    folder = Path(__file__).resolve().parent
    actions = json.loads((folder / "actions.json").read_text())
    decoded = [decode(action) for action in actions]
    (folder / "decoded-events.json").write_text(
        json.dumps(decoded, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"Decoded {len(decoded)} actions into decoded-events.json")
